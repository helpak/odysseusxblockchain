"""Service de l'IA : file de requêtes, attribution aux mineurs, contrôle aléatoire.

Cycle d'une requête :
  1. L'API (/v1/chat/completions) ou le benchmark dépose une requête dans la file.
  2. Un mineur prêt à servir l'obtient par /api/jobs/next (attente longue).
  3. Il renvoie la réponse de son modèle ; le compte utilisateur est débité au
     prix du moment et le mineur gagne des points (1 point = 1 token servi).
  4. Une fraction (VERIFY_SAMPLE_RATE) des requêtes utilisateur est servie à
     température 0 puis rejouée par un AUTRE mineur (autre wallet). Réponses
     proches : réputation +1 pour les deux. Écart : un TROISIÈME mineur (autre
     wallet encore) départage ; celui qui s'écarte de l'arbitre perd 3 points
     de réputation et les points de sa réponse. Si l'arbitre ne rejoint
     personne, les deux sont sanctionnés. Sous REPUTATION_MIN_TO_SERVE, un
     nœud ne sert plus.

La file vit en mémoire : un redémarrage du coordinateur fait échouer les
requêtes en cours (jamais débitées), rien d'autre.
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
    """Estimation indépendante du mineur (≈ 4 caractères par token) : le mineur
    ne peut pas gonfler sa facturation en déclarant plus de tokens."""
    return max(1, len(text) // 4)


def messages_text(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


def with_network_prompt(messages: list[dict], system_prompt: str) -> list[dict]:
    """Le prompt système amélioré par le réseau passe en premier."""
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
    """Donne au nœud la plus ancienne requête qu'il a le droit de servir."""
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
        # Ménage : on ne garde que les requêtes en attente ; un contrôle que
        # personne ne peut prendre (pas assez de wallets distincts) est abandonné
        # au bout de VERIFY_MAX_WAIT, sans sanction pour personne.
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
    """Délai dépassé : la requête est close, une réponse tardive sera refusée."""
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
    """Clôture une requête servie. Retourne (points, message)."""
    payload = json.loads(job["payload"])
    with _lock:
        req = _requests.get(payload.get("request_id", ""))
        if req is None or req["status"] != "assigned" or req["node_id"] != node["id"]:
            return 0, "requête expirée ou inconnue"
        content = str(result.get("content", ""))[:200_000]
        if not content.strip():
            req["status"] = "queued"  # réponse vide : on remet la requête en file
            req["node_id"] = None
            _queue.insert(0, req["id"])
            return 0, "réponse vide refusée, requête remise en file"
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

    message = f"{tokens} tokens servis"
    points = tokens

    me = {"node_id": node["id"], "job_id": job["id"], "wallet": node["wallet"], "content": content}

    if req["kind"] == "serve" and req["sample"]:
        submit(
            req["messages"], req["max_tokens"], 0.0,
            kind="verify", exclude_wallets=[node["wallet"]], verify_of={"stage": 1, "a": me},
        )
        message += " (contrôle aléatoire programmé)"

    if req["kind"] == "verify" and req["verify_of"]:
        points, message = _judge(conn, req, me, points)

    req["event"].set()
    if req["kind"] == "verify":
        forget(req["id"])  # personne n'attend un contrôle : on libère la mémoire
    return points, message


def _sanction(conn, party: dict) -> None:
    _adjust_reputation(conn, party["node_id"], -settings.REPUTATION_FAIL)
    conn.execute("UPDATE jobs SET points = 0 WHERE id = ?", (party["job_id"],))


def _judge(conn, req: dict, me: dict, points: int) -> tuple[int, str]:
    """Étape 1 : contrôleur vs réponse d'origine. Étape 2 : arbitrage."""
    vo = req["verify_of"]
    threshold = settings.VERIFY_MIN_SIMILARITY
    if vo["stage"] == 1:
        a = vo["a"]
        sim = similarity(a["content"], me["content"])
        if sim >= threshold:
            _adjust_reputation(conn, a["node_id"], settings.REPUTATION_PASS)
            _adjust_reputation(conn, me["node_id"], settings.REPUTATION_PASS)
            return points, f"contrôle réussi (similarité {sim:.2f})"
        submit(
            req["messages"], req["max_tokens"], 0.0,
            kind="verify", exclude_wallets=[a["wallet"], me["wallet"]],
            verify_of={"stage": 2, "a": a, "b": me},
        )
        return points, f"écart constaté (similarité {sim:.2f}) : arbitrage par un troisième mineur"

    a, b = vo["a"], vo["b"]
    ok_a = similarity(a["content"], me["content"]) >= threshold
    ok_b = similarity(b["content"], me["content"]) >= threshold
    if ok_a and not ok_b:
        _sanction(conn, b)
        _adjust_reputation(conn, a["node_id"], settings.REPUTATION_PASS)
        return points, "arbitrage : le contrôleur s'écartait, il est sanctionné"
    if ok_b and not ok_a:
        _sanction(conn, a)
        _adjust_reputation(conn, b["node_id"], settings.REPUTATION_PASS)
        return points, "arbitrage : la réponse d'origine s'écartait, elle est sanctionnée"
    if not ok_a and not ok_b:
        _sanction(conn, a)
        _sanction(conn, b)
        return points, "arbitrage : aucune réponse ne concorde, les deux sont sanctionnées"
    return points, "arbitrage : les deux réponses concordent finalement"


def eligible(node) -> tuple[bool, str]:
    if node["node_type"] != "gpu":
        return False, "nœud de stockage"
    if not node["has_model"] or node["model"] != settings.NETWORK_MODEL:
        return False, f"modèle requis : {settings.NETWORK_MODEL} (déclaré : {node['model'] or 'aucun'})"
    if node["reputation"] < settings.REPUTATION_MIN_TO_SERVE:
        return False, f"réputation trop basse ({node['reputation']} < {settings.REPUTATION_MIN_TO_SERVE})"
    return True, ""


def wait_for(rid: str, timeout: float) -> dict | None:
    """Attente bloquante (threads internes : benchmark)."""
    req = get(rid)
    if req is None:
        return None
    if not req["event"].wait(timeout):
        expire(rid)
    return get(rid)


# Les points du benchmark comptent comme du travail utile (AQL), mais seul le
# service payé et ses contrôles se partagent l'USDT des utilisateurs.
assert set(QUEUE_KINDS) <= set(rewards.GPU_KINDS)
