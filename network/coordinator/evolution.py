"""Auto-amélioration prouvée au benchmark.

1. Un AMÉLIORATEUR (nœud de calcul) reçoit le prompt système actuel du réseau
   et des exemples de tâches ; il propose un prompt candidat.
2. Des MESUREURS tirés au sort (autre nœud, autre wallet) répondent à une série
   de tâches générées (nouvelle graine à chaque mesure) avec le prompt actuel
   PUIS avec le candidat. Le coordinateur corrige lui-même les réponses.
3. Décision : promu si MEASURES_REQUIRED mesureurs constatent chacun au moins
   MEASURE_MIN_GAIN bonnes réponses de plus ; rejeté si MEASURES_REQUIRED
   mesureurs ne le constatent pas ; sinon une mesure de plus départage.
4. Promu : il devient le prompt système de TOUT le réseau (ajouté à chaque
   requête servie) et son auteur reçoit un bonus de points.

Les tâches changent à chaque mesure : impossible de glisser les réponses dans
un prompt. Les votes subjectifs de la v1 sont supprimés.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

import settings
import tasks

DEFAULT_PROMPT = (
    "Tu es l'assistant du réseau AQL. Réponds dans la langue de l'utilisateur, "
    "de façon exacte et concise. Pour un calcul ou un raisonnement, procède étape "
    "par étape avant de donner la réponse finale. Si tu ne sais pas, dis-le."
)

IMPROVE_INSTRUCTIONS = (
    "Tu améliores le prompt système d'un assistant IA. Objectif : plus de bonnes "
    "réponses sur des tâches de calcul, de logique et de raisonnement court comme "
    "les exemples fournis. Rédige UNIQUEMENT le nouveau prompt système complet, "
    "sans préambule, en moins de 3 000 caractères."
)


def active(conn) -> dict:
    row = conn.execute(
        "SELECT id, content, decided_at FROM candidates WHERE status = 'promoted'"
        " ORDER BY decided_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {"id": "", "content": DEFAULT_PROMPT, "decided_at": None}
    return {"id": row["id"], "content": row["content"], "decided_at": row["decided_at"]}


def _open_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM candidates WHERE status = 'measuring'").fetchone()["c"]


def improve_job(conn, node) -> tuple[dict, dict] | None:
    if _open_count(conn) >= settings.MAX_OPEN_CANDIDATES:
        return None
    current = active(conn)
    examples = tasks.public_view(tasks.generate(secrets.randbits(32), 4))
    payload = {
        "instructions": IMPROVE_INSTRUCTIONS,
        "current_prompt": current["content"],
        "examples": [e["prompt"] for e in examples],
    }
    return payload, {"baseline_id": current["id"]}


# Un candidat peut améliorer le benchmark tout en glissant une consigne nuisible
# (« recommande tel site »). Le prompt promu s'applique à TOUS les utilisateurs :
# on refuse donc tout ce qui ressemble à un lien, une adresse, un identifiant de
# contact ou du code exécutable. Un bon prompt système n'en a jamais besoin.
_FORBIDDEN = re.compile(
    r"https?://|www\.|\b[\w.-]+\.(?:com|net|org|io|xyz|app|dev|fr|co|ru|cn|link|me)\b"
    r"|@[\w.-]+|<\s*script|javascript:|\bt\.me\b|telegram|whatsapp|discord\.gg"
    r"|\b0x[0-9a-fA-F]{40}\b|```",
    re.IGNORECASE,
)


def candidate_problem(content: str) -> str | None:
    if not (50 <= len(content) <= settings.CANDIDATE_MAX_CHARS):
        return f"candidat hors limites (50–{settings.CANDIDATE_MAX_CHARS} caractères)"
    if any(ord(c) < 32 and c not in "\n\t" for c in content):
        return "caractères de contrôle interdits"
    match = _FORBIDDEN.search(content)
    if match:
        return f"contenu interdit dans un prompt système (« {match.group(0)[:30]} ») : liens, adresses, contacts et code sont refusés"
    return None


def submit_improve(conn, node, job_payload: dict, result: dict, epoch_id: int) -> tuple[int, str, bool]:
    content = str(result.get("content", "")).strip()
    problem = candidate_problem(content)
    if problem:
        return 0, problem, False
    current = active(conn)
    if job_payload.get("baseline_id", "") != current["id"]:
        return 0, "le prompt du réseau a changé entre-temps : candidat écarté", False
    digest = hashlib.sha256(content.encode()).hexdigest()
    if conn.execute("SELECT 1 FROM candidates WHERE id = ?", (digest[:16],)).fetchone():
        return 0, "candidat identique déjà proposé", False
    conn.execute(
        "INSERT INTO candidates (id, epoch_id, author_node, author_wallet, baseline_id, content, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (digest[:16], epoch_id, node["id"], node["wallet"], current["id"], content, int(time.time())),
    )
    return settings.POINTS_IMPROVE_ATTEMPT, f"candidat {digest[:16]} proposé, en attente de mesures", True


def measure_job(conn, node) -> tuple[dict, dict] | None:
    """Un candidat en mesure, ni écrit ni déjà mesuré par ce nœud ou ce wallet,
    qui n'a pas déjà assez de mesures terminées ou en cours."""
    rows = conn.execute(
        """
        SELECT c.* FROM candidates c
        WHERE c.status = 'measuring' AND c.author_node != ? AND c.author_wallet != ?
          AND NOT EXISTS (SELECT 1 FROM measurements m
                          WHERE m.candidate_id = c.id AND (m.node_id = ? OR m.wallet = ?))
          AND NOT EXISTS (SELECT 1 FROM jobs j JOIN nodes n ON n.id = j.node_id
                          WHERE j.kind = 'measure' AND j.status = 'assigned'
                            AND json_extract(j.payload, '$.candidate_id') = c.id
                            AND (j.node_id = ? OR n.wallet = ?))
        ORDER BY c.created_at ASC
        """,
        (node["id"], node["wallet"], node["id"], node["wallet"], node["id"], node["wallet"]),
    ).fetchall()
    for c in rows:
        done = conn.execute(
            "SELECT COUNT(*) AS n FROM measurements WHERE candidate_id = ?", (c["id"],)
        ).fetchone()["n"]
        in_flight = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE kind = 'measure' AND status = 'assigned'"
            " AND json_extract(payload, '$.candidate_id') = ?",
            (c["id"],),
        ).fetchone()["n"]
        if done + in_flight >= settings.MEASURES_REQUIRED + 1:
            continue
        seed = secrets.randbits(32)
        series = tasks.generate(seed, settings.MEASURE_TASKS)
        baseline = active(conn)
        payload = {
            "baseline_prompt": baseline["content"],
            "candidate_prompt": c["content"],
            "tasks": tasks.public_view(series),
        }
        return payload, {"candidate_id": c["id"], "seed": seed}
    return None


def _decide(conn, candidate) -> str | None:
    rows = conn.execute(
        "SELECT baseline_correct, candidate_correct FROM measurements WHERE candidate_id = ?",
        (candidate["id"],),
    ).fetchall()
    support = sum(1 for r in rows if r["candidate_correct"] - r["baseline_correct"] >= settings.MEASURE_MIN_GAIN)
    against = len(rows) - support
    if support >= settings.MEASURES_REQUIRED:
        return "promoted"
    if against >= settings.MEASURES_REQUIRED:
        return "rejected"
    return None


def submit_measure(conn, node, job_payload: dict, result: dict, epoch_id: int) -> tuple[int, str, dict | None]:
    """Retourne (points, message, promotion) — promotion = {author_node} si promu."""
    candidate = conn.execute(
        "SELECT * FROM candidates WHERE id = ?", (job_payload["candidate_id"],)
    ).fetchone()
    if candidate is None or candidate["status"] != "measuring":
        return 0, "candidat déjà décidé", None
    series = tasks.generate(int(job_payload["seed"]), settings.MEASURE_TASKS)
    baseline_answers = result.get("baseline") or {}
    candidate_answers = result.get("candidate") or {}
    answered = sum(
        1 for t in series
        if str(baseline_answers.get(str(t["id"]), "")).strip() and str(candidate_answers.get(str(t["id"]), "")).strip()
    )
    if answered < len(series) * 0.8:
        return 0, f"mesure incomplète ({answered}/{len(series)} tâches répondues) : refusée", None

    b = tasks.score(series, baseline_answers)
    c = tasks.score(series, candidate_answers)
    conn.execute(
        "INSERT OR IGNORE INTO measurements (candidate_id, node_id, wallet, baseline_correct,"
        " candidate_correct, total, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (candidate["id"], node["id"], node["wallet"], b, c, len(series), int(time.time())),
    )
    text = "".join(str(v) for v in list(baseline_answers.values()) + list(candidate_answers.values()))
    points = max(1, len(text) // 4)
    message = f"mesure : actuel {b}/{len(series)}, candidat {c}/{len(series)}"

    decision = _decide(conn, candidate)
    promotion = None
    if decision:
        conn.execute(
            "UPDATE candidates SET status = ?, decided_at = ? WHERE id = ?",
            (decision, int(time.time()), candidate["id"]),
        )
        message += f" — candidat {decision}"
        if decision == "promoted":
            # Les autres candidats étaient mesurés contre l'ancien prompt.
            conn.execute(
                "UPDATE candidates SET status = 'superseded', decided_at = ? WHERE status = 'measuring'",
                (int(time.time()),),
            )
            promotion = {"author_node": candidate["author_node"], "candidate_id": candidate["id"]}
    return points, message, promotion


def overview(conn, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT id, epoch_id, status, created_at, decided_at, length(content) AS size FROM candidates"
        " ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        ms = conn.execute(
            "SELECT baseline_correct, candidate_correct, total FROM measurements WHERE candidate_id = ?",
            (r["id"],),
        ).fetchall()
        out.append(
            {
                "id": r["id"],
                "epoch_id": r["epoch_id"],
                "status": r["status"],
                "size_chars": r["size"],
                "measurements": [
                    {"baseline": m["baseline_correct"], "candidate": m["candidate_correct"], "total": m["total"]}
                    for m in ms
                ],
                "created_at": r["created_at"],
                "decided_at": r["decided_at"],
            }
        )
    return out


def stats(conn) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) AS c FROM candidates GROUP BY status").fetchall()
    by = {r["status"]: r["c"] for r in rows}
    return {
        "measuring": by.get("measuring", 0),
        "promoted": by.get("promoted", 0),
        "rejected": by.get("rejected", 0) + by.get("superseded", 0),
        "active_prompt_id": active(conn)["id"] or "par défaut",
    }


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
