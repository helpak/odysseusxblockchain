"""Self-improvement, proven on the benchmark.

1. An IMPROVER (compute node) receives the network's current system prompt
   and example tasks; it proposes a candidate prompt.
2. Randomly drawn MEASURERS (another node, another wallet) answer a series of
   generated tasks (new seed for every measurement) with the current prompt
   THEN with the candidate. The coordinator grades the answers itself.
3. Decision: promoted if MEASURES_REQUIRED measurers each see at least
   MEASURE_MIN_GAIN more correct answers; rejected if MEASURES_REQUIRED
   measurers do not; otherwise one more measurement breaks the tie.
4. Promoted: it becomes the system prompt of the WHOLE network (added to every
   request served) and its author receives bonus points.

The tasks change with every measurement: answers cannot be slipped into a
prompt. The subjective votes of v1 are gone.
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
    "You are the AQL network assistant. Answer in the user's language, accurately "
    "and concisely. For a calculation or a reasoning question, work step by step "
    "before giving the final answer. If you don't know, say so."
)

IMPROVE_INSTRUCTIONS = (
    "You are improving the system prompt of an AI assistant. Goal: more correct "
    "answers on calculation, logic and short reasoning tasks like the examples "
    "provided. Write ONLY the complete new system prompt, with no preamble, in "
    "under 3,000 characters."
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


# A candidate could improve the benchmark while slipping in a harmful instruction
# ("recommend this website"). The promoted prompt applies to ALL users, so
# anything that looks like a link, an address, a contact handle or executable
# code is refused. A good system prompt never needs any of those.
_FORBIDDEN = re.compile(
    r"https?://|www\.|\b[\w.-]+\.(?:com|net|org|io|xyz|app|dev|fr|co|ru|cn|link|me)\b"
    r"|@[\w.-]+|<\s*script|javascript:|\bt\.me\b|telegram|whatsapp|discord\.gg"
    r"|\b0x[0-9a-fA-F]{40}\b|```",
    re.IGNORECASE,
)


def candidate_problem(content: str) -> str | None:
    if not (50 <= len(content) <= settings.CANDIDATE_MAX_CHARS):
        return f"candidate out of bounds (50–{settings.CANDIDATE_MAX_CHARS} characters)"
    if any(ord(c) < 32 and c not in "\n\t" for c in content):
        return "control characters are not allowed"
    match = _FORBIDDEN.search(content)
    if match:
        return f"content not allowed in a system prompt (\"{match.group(0)[:30]}\"): links, addresses, contacts and code are refused"
    return None


def submit_improve(conn, node, job_payload: dict, result: dict, epoch_id: int) -> tuple[int, str, bool]:
    content = str(result.get("content", "")).strip()
    problem = candidate_problem(content)
    if problem:
        return 0, problem, False
    current = active(conn)
    if job_payload.get("baseline_id", "") != current["id"]:
        return 0, "the network prompt changed in the meantime: candidate discarded", False
    digest = hashlib.sha256(content.encode()).hexdigest()
    if conn.execute("SELECT 1 FROM candidates WHERE id = ?", (digest[:16],)).fetchone():
        return 0, "identical candidate already proposed", False
    conn.execute(
        "INSERT INTO candidates (id, epoch_id, author_node, author_wallet, baseline_id, content, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (digest[:16], epoch_id, node["id"], node["wallet"], current["id"], content, int(time.time())),
    )
    return settings.POINTS_IMPROVE_ATTEMPT, f"candidate {digest[:16]} proposed, awaiting measurements", True


def measure_job(conn, node) -> tuple[dict, dict] | None:
    """A candidate being measured, neither written nor already measured by this
    node or this wallet, that does not already have enough measurements done or
    in progress."""
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
    """Returns (points, message, promotion) — promotion = {author_node} if promoted."""
    candidate = conn.execute(
        "SELECT * FROM candidates WHERE id = ?", (job_payload["candidate_id"],)
    ).fetchone()
    if candidate is None or candidate["status"] != "measuring":
        return 0, "candidate already decided", None
    series = tasks.generate(int(job_payload["seed"]), settings.MEASURE_TASKS)
    baseline_answers = result.get("baseline") or {}
    candidate_answers = result.get("candidate") or {}
    answered = sum(
        1 for t in series
        if str(baseline_answers.get(str(t["id"]), "")).strip() and str(candidate_answers.get(str(t["id"]), "")).strip()
    )
    if answered < len(series) * 0.8:
        return 0, f"incomplete measurement ({answered}/{len(series)} tasks answered): refused", None

    b = tasks.score(series, baseline_answers)
    c = tasks.score(series, candidate_answers)
    conn.execute(
        "INSERT OR IGNORE INTO measurements (candidate_id, node_id, wallet, baseline_correct,"
        " candidate_correct, total, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (candidate["id"], node["id"], node["wallet"], b, c, len(series), int(time.time())),
    )
    text = "".join(str(v) for v in list(baseline_answers.values()) + list(candidate_answers.values()))
    points = max(1, len(text) // 4)
    message = f"measurement: current {b}/{len(series)}, candidate {c}/{len(series)}"

    decision = _decide(conn, candidate)
    promotion = None
    if decision:
        conn.execute(
            "UPDATE candidates SET status = ?, decided_at = ? WHERE id = ?",
            (decision, int(time.time()), candidate["id"]),
        )
        message += f" — candidate {decision}"
        if decision == "promoted":
            # The other candidates were measured against the old prompt.
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
        "active_prompt_id": active(conn)["id"] or "default",
    }


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
