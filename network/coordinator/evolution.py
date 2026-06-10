"""Boucle d'auto-amélioration : améliorateurs proposent, voteurs notent.

v1, honnête sur ce qu'elle fait : les candidats sont des artefacts textuels
(prompts système, skills, recettes de configuration) générés par les mineurs
GPU disposant d'un modèle local, puis notés par d'autres mineurs (les voteurs).
Un candidat qui atteint le quorum avec une moyenne suffisante est "promu" et
exposé sur /api/evolution/active, où le cœur IA (ai/) vient le consommer.

L'entraînement distribué de poids de modèles est la cible v2 ; le protocole
(candidats -> votes -> promotion -> récompenses) est déjà celui-là.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time

import db
import settings

# Objectifs d'amélioration distribués aux améliorateurs, en rotation.
GOALS = [
    "Rédiger un meilleur prompt système pour l'agent Odysseus sur les tâches de "
    "programmation : plus précis sur la lecture du code existant avant modification, "
    "la vérification des changements et le format des réponses.",
    "Rédiger une skill réutilisable 'résumé de longue conversation' : entrée, étapes, "
    "format de sortie, pièges à éviter.",
    "Améliorer le prompt de l'outil de recherche web d'Odysseus : reformulation des "
    "requêtes, croisement des sources, citation systématique.",
    "Rédiger une skill 'triage d'emails' : critères d'urgence, catégories, format du "
    "brouillon de réponse.",
    "Améliorer le prompt du mode Deep Research : plan de recherche, critères d'arrêt, "
    "structure du rapport final.",
]

VOTE_RUBRIC = (
    "Note ce candidat entre 0.0 et 1.0 selon : (1) répond-il précisément à l'objectif ? "
    "(2) est-il directement utilisable (structure claire, étapes concrètes) ? "
    "(3) est-il sans contenu générique ou placeholder ? "
    "Réponds UNIQUEMENT par un JSON: {\"score\": <0.0-1.0>, \"rationale\": \"<une phrase>\"}"
)


def next_improve_goal(conn) -> str:
    count = conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE kind = 'improve'").fetchone()["c"]
    return GOALS[count % len(GOALS)]


def open_candidates_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM candidates WHERE status = 'proposed'"
    ).fetchone()["c"]


def candidate_needing_vote(conn, node_id: str):
    """Un candidat proposé, pas écrit par ce nœud, pas encore noté par lui."""
    return conn.execute(
        """
        SELECT * FROM candidates
        WHERE status = 'proposed' AND author_node != ?
          AND id NOT IN (SELECT candidate_id FROM votes WHERE node_id = ?)
        ORDER BY created_at ASC LIMIT 1
        """,
        (node_id, node_id),
    ).fetchone()


def create_candidate(conn, epoch_id: int, node_id: str, wallet: str, goal: str, content: str) -> str:
    candidate_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO candidates (id, epoch_id, author_node, author_wallet, goal, content,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (candidate_id, epoch_id, node_id, wallet, goal, content, int(time.time())),
    )
    return candidate_id


def record_vote(conn, candidate_id: str, node_id: str, score: float, rationale: str) -> dict:
    """Enregistre un vote ; décide promotion/rejet au quorum.

    Retourne {accepted, decided, status, bonus_wallet?} — le bonus de promotion
    est crédité à l'auteur via un job 'promotion_bonus' par l'appelant.
    """
    candidate = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if candidate is None:
        return {"accepted": False, "reason": "candidat inconnu"}
    if candidate["status"] != "proposed":
        return {"accepted": False, "reason": f"candidat déjà décidé ({candidate['status']})"}
    if candidate["author_node"] == node_id:
        return {"accepted": False, "reason": "un améliorateur ne vote pas pour lui-même"}

    score = max(0.0, min(1.0, float(score)))
    try:
        conn.execute(
            "INSERT INTO votes (candidate_id, node_id, score, rationale, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (candidate_id, node_id, score, rationale[:2000], int(time.time())),
        )
    except sqlite3.IntegrityError:
        return {"accepted": False, "reason": "vote déjà enregistré pour ce candidat"}

    votes = candidate["votes"] + 1
    score_sum = candidate["score_sum"] + score
    decided = votes >= settings.VOTE_QUORUM
    status = "proposed"
    result: dict = {"accepted": True, "decided": False, "status": status}

    if decided:
        average = score_sum / votes
        status = "promoted" if average >= settings.PROMOTE_SCORE else "rejected"
        conn.execute(
            "UPDATE candidates SET votes = ?, score_sum = ?, status = ?, decided_at = ?"
            " WHERE id = ?",
            (votes, score_sum, status, int(time.time()), candidate_id),
        )
        result.update(
            {
                "decided": True,
                "status": status,
                "average": round(average, 4),
                "author_node": candidate["author_node"],
                "author_wallet": candidate["author_wallet"],
            }
        )
    else:
        conn.execute(
            "UPDATE candidates SET votes = ?, score_sum = ? WHERE id = ?",
            (votes, score_sum, candidate_id),
        )
    return result


def active_promotions(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT id, epoch_id, goal, content, votes, score_sum, decided_at FROM candidates"
        " WHERE status = 'promoted' ORDER BY decided_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "epoch_id": row["epoch_id"],
            "goal": row["goal"],
            "content": row["content"],
            "votes": row["votes"],
            "average_score": round(row["score_sum"] / row["votes"], 4) if row["votes"] else 0,
            "decided_at": row["decided_at"],
        }
        for row in rows
    ]


def candidates_overview(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, epoch_id, goal, status, votes, score_sum, created_at FROM candidates"
        " ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "epoch_id": row["epoch_id"],
            "goal": row["goal"][:160],
            "status": row["status"],
            "votes": row["votes"],
            "average_score": round(row["score_sum"] / row["votes"], 4) if row["votes"] else None,
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def stats(conn) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS c FROM candidates GROUP BY status"
    ).fetchall()
    by_status = {row["status"]: row["c"] for row in rows}
    return {
        "proposed": by_status.get("proposed", 0),
        "promoted": by_status.get("promoted", 0),
        "rejected": by_status.get("rejected", 0),
        "vote_quorum": settings.VOTE_QUORUM,
        "promote_score": settings.PROMOTE_SCORE,
    }


def vote_rubric() -> str:
    return VOTE_RUBRIC


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
