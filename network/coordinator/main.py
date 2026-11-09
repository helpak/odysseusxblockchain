"""AQL network coordinator — FastAPI API.

Roles:
  - AI: user accounts (key + USDT credit), OpenAI-compatible API
    (/v1/chat/completions) served by the miners, automatic load-based pricing;
  - credits: reads on-chain payments (AQLNetwork.pay) and credits accounts automatically;
  - miners: node registry, job dispatch and verification
    (serve, verify, bench, improve, measure, store, challenge), reputation;
  - improvement: candidate prompts measured on the benchmark, automatic promotion;
  - public benchmark every 2 h, network vs reference models;
  - epochs: points -> AQL (halving) + USDT from the miner pool, merkle tree voted
    on-chain by the oracles (contracts/scripts/oracle-daemon.js).

Start:  uvicorn main:app --host 0.0.0.0 --port 9000   (a single worker)
"""

from __future__ import annotations

import asyncio
import base64
import collections
import contextlib
import json
import os
import secrets
import threading
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import accounts
import benchmark
import chain
import db
import evolution
import merkle
import pricing
import rewards
import serving
import settings
import storage_net

_boot = db.init()
rewards.init_genesis(_boot["genesis_ts"])
ADMIN_TOKEN = _boot["admin_token"]
if _boot["admin_token_generated"]:
    print(
        "\n=== AQL Coordinator ===\n"
        f"Admin token generated (stored in the database): {ADMIN_TOKEN}\n"
        "Use it in the X-Admin-Token header for the /api/admin/* routes.\n",
        flush=True,
    )


@contextlib.asynccontextmanager
async def lifespan(_app):
    chain.start_background()
    benchmark.start_background()
    yield


app = FastAPI(title="AQL Network — Coordinator", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Nodes currently waiting for a job: available serving capacity.
_waiting: set[str] = set()
_waiting_lock = threading.Lock()
# Account creation limit per IP.
_account_creations: dict[str, collections.deque] = collections.defaultdict(collections.deque)


# ---------------------------------------------------------------- models


class RegisterRequest(BaseModel):
    wallet: str
    node_type: str
    name: str = ""
    model: str = ""
    storage_allocated_gb: float = 0


class HeartbeatRequest(BaseModel):
    storage_allocated_gb: float | None = None


class SubmitRequest(BaseModel):
    job_id: str
    result: dict = {}


class ArchiveRequest(BaseModel):
    key: str
    data_b64: str


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    max_tokens: int = 1024
    temperature: float = 0.7
    stream: bool = False


# ---------------------------------------------------------------- helpers


def _auth_node(conn, node_id: str | None, node_token: str | None):
    if not node_id or not node_token:
        raise HTTPException(401, "X-Node-Id / X-Node-Token headers required")
    node = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if node is None or not secrets.compare_digest(node["token"], node_token):
        raise HTTPException(401, "unknown node or invalid token")
    return node


def _check_admin(token: str | None):
    if not token or not secrets.compare_digest(ADMIN_TOKEN, token):
        raise HTTPException(401, "invalid X-Admin-Token")


def _touch(conn, node_id: str):
    conn.execute("UPDATE nodes SET last_seen = ? WHERE id = ?", (int(time.time()), node_id))


def _fail_stale_jobs(conn, node_id: str):
    conn.execute(
        "UPDATE jobs SET status = 'failed', completed_at = ?"
        " WHERE node_id = ? AND status = 'assigned' AND created_at < ?",
        (int(time.time()), node_id, int(time.time()) - settings.JOB_STALE_SECONDS),
    )


def _insert_job(conn, node_id: str, kind: str, db_payload: dict, epoch: int) -> str:
    job_id = secrets.token_hex(12)
    conn.execute(
        "INSERT INTO jobs (id, node_id, kind, payload, epoch_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, node_id, kind, json.dumps(db_payload), epoch, int(time.time())),
    )
    return job_id


def _background_allowed(node_id: str) -> bool:
    """Improvement work must never delay users: it is only handed out if
    another node remains available to serve, or if no user has made a
    request in the last 10 minutes."""
    with _waiting_lock:
        others_waiting = len(_waiting - {node_id})
    return others_waiting >= 1 or serving.seconds_since_user_request() > 600


def _clean_messages(messages: list[dict]) -> list[dict]:
    clean = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role not in ("system", "user", "assistant") or not isinstance(content, str):
            raise HTTPException(400, "messages: every item requires role (system|user|assistant) and content (text)")
        clean.append({"role": role, "content": content})
    if not clean or sum(len(m["content"]) for m in clean) > 200_000:
        raise HTTPException(400, "messages empty or too long (200,000 characters max)")
    return clean


# ---------------------------------------------------------------- public routes


@app.get("/")
def root():
    return {"service": "AQL Network — Coordinator", "version": app.version, "epoch": rewards.current_epoch(), "docs": "/docs"}


@app.get("/api/stats")
def stats():
    now = int(time.time())
    epoch = rewards.current_epoch(now)
    _, epoch_end = rewards.epoch_bounds(epoch)
    reward = rewards.epoch_reward_wei(epoch)
    cutoff = now - settings.NODE_ACTIVE_WINDOW_SECONDS

    with db.write() as conn:
        price = pricing.price_for_epoch(conn, epoch)
        node_counts = {}
        for label, query, args in (
            ("gpu_nodes", "SELECT COUNT(*) AS c FROM nodes WHERE node_type = 'gpu'", ()),
            ("gpu_nodes_active", "SELECT COUNT(*) AS c FROM nodes WHERE node_type = 'gpu' AND last_seen >= ?", (cutoff,)),
            ("serving_nodes_active",
             "SELECT COUNT(*) AS c FROM nodes WHERE node_type = 'gpu' AND last_seen >= ? AND has_model = 1"
             " AND model = ? AND reputation >= ?",
             (cutoff, settings.NETWORK_MODEL, settings.REPUTATION_MIN_TO_SERVE)),
            ("storage_nodes", "SELECT COUNT(*) AS c FROM nodes WHERE node_type = 'storage'", ()),
            ("storage_nodes_active", "SELECT COUNT(*) AS c FROM nodes WHERE node_type = 'storage' AND last_seen >= ?", (cutoff,)),
        ):
            node_counts[label] = conn.execute(query, args).fetchone()["c"]
        row = conn.execute("SELECT tokens_served FROM epoch_stats WHERE epoch_id = ?", (epoch,)).fetchone()
        tokens_epoch = int(row["tokens_served"]) if row else 0
        util_prev = pricing.utilization_bps(conn, epoch - 1) if epoch > 0 else None
        bench = benchmark.history(conn, limit=10)
        storage_stats = storage_net.stats(conn)
        evolution_stats = evolution.stats(conn)

    with _waiting_lock:
        waiting = len(_waiting)
    latest_network = next((b for b in bench if b["target"] == "network"), None)

    return {
        "network": {**node_counts, "nodes_waiting_now": waiting, "queue_length": serving.queue_length()},
        "ai": {
            "model": settings.NETWORK_MODEL,
            "price_usdt_per_million_tokens": price / 1_000_000,
            "previous_epoch_utilization_pct": None if util_prev is None else util_prev / 100,
            "tokens_served_this_epoch": tokens_epoch,
            "latest_benchmark": latest_network,
        },
        "epoch": {
            "id": epoch,
            "seconds_remaining": max(0, epoch_end - now),
            "reward_wei": str(reward),
            "reward_aql": f"{reward / 10**18:,.0f}",
            "gpu_pool_bps": settings.GPU_POOL_BPS,
            "storage_pool_bps": settings.STORAGE_POOL_BPS,
        },
        "halving": {
            "interval_epochs": settings.HALVING_INTERVAL,
            "next_halving_epoch": rewards.next_halving_epoch(epoch),
            "epochs_until_halving": rewards.next_halving_epoch(epoch) - epoch,
        },
        "storage": storage_stats,
        "evolution": evolution_stats,
        "token": {
            "symbol": "AQL",
            "max_supply": "1000000000",
            "premine_pct": 0,
            "payment_split": {"miners_pct": 67, "stakers_pct": 33},
        },
        "payments_ingestion": chain.status(),
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
    """Full settlement of an epoch (root, earnings, proofs). Public: this data
    ends up on-chain and anyone can re-check their share."""
    with db.read() as conn:
        row = conn.execute("SELECT settlement FROM epochs WHERE id = ?", (epoch_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"epoch {epoch_id} not settled")
    return json.loads(row["settlement"])


@app.get("/api/rewards/{wallet}")
def wallet_rewards(wallet: str):
    try:
        return rewards.wallet_rewards(wallet)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/pricing")
def pricing_info():
    epoch = rewards.current_epoch()
    with db.write() as conn:
        price = pricing.price_for_epoch(conn, epoch)
        hist = pricing.history(conn)
    plans = [
        {**p, "approx_tokens": int(p["usdt"] * 1_000_000 * 1_000_000 // price)} for p in settings.PLANS
    ]
    return {
        "model": settings.NETWORK_MODEL,
        "price_usdt_per_million_tokens": price / 1_000_000,
        "rule": (
            f"Adjusted automatically every epoch based on load: at most ±{settings.PRICE_MAX_STEP * 100:g}% "
            f"per epoch, target {settings.PRICE_TARGET_UTILIZATION * 100:g}% utilization, "
            f"bounds {settings.PRICE_MIN_MICRO / 1e6:g}–{settings.PRICE_MAX_MICRO / 1e6:g} USDT per million tokens."
        ),
        "plans": plans,
        "requests_per_minute": settings.REQUESTS_PER_MINUTE,
        "history": hist,
    }


@app.get("/api/benchmark")
def benchmark_info():
    with db.read() as conn:
        hist = benchmark.history(conn, limit=120)
    return {
        "interval_hours": settings.BENCH_INTERVAL_SECONDS / 3600,
        "tasks_per_run": settings.BENCH_TASKS,
        "method": "Tasks generated from a public seed, graded automatically, "
                  "given identically to the network and to the reference models.",
        "references": [r["name"] for r in settings.BENCH_REFERENCES],
        "history": hist,
    }


@app.get("/api/evolution")
def evolution_info():
    with db.read() as conn:
        return {
            "active_prompt": evolution.active(conn),
            "rule": f"Promoted if {settings.MEASURES_REQUIRED} measurers each see at least "
                    f"{settings.MEASURE_MIN_GAIN} more correct answers out of {settings.MEASURE_TASKS}.",
            "candidates": evolution.overview(conn),
        }


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": settings.NETWORK_MODEL, "object": "model", "owned_by": "aql-network"}]}


# ---------------------------------------------------------------- accounts & AI


@app.post("/api/accounts")
def create_account(request: Request):
    ip = request.client.host if request.client else "?"
    window = _account_creations[ip]
    now = time.time()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= 10:
        raise HTTPException(429, "too many accounts created from this address, try again in a minute")
    window.append(now)
    with db.write() as conn:
        created = accounts.create(conn)
    return {
        **created,
        "message": "Keep the key: it is shown only once. Credit the account with "
                   "AQLNetwork.pay(amount, account_ref).",
    }


@app.get("/api/accounts/me")
def account_me(authorization: str | None = Header(default=None)):
    with db.read() as conn:
        account = accounts.authenticate(conn, authorization)
        if account is None:
            raise HTTPException(401, "invalid access key")
        pays = conn.execute(
            "SELECT tx_hash, block_number, received_micro FROM payments WHERE account_id = ?"
            " ORDER BY block_number DESC LIMIT 20",
            (account["id"],),
        ).fetchall()
    return {
        "account_ref": "0x" + account["id"],
        "balance_usdt": account["balance_micro"] / 1_000_000,
        "spent_usdt": account["spent_micro"] / 1_000_000,
        "tokens_used": account["tokens_used"],
        "payments": [
            {"tx_hash": p["tx_hash"], "block": p["block_number"], "usdt": p["received_micro"] / 1_000_000} for p in pays
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, authorization: str | None = Header(default=None)):
    if req.stream:
        raise HTTPException(400, "stream=true is not supported yet")
    messages = _clean_messages(req.messages)
    epoch = rewards.current_epoch()
    with db.write() as conn:
        account = accounts.authenticate(conn, authorization)
        if account is None:
            raise HTTPException(401, "invalid access key (header Authorization: Bearer aql_…)")
        price = pricing.price_for_epoch(conn, epoch)
        prompt = evolution.active(conn)["content"]
    if not accounts.allow_request(account["id"]):
        raise HTTPException(429, f"limit of {settings.REQUESTS_PER_MINUTE} requests per minute reached")

    final_messages = serving.with_network_prompt(messages, prompt)
    max_tokens = max(1, min(req.max_tokens, settings.MAX_TOKENS_CAP))
    estimate = pricing.cost_micro(serving.estimate_tokens(serving.messages_text(final_messages)) + max_tokens, price)
    if not accounts.reserve(account["id"], int(account["balance_micro"]), estimate):
        raise HTTPException(
            402,
            f"insufficient credit: {account['balance_micro'] / 1e6:.6f} USDT available, "
            f"up to {estimate / 1e6:.6f} USDT required for this request",
        )
    rid = serving.submit(
        final_messages, max_tokens, req.temperature,
        kind="serve", account_id=account["id"], reserved_micro=estimate,
    )
    try:
        deadline = time.time() + settings.SERVE_TIMEOUT_SECONDS
        state = serving.get(rid)
        while time.time() < deadline and state and state["status"] not in ("done", "expired"):
            await asyncio.sleep(0.2)
            state = serving.get(rid)
        if not state or state["status"] != "done":
            serving.expire(rid)
            raise HTTPException(504, "no miner answered in time: request not charged")
        return {
            "id": "aql-" + rid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": settings.NETWORK_MODEL,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": state["content"]}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": state["prompt_tokens"],
                "completion_tokens": state["completion_tokens"],
                "total_tokens": state["tokens"],
            },
            "aql": {
                "cost_usdt": state["cost_micro"] / 1_000_000,
                "price_usdt_per_million_tokens": price / 1_000_000,
                "verified_sample": state["sample"],
            },
        }
    finally:
        accounts.release(account["id"], estimate)
        serving.forget(rid)


# ---------------------------------------------------------------- node routes


@app.post("/api/nodes/register")
def register_node(req: RegisterRequest):
    if req.node_type not in ("gpu", "storage"):
        raise HTTPException(400, "node_type must be 'gpu' or 'storage'")
    try:
        wallet = merkle.normalize_address(req.wallet)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if req.node_type == "storage" and req.storage_allocated_gb <= 0:
        raise HTTPException(400, "storage_allocated_gb required for a storage node")

    model = req.model.strip()[:120] if req.node_type == "gpu" else ""
    node_id = secrets.token_hex(12)
    token = secrets.token_hex(32)
    now = int(time.time())
    with db.write() as conn:
        conn.execute(
            "INSERT INTO nodes (id, token, wallet, node_type, name, has_model, model, reputation,"
            " storage_allocated_bytes, created_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                node_id, token, wallet, req.node_type, req.name[:80], 1 if model else 0, model,
                settings.REPUTATION_START, int(req.storage_allocated_gb * 1024**3), now, now,
            ),
        )
        node = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    ok, reason = serving.eligible(node) if req.node_type == "gpu" else (True, "")
    message = f"{req.node_type} node registered. Earnings will go to {wallet}."
    if not ok:
        message += f" WARNING: this node will receive no compute work — {reason}."
    return {
        "node_id": node_id,
        "node_token": token,
        "wallet": wallet,
        "network_model": settings.NETWORK_MODEL,
        "eligible": ok,
        "epoch": rewards.current_epoch(),
        "message": message,
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


def _pick_gpu_job(conn, node, epoch: int, allow_background: bool):
    req = serving.take(node)
    if req is not None:
        job_id = _insert_job(conn, node["id"], req["kind"], {"request_id": req["id"]}, epoch)
        return job_id, req["kind"], serving.job_payload(req)
    if not allow_background:
        return None
    picked = evolution.measure_job(conn, node)
    if picked:
        payload, db_payload = picked
        return _insert_job(conn, node["id"], "measure", db_payload, epoch), "measure", payload
    picked = evolution.improve_job(conn, node)
    if picked:
        payload, db_payload = picked
        return _insert_job(conn, node["id"], "improve", db_payload, epoch), "improve", payload
    return None


@app.post("/api/jobs/next")
async def next_job(
    x_node_id: str | None = Header(default=None),
    x_node_token: str | None = Header(default=None),
):
    """Long poll (up to LONG_POLL_SECONDS): a miner ready to serve receives a
    request as soon as it arrives, without polling in a loop."""
    epoch = rewards.current_epoch()
    with db.write() as conn:
        node = _auth_node(conn, x_node_id, x_node_token)
        _touch(conn, node["id"])
        _fail_stale_jobs(conn, node["id"])
        if node["node_type"] == "storage":
            job = storage_net.next_storage_job(conn, node)
            if not job:
                return {"job": None, "retry_in": 30, "epoch": epoch}
            job_id = _insert_job(conn, node["id"], job["kind"], job["db_payload"], epoch)
            return {"job": {"id": job_id, "kind": job["kind"], "payload": job["payload"]}, "epoch": epoch}
        ok, reason = serving.eligible(node)
    if not ok:
        return {"job": None, "retry_in": 60, "epoch": epoch, "reason": reason}

    node_id = node["id"]
    with _waiting_lock:
        _waiting.add(node_id)
    deadline = time.time() + settings.LONG_POLL_SECONDS
    try:
        while True:
            epoch = rewards.current_epoch()
            with db.write() as conn:
                node = _auth_node(conn, x_node_id, x_node_token)
                picked = _pick_gpu_job(conn, node, epoch, _background_allowed(node_id))
                if picked:
                    job_id, kind, payload = picked
                    if kind in serving.QUEUE_KINDS:
                        pricing.record(conn, epoch, assigned=1)
                    else:
                        pricing.record(conn, epoch, idle=1)
                    return {"job": {"id": job_id, "kind": kind, "payload": payload}, "epoch": epoch}
                if time.time() >= deadline:
                    pricing.record(conn, epoch, idle=1)
                    return {"job": None, "retry_in": 0, "epoch": epoch}
            await asyncio.sleep(0.25)
    finally:
        with _waiting_lock:
            _waiting.discard(node_id)


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
            raise HTTPException(404, "unknown job for this node")
        if job["status"] != "assigned":
            raise HTTPException(409, f"job already closed ({job['status']})")

        payload = json.loads(job["payload"])
        kind = job["kind"]
        points, message, status = 0, "", "done"

        if kind in serving.QUEUE_KINDS:
            points, message = serving.complete(conn, job, node, req.result, job["epoch_id"])
            if points == 0:
                status = "failed"

        elif kind == "improve":
            points, message, ok = evolution.submit_improve(conn, node, payload, req.result, job["epoch_id"])
            if not ok:
                status = "failed"

        elif kind == "measure":
            points, message, promotion = evolution.submit_measure(conn, node, payload, req.result, job["epoch_id"])
            if points == 0:
                status = "failed"
            if promotion:
                conn.execute(
                    "INSERT INTO jobs (id, node_id, kind, payload, status, points, epoch_id, created_at,"
                    " completed_at) VALUES (?, ?, 'promotion_bonus', ?, 'done', ?, ?, ?, ?)",
                    (
                        secrets.token_hex(12), promotion["author_node"],
                        json.dumps({"candidate_id": promotion["candidate_id"]}),
                        settings.POINTS_PROMOTION_BONUS, rewards.current_epoch(), now, now,
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
            raise HTTPException(400, f"unknown job type: {kind}")

        stored_result = {k: v for k, v in req.result.items() if k != "data_b64"}
        conn.execute(
            "UPDATE jobs SET status = ?, result = ?, points = ?, completed_at = ? WHERE id = ?",
            (status, json.dumps(stored_result)[:100_000], points, now, req.job_id),
        )
        reputation = conn.execute("SELECT reputation FROM nodes WHERE id = ?", (node["id"],)).fetchone()["reputation"]

    return {
        "accepted": status == "done",
        "points": points,
        "message": message,
        "reputation": reputation,
        "epoch": rewards.current_epoch(),
    }


# ---------------------------------------------------------------- admin routes


@app.post("/api/admin/epochs/{epoch_id}/settle")
def settle(epoch_id: int, usdt_pool: int = 0, x_admin_token: str | None = Header(default=None)):
    """`usdt_pool`: USDT in the miner pool available on-chain (AQLNetwork.minerPool),
    in base units, passed in by the oracle daemon."""
    _check_admin(x_admin_token)
    try:
        settlement = rewards.settle_epoch(epoch_id, usdt_pool)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {
        "epoch_id": settlement["epoch_id"],
        "merkle_root": settlement["merkle_root"],
        "epoch_reward_wei": settlement["epoch_reward_wei"],
        "aql_total": settlement["aql_total"],
        "usdt_total": settlement["usdt_total"],
        "claims": len(settlement["claims"]),
        "settlement_file": f"{settings.SETTLEMENTS_DIR}/epoch_{epoch_id}.json",
        "next_step": "the oracles vote on this epoch (contracts/scripts/oracle-daemon.js)",
    }


@app.post("/api/admin/benchmark/run")
def run_benchmark_now(x_admin_token: str | None = Header(default=None)):
    _check_admin(x_admin_token)
    threading.Thread(target=benchmark.run_once, daemon=True, name="benchmark-manual").start()
    return {"started": True, "results": "/api/benchmark"}


@app.get("/api/admin/payments/unmatched")
def unmatched_payments(x_admin_token: str | None = Header(default=None)):
    """Payments whose reference matches no account (typing error)."""
    _check_admin(x_admin_token)
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM payments WHERE credited = 0 ORDER BY block_number").fetchall()
    return {"payments": [dict(r) for r in rows]}


@app.post("/api/admin/storage/archive")
def archive(req: ArchiveRequest, x_admin_token: str | None = Header(default=None)):
    _check_admin(x_admin_token)
    try:
        data = base64.b64decode(req.data_b64, validate=True)
    except Exception:
        raise HTTPException(400, "invalid data_b64")
    if not data:
        raise HTTPException(400, "empty data")
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
