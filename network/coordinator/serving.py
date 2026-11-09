"""AI serving: request queue, assignment to miners, random checks.

Lifecycle of a request:
  1. The API (/v1/chat/completions) or the benchmark puts a request in the queue.
  2. A miner ready to serve picks it up via /api/jobs/next (long polling).
  3. It sends back its model's answer; the user account is charged at the
     current price and the miner earns points (1 point = 1 token served).
  4. A fraction (VERIFY_SAMPLE_RATE) of user requests is served at
     temperature 0, then replayed by ANOTHER miner (different wallet). Close
     answers: reputation +1 for both. Mismatch: a THIRD miner (yet another
     wallet) breaks the tie; whoever disagrees with the arbiter loses 3
     reputation points and the points for its answer. If the arbiter agrees
     with neither, both are penalized. Below REPUTATION_MIN_TO_SERVE, a
     node no longer serves.

The queue lives in memory: a coordinator restart makes in-flight
requests fail (never charged), nothing else.
"""

from __future__ import annotations

import difflib
import json
import random
import secrets
import threading
import time

import accounts
import pricing
import rewards
import settings

_lock = threading.Lock()
_queue: list[str] = []
_requests: dict[str, dict] = {}
_last_user_request = 0.0

QUEUE_KINDS = ("serve", "verify", "bench")
VERIFY_MAX_WAIT = 600


def estimate_tokens(text: str) -> int:
    """Estimate that does not depend on the miner (≈ 4 characters per token): the
    miner cannot inflate its billing by reporting more tokens."""
    return max(1, len(text) // 4)


def messages_text(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


def with_network_prompt(messages: list[dict], system_prompt: str) -> list[dict]:
    """The system prompt improved by the network goes first."""
    if not system_prompt:
        return list(messages)
    return [{"role": "system", "content": system_prompt}] + list(messages)


def submit(
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    *,
    kind: str = "serve",
    account_id: str | None = None,
    reserved_micro: int = 0,
    exclude_wallets: list[str] | None = None,
    verify_of: dict | None = None,
) -> str:
    sample = kind == "serve" and account_id is not None and random.random() < settings.VERIFY_SAMPLE_RATE
    if sample or kind in ("verify", "bench"):
        temperature = 0.0
    rid = secrets.token_hex(12)
    req = {
        "id": rid,
        "kind": kind,
        "account_id": account_id,
        "reserved_micro": reserved_micro,
        "messages": messages,
        "max_tokens": max(1, min(int(max_tokens), settings.MAX_TOKENS_CAP)),
        "temperature": float(temperature),
        "sample": sample,
        "exclude_wallets": list(exclude_wallets or []),
        "verify_of": verify_of,
        "status": "queued",
        "created": time.time(),
        "node_id": None,
        "content": None,
        "tokens": 0,
        "cost_micro": 0,
        "event": threading.Event(),
    }
    global _last_user_request
    with _lock:
        _requests[rid] = req
        _queue.append(rid)
        if kind == "serve" and account_id is not None:
            _last_user_request = time.time()
    return rid


def seconds_since_user_request() -> float:
    return time.time() - _last_user_request


def get(rid: str) -> dict | None:
    with _lock:
        return _requests.get(rid)


def queue_length() -> int:
    with _lock:
        return sum(1 for rid in _queue if _requests.get(rid, {}).get("status") == "queued")


def take(node) -> dict | None:
    """Gives the node the oldest request it is allowed to serve."""
    with _lock:
        for i, rid in enumerate(_queue):
            req = _requests.get(rid)
            if req is None or req["status"] != "queued":
                continue
            if node["wallet"] in req["exclude_wallets"]:
                continue
            _queue.pop(i)
            req["status"] = "assigned"
            req["node_id"] = node["id"]
            req["node_wallet"] = node["wallet"]
            req["assigned_at"] = time.time()
            return req
        # Cleanup: only queued requests are kept; a check that nobody
        # can take (not enough distinct wallets) is dropped after
        # VERIFY_MAX_WAIT, with no penalty for anyone.
        now = time.time()
        keep = []
        for r in _queue:
            req = _requests.get(r)
            if req is None or req["status"] != "queued":
                continue
            if req["kind"] == "verify" and now - req["created"] > VERIFY_MAX_WAIT:
                _requests.pop(r, None)
                continue
            keep.append(r)
        _queue[:] = keep
    return None


def expire(rid: str) -> None:
    """Timeout reached: the request is closed, a late answer will be refused."""
    with _lock:
        req = _requests.get(rid)
        if req and req["status"] in ("queued", "assigned"):
            req["status"] = "expired"
            req["event"].set()


def forget(rid: str) -> None:
    with _lock:
        _requests.pop(rid, None)


def job_payload(req: dict) -> dict:
    return {
        "request_id": req["id"],
        "model": settings.NETWORK_MODEL,
        "messages": req["messages"],
        "max_tokens": req["max_tokens"],
        "temperature": req["temperature"],
    }


def similarity(a: str, b: str) -> float:
    a, b = (a or "")[:4_000], (b or "")[:4_000]
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _adjust_reputation(conn, node_id: str, delta: int) -> None:
    conn.execute(
        "UPDATE nodes SET reputation = MAX(0, MIN(?, reputation + ?)) WHERE id = ?",
        (settings.REPUTATION_MAX, delta, node_id),
    )


def complete(conn, job, node, result: dict, epoch_id: int) -> tuple[int, str]:
    """Closes a served request. Returns (points, message)."""
    payload = json.loads(job["payload"])
    with _lock:
        req = _requests.get(payload.get("request_id", ""))
        if req is None or req["status"] != "assigned" or req["node_id"] != node["id"]:
            return 0, "request expired or unknown"
        content = str(result.get("content", ""))[:200_000]
        if not content.strip():
            req["status"] = "queued"  # empty answer: put the request back in the queue
            req["node_id"] = None
            _queue.insert(0, req["id"])
            return 0, "empty answer refused, request put back in the queue"
        req["content"] = content
        req["prompt_tokens"] = estimate_tokens(messages_text(req["messages"]))
        req["completion_tokens"] = estimate_tokens(content)
        req["tokens"] = req["prompt_tokens"] + req["completion_tokens"]
        req["status"] = "done"

    tokens = req["tokens"]
    pricing.record(conn, epoch_id, tokens=tokens)

    if req["kind"] == "serve" and req["account_id"]:
        price = pricing.price_for_epoch(conn, epoch_id)
        req["cost_micro"] = accounts.charge(conn, req["account_id"], pricing.cost_micro(tokens, price), tokens)

    message = f"{tokens} tokens served"
    points = tokens

    me = {"node_id": node["id"], "job_id": job["id"], "wallet": node["wallet"], "content": content}

    if req["kind"] == "serve" and req["sample"]:
        submit(
            req["messages"], req["max_tokens"], 0.0,
            kind="verify", exclude_wallets=[node["wallet"]], verify_of={"stage": 1, "a": me},
        )
        message += " (random check scheduled)"

    if req["kind"] == "verify" and req["verify_of"]:
        points, message = _judge(conn, req, me, points)

    req["event"].set()
    if req["kind"] == "verify":
        forget(req["id"])  # nobody waits on a check: free the memory
    return points, message


def _sanction(conn, party: dict) -> None:
    _adjust_reputation(conn, party["node_id"], -settings.REPUTATION_FAIL)
    conn.execute("UPDATE jobs SET points = 0 WHERE id = ?", (party["job_id"],))


def _judge(conn, req: dict, me: dict, points: int) -> tuple[int, str]:
    """Stage 1: checker vs original answer. Stage 2: arbitration."""
    vo = req["verify_of"]
    threshold = settings.VERIFY_MIN_SIMILARITY
    if vo["stage"] == 1:
        a = vo["a"]
        sim = similarity(a["content"], me["content"])
        if sim >= threshold:
            _adjust_reputation(conn, a["node_id"], settings.REPUTATION_PASS)
            _adjust_reputation(conn, me["node_id"], settings.REPUTATION_PASS)
            return points, f"check passed (similarity {sim:.2f})"
        submit(
            req["messages"], req["max_tokens"], 0.0,
            kind="verify", exclude_wallets=[a["wallet"], me["wallet"]],
            verify_of={"stage": 2, "a": a, "b": me},
        )
        return points, f"mismatch found (similarity {sim:.2f}): arbitration by a third miner"

    a, b = vo["a"], vo["b"]
    ok_a = similarity(a["content"], me["content"]) >= threshold
    ok_b = similarity(b["content"], me["content"]) >= threshold
    if ok_a and not ok_b:
        _sanction(conn, b)
        _adjust_reputation(conn, a["node_id"], settings.REPUTATION_PASS)
        return points, "arbitration: the checker disagreed, it is penalized"
    if ok_b and not ok_a:
        _sanction(conn, a)
        _adjust_reputation(conn, b["node_id"], settings.REPUTATION_PASS)
        return points, "arbitration: the original answer disagreed, it is penalized"
    if not ok_a and not ok_b:
        _sanction(conn, a)
        _sanction(conn, b)
        return points, "arbitration: no answer matches, both are penalized"
    return points, "arbitration: both answers match after all"


def eligible(node) -> tuple[bool, str]:
    if node["node_type"] != "gpu":
        return False, "storage node"
    if not node["has_model"] or node["model"] != settings.NETWORK_MODEL:
        return False, f"required model: {settings.NETWORK_MODEL} (reported: {node['model'] or 'none'})"
    if node["reputation"] < settings.REPUTATION_MIN_TO_SERVE:
        return False, f"reputation too low ({node['reputation']} < {settings.REPUTATION_MIN_TO_SERVE})"
    return True, ""


def wait_for(rid: str, timeout: float) -> dict | None:
    """Blocking wait (internal threads: benchmark)."""
    req = get(rid)
    if req is None:
        return None
    if not req["event"].wait(timeout):
        expire(rid)
    return get(rid)


# Benchmark points count as useful work (AQL), but only paid service
# and its checks share the users' USDT.
assert set(QUEUE_KINDS) <= set(rewards.GPU_KINDS)
