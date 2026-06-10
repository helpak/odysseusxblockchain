"""Coordinateur du réseau Odysseus — API FastAPI.

Rôles :
  - registre des nœuds (mineurs GPU et nœuds de stockage), identifiés par wallet ;
  - distribution des jobs : vote / improve / bench pour les GPU,
    store / challenge pour le stockage ;
  - vérification des résultats et attribution des points (milli-points entiers) ;
  - règlement des époques : points -> ODY (halving), arbre merkle,
    fichier prêt pour contracts/scripts/submit-epoch.js ;
  - archivage de blobs (chiffrés par l'app appelante) sur le réseau de stockage.

Démarrage :  uvicorn main:app --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db
import evolution
import merkle
import rewards
import settings
import storage_net

app = FastAPI(title="Odysseus Network — Coordinateur", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

_boot = db.init()
rewards.init_genesis(_boot["genesis_ts"])
ADMIN_TOKEN = _boot["admin_token"]
if _boot["admin_token_generated"]:
    print(
        "\n=== Odysseus Coordinator ===\n"
        f"Jeton admin généré (persisté en base) : {ADMIN_TOKEN}\n"
        "Utilisez-le dans l'en-tête X-Admin-Token pour les routes /api/admin/*.\n",
        flush=True,
    )

IMPROVE_CONTEXT = (
    "Tu es un améliorateur du réseau Odysseus. Le cœur IA est Odysseus, un "
    "assistant self-hosted (chat, agent à outils, recherche web, mémoire). "
    "Produis un livrable directement utilisable répondant à l'objectif, en "
    "markdown structuré, sans préambule ni conclusion hors sujet."
)


# ---------------------------------------------------------------- modèles


class RegisterRequest(BaseModel):
    wallet: str
    node_type: str
    name: str = ""
    has_model: bool = False
    storage_allocated_gb: float = 0


class HeartbeatRequest(BaseModel):
    storage_allocated_gb: float | None = None


class SubmitRequest(BaseModel):
    job_id: str
    result: dict = {}


class ArchiveRequest(BaseModel):
    key: str
    data_b64: str


# ---------------------------------------------------------------- helpers


def _auth_node(conn, node_id: str | None, node_token: str | None):
    if not node_id or not node_token:
        raise HTTPException(401, "en-têtes X-Node-Id / X-Node-Token requis")
    node = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if node is None or not secrets.compare_digest(node["token"], node_token):
        raise HTTPException(401, "nœud inconnu ou jeton invalide")
    return node


def _check_admin(token: str | None):
    if not token or not secrets.compare_digest(ADMIN_TOKEN, token):
        raise HTTPException(401, "X-Admin-Token invalide")


def _touch(conn, node_id: str):
    conn.execute("UPDATE nodes SET last_seen = ? WHERE id = ?", (int(time.time()), node_id))


def _leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        bits += 8 - byte.bit_length()
        break
    return bits


def _verify_bench(payload: dict, result: dict) -> int:
    seed = bytes.fromhex(payload["seed"])
    target_bits = int(payload["target_bits"])
    valid, seen = 0, set()
    for raw in list(result.get("nonces", []))[: int(payload["max_nonces"])]:
        try:
            nonce = int(raw)
        except (TypeError, ValueError):
            continue
        if nonce < 0 or nonce >= 2**64 or nonce in seen:
            continue
        seen.add(nonce)
        digest = hashlib.sha256(seed + nonce.to_bytes(8, "big")).digest()
        if _leading_zero_bits(digest) >= target_bits:
            valid += 1
    return valid


def _fail_stale_jobs(conn, node_id: str):
    conn.execute(
        "UPDATE jobs SET status = 'failed', completed_at = ?"
        " WHERE node_id = ? AND status = 'assigned' AND created_at < ?",
        (int(time.time()), node_id, int(time.time()) - settings.JOB_STALE_SECONDS),
    )


def _next_gpu_job(conn, node) -> tuple[str, dict, dict] | None:
    """Retourne (kind, payload_envoyé_au_nœud, payload_stocké_en_base)."""
    candidate = evolution.candidate_needing_vote(conn, node["id"])
    if candidate is not None:
        payload = {
            "candidate_id": candidate["id"],
            "goal": candidate["goal"],
            "content": candidate["content"],
            "rubric": evolution.vote_rubric(),
        }
        return "vote", payload, {"candidate_id": candidate["id"]}

    if node["has_model"] and evolution.open_candidates_count(conn) < settings.MAX_OPEN_CANDIDATES:
        goal = evolution.next_improve_goal(conn)
        payload = {"goal": goal, "context": IMPROVE_CONTEXT}
        return "improve", payload, payload

    payload = {
        "seed": secrets.token_hex(16),
        "target_bits": settings.BENCH_TARGET_BITS,
        "duration_s": settings.BENCH_DURATION_S,
        "max_nonces": settings.BENCH_MAX_NONCES,
        "algo": "sha256(seed_hex_bytes || nonce_uint64_big_endian) avec >= target_bits bits à zéro en tête",
    }
    return "bench", payload, payload


# ---------------------------------------------------------------- routes publiques


@app.get("/")
def root():
    return {
        "service": "Odysseus Network — Coordinateur",
        "version": app.version,
        "epoch": rewards.current_epoch(),
        "docs": "/docs",
    }


@app.get("/api/stats")
def stats():
    now = int(time.time())
    epoch = rewards.current_epoch(now)
    _, epoch_end = rewards.epoch_bounds(epoch)
    reward = rewards.epoch_reward_wei(epoch)
    cutoff = now - settings.NODE_ACTIVE_WINDOW_SECONDS

    with db.read() as conn:
        def _count(node_type: str, active: bool) -> int:
            query = "SELECT COUNT(*) AS c FROM nodes WHERE node_type = ?"
            args: list = [node_type]
            if active:
                query += " AND last_seen >= ?"
                args.append(cutoff)
            return conn.execute(query, args).fetchone()["c"]

        def _epoch_points(kinds) -> int:
            placeholders = ",".join("?" for _ in kinds)
            row = conn.execute(
                f"SELECT COALESCE(SUM(points), 0) AS p FROM jobs"
                f" WHERE epoch_id = ? AND status = 'done' AND kind IN ({placeholders})",
                (epoch, *kinds),
            ).fetchone()
            return int(row["p"])

        storage_stats = storage_net.stats(conn)
        evolution_stats = evolution.stats(conn)
        network = {
            "gpu_nodes": _count("gpu", False),
            "gpu_nodes_active": _count("gpu", True),
            "storage_nodes": _count("storage", False),
            "storage_nodes_active": _count("storage", True),
        }
        epoch_points = {
            "gpu": _epoch_points(rewards.GPU_KINDS),
            "storage": _epoch_points(rewards.STORAGE_KINDS),
        }

    return {
        "network": network,
        "epoch": {
            "id": epoch,
            "seconds_remaining": max(0, epoch_end - now),
            "reward_wei": str(reward),
            "reward_ody": f"{reward / 10**18:,.0f}",
            "gpu_pool_bps": settings.GPU_POOL_BPS,
            "storage_pool_bps": settings.STORAGE_POOL_BPS,
            "points": epoch_points,
        },
        "halving": {
            "interval_epochs": settings.HALVING_INTERVAL,
            "next_halving_epoch": rewards.next_halving_epoch(epoch),
            "epochs_until_halving": rewards.next_halving_epoch(epoch) - epoch,
        },
        "storage": storage_stats,
        "evolution": evolution_stats,
        "token": {
            "symbol": "ODY",
            "max_supply": "1000000000",
            "founder_premine_pct": 10,
            "dividends_split": {"stakers_pct": 80, "founder_pct": 10, "staff_pct": 10},
        },
    }


@app.get("/api/epochs/current")
def current_epoch_info():
    epoch = rewards.current_epoch()
    start, end = rewards.epoch_bounds(epoch)
    return {
        "epoch_id": epoch,
        "starts_at": start,
        "ends_at": end,
        "reward_wei": str(rewards.epoch_reward_wei(epoch)),
        "epoch_seconds": settings.EPOCH_SECONDS,
        "genesis_ts": rewards.genesis_ts(),
    }


@app.get("/api/epochs/{epoch_id}/settlement")
def epoch_settlement(epoch_id: int):
    """Règlement complet d'une époque (racine, payouts, preuves).

    Public par conception : ces données finissent on-chain de toute façon.
    Consommé par l'oracle-daemon et par tout mineur voulant vérifier sa part.
    """
    with db.read() as conn:
        row = conn.execute("SELECT settlement FROM epochs WHERE id = ?", (epoch_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"époque {epoch_id} non réglée")
    return json.loads(row["settlement"])


@app.get("/api/rewards/{wallet}")
def wallet_rewards(wallet: str):
    try:
        return rewards.wallet_rewards(wallet)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/evolution/candidates")
def evolution_candidates():
    with db.read() as conn:
        return {"candidates": evolution.candidates_overview(conn)}


@app.get("/api/evolution/active")
def evolution_active():
    """Les améliorations promues — consommées par le cœur IA (ai/)."""
    with db.read() as conn:
        return {"promotions": evolution.active_promotions(conn)}


# ---------------------------------------------------------------- routes nœuds


@app.post("/api/nodes/register")
def register_node(req: RegisterRequest):
    if req.node_type not in ("gpu", "storage"):
        raise HTTPException(400, "node_type doit être 'gpu' ou 'storage'")
    try:
        wallet = merkle.normalize_address(req.wallet)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if req.node_type == "storage" and req.storage_allocated_gb <= 0:
        raise HTTPException(400, "storage_allocated_gb requis pour un nœud de stockage")

    node_id = secrets.token_hex(12)
    token = secrets.token_hex(32)
    now = int(time.time())
    with db.write() as conn:
        conn.execute(
            "INSERT INTO nodes (id, token, wallet, node_type, name, has_model,"
            " storage_allocated_bytes, created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                node_id,
                token,
                wallet,
                req.node_type,
                req.name[:80],
                1 if (req.has_model and req.node_type == "gpu") else 0,
                int(req.storage_allocated_gb * 1024**3),
                now,
                now,
            ),
        )
    return {
        "node_id": node_id,
        "node_token": token,
        "wallet": wallet,
        "epoch": rewards.current_epoch(),
        "message": f"Nœud {req.node_type} enregistré. Les récompenses iront à {wallet}.",
    }


@app.post("/api/nodes/heartbeat")
def heartbeat(
    req: HeartbeatRequest,
    x_node_id: str | None = Header(default=None),
    x_node_token: str | None = Header(default=None),
):
    with db.write() as conn:
        node = _auth_node(conn, x_node_id, x_node_token)
        _touch(conn, node["id"])
        if req.storage_allocated_gb is not None and node["node_type"] == "storage":
            conn.execute(
                "UPDATE nodes SET storage_allocated_bytes = ? WHERE id = ?",
                (int(req.storage_allocated_gb * 1024**3), node["id"]),
            )
    return {"ok": True, "epoch": rewards.current_epoch()}


@app.post("/api/jobs/next")
def next_job(
    x_node_id: str | None = Header(default=None),
    x_node_token: str | None = Header(default=None),
):
    epoch = rewards.current_epoch()
    with db.write() as conn:
        node = _auth_node(conn, x_node_id, x_node_token)
        _touch(conn, node["id"])
        _fail_stale_jobs(conn, node["id"])

        if node["node_type"] == "gpu":
            picked = _next_gpu_job(conn, node)
        else:
            job = storage_net.next_storage_job(conn, node)
            picked = (job["kind"], job["payload"], job["db_payload"]) if job else None

        if picked is None:
            return {"job": None, "retry_in": 30, "epoch": epoch}

        kind, payload, db_payload = picked
        job_id = secrets.token_hex(12)
        conn.execute(
            "INSERT INTO jobs (id, node_id, kind, payload, epoch_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, node["id"], kind, json.dumps(db_payload), epoch, int(time.time())),
        )
    return {"job": {"id": job_id, "kind": kind, "payload": payload}, "epoch": epoch}


@app.post("/api/jobs/submit")
def submit_job(
    req: SubmitRequest,
    x_node_id: str | None = Header(default=None),
    x_node_token: str | None = Header(default=None),
):
    now = int(time.time())
    with db.write() as conn:
        node = _auth_node(conn, x_node_id, x_node_token)
        _touch(conn, node["id"])
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (req.job_id,)).fetchone()
        if job is None or job["node_id"] != node["id"]:
            raise HTTPException(404, "job inconnu pour ce nœud")
        if job["status"] != "assigned":
            raise HTTPException(409, f"job déjà clôturé ({job['status']})")

        payload = json.loads(job["payload"])
        kind = job["kind"]
        points, message, status = 0, "", "done"

        if kind == "bench":
            valid = _verify_bench(payload, req.result)
            points = valid * settings.POINTS_PER_BENCH_NONCE
            message = f"{valid} nonce(s) valide(s) à {payload['target_bits']} bits"
            if valid == 0:
                status = "failed"

        elif kind == "improve":
            content = str(req.result.get("content", "")).strip()
            if not (50 <= len(content) <= 20_000):
                status, message = "failed", "contenu absent ou hors limites (50–20000 caractères)"
            else:
                candidate_id = evolution.create_candidate(
                    conn, job["epoch_id"], node["id"], node["wallet"], payload["goal"], content
                )
                points = settings.POINTS_PER_IMPROVE
                message = f"candidat {candidate_id} proposé, en attente de {settings.VOTE_QUORUM} votes"

        elif kind == "vote":
            outcome = evolution.record_vote(
                conn,
                payload["candidate_id"],
                node["id"],
                float(req.result.get("score", -1)),
                str(req.result.get("rationale", "")),
            )
            if not outcome["accepted"]:
                status, message = "failed", outcome["reason"]
            else:
                points = settings.POINTS_PER_VOTE
                message = "vote enregistré"
                if outcome["decided"]:
                    message += f" — candidat {outcome['status']} (moyenne {outcome['average']})"
                    if outcome["status"] == "promoted":
                        conn.execute(
                            "INSERT INTO jobs (id, node_id, kind, payload, status, points,"
                            " epoch_id, created_at, completed_at) VALUES (?, ?, 'promotion_bonus',"
                            " ?, 'done', ?, ?, ?, ?)",
                            (
                                secrets.token_hex(12),
                                outcome["author_node"],
                                json.dumps({"candidate_id": payload["candidate_id"]}),
                                settings.POINTS_PROMOTION_BONUS,
                                rewards.current_epoch(),
                                now,
                                now,
                            ),
                        )

        elif kind == "store":
            points, message = storage_net.handle_store_result(conn, node["id"], payload, req.result)
            if points == 0:
                status = "failed"

        elif kind == "challenge":
            points, message = storage_net.handle_challenge_result(conn, node["id"], payload, req.result)
            if points == 0:
                status = "failed"

        else:
            raise HTTPException(400, f"type de job inconnu: {kind}")

        conn.execute(
            "UPDATE jobs SET status = ?, result = ?, points = ?, completed_at = ? WHERE id = ?",
            (status, json.dumps(req.result)[:100_000], points, now, req.job_id),
        )

    return {"accepted": status == "done", "points": points, "message": message,
            "epoch": rewards.current_epoch()}


# ---------------------------------------------------------------- routes admin


@app.post("/api/admin/epochs/{epoch_id}/settle")
def settle(epoch_id: int, x_admin_token: str | None = Header(default=None)):
    _check_admin(x_admin_token)
    try:
        settlement = rewards.settle_epoch(epoch_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {
        "epoch_id": settlement["epoch_id"],
        "merkle_root": settlement["merkle_root"],
        "reward_wei": settlement["reward_wei"],
        "total_payout_wei": settlement["total_payout_wei"],
        "claims": len(settlement["claims"]),
        "settlement_file": f"{settings.SETTLEMENTS_DIR}/epoch_{epoch_id}.json",
        "next_step": "node contracts/scripts/submit-epoch.js <settlement_file>",
    }


@app.post("/api/admin/storage/archive")
def archive(req: ArchiveRequest, x_admin_token: str | None = Header(default=None)):
    _check_admin(x_admin_token)
    try:
        data = base64.b64decode(req.data_b64, validate=True)
    except Exception:
        raise HTTPException(400, "data_b64 invalide")
    if not data:
        raise HTTPException(400, "données vides")
    with db.write() as conn:
        try:
            return storage_net.archive(conn, req.key[:200], data)
        except ValueError as exc:
            raise HTTPException(409, str(exc))


@app.get("/api/admin/storage/retrieve/{key}")
def retrieve(key: str, x_admin_token: str | None = Header(default=None)):
    _check_admin(x_admin_token)
    with db.read() as conn:
        try:
            data = storage_net.retrieve(conn, key)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
    return {"key": key, "data_b64": base64.b64encode(data).decode()}
