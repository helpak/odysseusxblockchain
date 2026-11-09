"""Réseau de stockage : découpage en chunks, réplication, preuves par défi.

Modèle v1 (assumé et documenté) : le coordinateur garde la copie de référence
de chaque chunk — c'est elle qui permet de vérifier les défis et de garantir
la restitution. Les nœuds de stockage fournissent la redondance répliquée et
sont payés à la preuve : un défi demande le sha256(nonce || tranche aléatoire
du chunk), impossible à produire sans détenir réellement les octets.

Les données à archiver (ex. conversations) doivent être chiffrées par
l'application AVANT l'envoi : le réseau ne voit que des blobs opaques.
"""

from __future__ import annotations

import hashlib
import secrets
import time

import settings


def _mb(size: int) -> int:
    return max(1, size // (1024 * 1024))


def archive(conn, key: str, data: bytes) -> dict:
    """Découpe et enregistre un blob sous une clé. Refuse l'écrasement."""
    if conn.execute("SELECT 1 FROM chunks WHERE key = ? LIMIT 1", (key,)).fetchone():
        raise ValueError(f"clé déjà archivée: {key}")
    now = int(time.time())
    chunk_ids = []
    for seq, offset in enumerate(range(0, len(data), settings.CHUNK_BYTES)):
        blob = data[offset : offset + settings.CHUNK_BYTES]
        chunk_id = secrets.token_hex(16)
        conn.execute(
            "INSERT INTO chunks (id, key, seq, size, sha256, data, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chunk_id, key, seq, len(blob), hashlib.sha256(blob).hexdigest(), blob, now),
        )
        chunk_ids.append(chunk_id)
    return {"key": key, "chunks": len(chunk_ids), "bytes": len(data)}


def retrieve(conn, key: str) -> bytes:
    rows = conn.execute(
        "SELECT data FROM chunks WHERE key = ? ORDER BY seq", (key,)
    ).fetchall()
    if not rows:
        raise KeyError(f"clé inconnue: {key}")
    return b"".join(row["data"] for row in rows)


def _node_used_bytes(conn, node_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(c.size), 0) AS used
        FROM assignments a JOIN chunks c ON c.id = a.chunk_id
        WHERE a.node_id = ? AND a.status IN ('pending', 'stored')
        """,
        (node_id,),
    ).fetchone()
    return int(row["used"])


def next_storage_job(conn, node) -> dict | None:
    """Choisit le prochain travail d'un nœud de stockage.

    Priorités : 1) ré-envoyer un chunk accepté mais non confirmé,
    2) répliquer un chunk sous-répliqué, 3) défier un chunk stocké.
    Retourne {kind, payload, db_payload} ou None.
    """
    now = int(time.time())

    pending = conn.execute(
        "SELECT chunk_id FROM assignments WHERE node_id = ? AND status = 'pending' LIMIT 1",
        (node["id"],),
    ).fetchone()
    if pending:
        return _store_job(conn, pending["chunk_id"])

    free = node["storage_allocated_bytes"] - _node_used_bytes(conn, node["id"])
    candidate = conn.execute(
        """
        SELECT c.id, c.size FROM chunks c
        WHERE c.size <= ?
          AND (SELECT COUNT(*) FROM assignments a
               WHERE a.chunk_id = c.id AND a.status IN ('pending', 'stored')) < ?
          AND NOT EXISTS (SELECT 1 FROM assignments a2
                          WHERE a2.chunk_id = c.id AND a2.node_id = ?)
        ORDER BY c.created_at ASC LIMIT 1
        """,
        (free, settings.REPLICATION, node["id"]),
    ).fetchone()
    if candidate:
        conn.execute(
            "INSERT INTO assignments (chunk_id, node_id, status) VALUES (?, ?, 'pending')",
            (candidate["id"], node["id"]),
        )
        return _store_job(conn, candidate["id"])

    due = conn.execute(
        """
        SELECT a.chunk_id, c.size FROM assignments a JOIN chunks c ON c.id = a.chunk_id
        WHERE a.node_id = ? AND a.status = 'stored' AND a.last_challenge_at < ?
        ORDER BY a.last_challenge_at ASC LIMIT 1
        """,
        (node["id"], now - settings.CHALLENGE_INTERVAL_SECONDS),
    ).fetchone()
    if due:
        length = min(due["size"], 2048)
        offset = secrets.randbelow(max(1, due["size"] - length + 1))
        nonce = secrets.token_hex(16)
        # Marque le défi comme lancé pour ne pas le re-générer en boucle.
        conn.execute(
            "UPDATE assignments SET last_challenge_at = ? WHERE chunk_id = ? AND node_id = ?",
            (now, due["chunk_id"], node["id"]),
        )
        payload = {"chunk_id": due["chunk_id"], "offset": offset, "length": length, "nonce": nonce}
        return {"kind": "challenge", "payload": payload, "db_payload": payload}


def _store_job(conn, chunk_id: str) -> dict:
    import base64

    chunk = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    return {
        "kind": "store",
        # Les octets ne sont envoyés qu'au nœud ; pas besoin de les dupliquer
        # dans la table jobs.
        "payload": {
            "chunk_id": chunk["id"],
            "size": chunk["size"],
            "sha256": chunk["sha256"],
            "data_b64": base64.b64encode(chunk["data"]).decode(),
        },
        "db_payload": {"chunk_id": chunk["id"], "size": chunk["size"], "sha256": chunk["sha256"]},
    }


def handle_store_result(conn, node_id: str, payload: dict, result: dict) -> tuple[int, str]:
    """Confirme un stockage. Retourne (points, message)."""
    chunk_id = payload["chunk_id"]
    chunk = conn.execute("SELECT size, sha256 FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    assignment = conn.execute(
        "SELECT status FROM assignments WHERE chunk_id = ? AND node_id = ?",
        (chunk_id, node_id),
    ).fetchone()
    if chunk is None or assignment is None:
        return 0, "assignation inconnue"
    if assignment["status"] == "stored":
        return 0, "chunk déjà confirmé"
    if result.get("sha256") != chunk["sha256"]:
        conn.execute(
            "UPDATE assignments SET status = 'failed', fails = fails + 1"
            " WHERE chunk_id = ? AND node_id = ?",
            (chunk_id, node_id),
        )
        return 0, "sha256 incorrect : stockage refusé"
    now = int(time.time())
    conn.execute(
        "UPDATE assignments SET status = 'stored', stored_at = ?, last_challenge_at = ?"
        " WHERE chunk_id = ? AND node_id = ?",
        (now, now, chunk_id, node_id),
    )
    points = _mb(chunk["size"]) * settings.POINTS_STORE_PER_MB
    return points, f"chunk {chunk_id[:8]}… confirmé ({chunk['size']} octets)"


def handle_challenge_result(conn, node_id: str, payload: dict, result: dict) -> tuple[int, str]:
    """Vérifie une preuve de stockage. Retourne (points, message)."""
    chunk = conn.execute(
        "SELECT size, data FROM chunks WHERE id = ?", (payload["chunk_id"],)
    ).fetchone()
    if chunk is None:
        return 0, "chunk inconnu"
    offset, length = int(payload["offset"]), int(payload["length"])
    expected = hashlib.sha256(
        bytes.fromhex(payload["nonce"]) + chunk["data"][offset : offset + length]
    ).hexdigest()
    if result.get("digest") == expected:
        points = _mb(chunk["size"]) * settings.POINTS_CHALLENGE_PER_MB
        return points, "preuve de stockage valide"

    row = conn.execute(
        "SELECT fails FROM assignments WHERE chunk_id = ? AND node_id = ?",
        (payload["chunk_id"], node_id),
    ).fetchone()
    fails = (row["fails"] if row else 0) + 1
    status = "failed" if fails >= settings.MAX_CHALLENGE_FAILS else "stored"
    conn.execute(
        "UPDATE assignments SET fails = ?, status = ? WHERE chunk_id = ? AND node_id = ?",
        (fails, status, payload["chunk_id"], node_id),
    )
    if status == "failed":
        return 0, "preuve invalide : réplique retirée, le chunk sera ré-attribué"
    return 0, f"preuve invalide ({fails}/{settings.MAX_CHALLENGE_FAILS} échecs)"


def stats(conn) -> dict:
    chunks = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM chunks"
    ).fetchone()
    stored = conn.execute(
        """
        SELECT COUNT(*) AS n, COALESCE(SUM(c.size), 0) AS bytes
        FROM assignments a JOIN chunks c ON c.id = a.chunk_id
        WHERE a.status = 'stored'
        """
    ).fetchone()
    allocated = conn.execute(
        "SELECT COALESCE(SUM(storage_allocated_bytes), 0) AS b FROM nodes"
        " WHERE node_type = 'storage'"
    ).fetchone()
    return {
        "chunks": chunks["n"],
        "archived_bytes": int(chunks["bytes"]),
        "replicated_bytes": int(stored["bytes"]),
        "stored_replicas": stored["n"],
        "allocated_bytes": int(allocated["b"]),
        "replication_target": settings.REPLICATION,
    }
