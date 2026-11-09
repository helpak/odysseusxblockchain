"""Comptes utilisateurs de l'IA : clé d'accès, crédit en USDT, limite de débit.

- L'identifiant de compte (32 octets) sert aussi de référence de paiement :
  l'utilisateur appelle AQLNetwork.pay(montant, 0x<identifiant>) et le crédit
  arrive tout seul sur son compte (lecture des événements Paid, cf. chain.py).
- La clé d'accès n'est stockée que hachée (sha256) : une fuite de la base ne
  permet pas de consommer le crédit des utilisateurs.
- Montants en micro-USDT (1 USDT = 1 000 000), comme les 6 décimales de l'USDT.
"""

from __future__ import annotations

import collections
import hashlib
import re
import secrets
import threading
import time

import settings

_lock = threading.Lock()
_reserved: dict[str, int] = collections.defaultdict(int)
_recent: dict[str, collections.deque] = collections.defaultdict(collections.deque)

_ACCOUNT_RE = re.compile(r"^[0-9a-f]{64}$")


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def create(conn) -> dict:
    account_id = secrets.token_hex(32)
    api_key = "aql_" + secrets.token_hex(24)
    conn.execute(
        "INSERT INTO accounts (id, key_hash, created_at) VALUES (?, ?, ?)",
        (account_id, _hash_key(api_key), int(time.time())),
    )
    return {"account_id": account_id, "account_ref": "0x" + account_id, "api_key": api_key}


def authenticate(conn, authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    key = authorization.split(" ", 1)[1].strip()
    if not key.startswith("aql_"):
        return None
    return conn.execute("SELECT * FROM accounts WHERE key_hash = ?", (_hash_key(key),)).fetchone()


def normalize_ref(ref: str) -> str | None:
    ref = ref.lower().removeprefix("0x")
    return ref if _ACCOUNT_RE.match(ref) else None


def credit(conn, account_id: str, amount_micro: int) -> bool:
    cur = conn.execute(
        "UPDATE accounts SET balance_micro = balance_micro + ? WHERE id = ?", (amount_micro, account_id)
    )
    return cur.rowcount == 1


def charge(conn, account_id: str, amount_micro: int, tokens: int) -> int:
    """Débite au plus le solde disponible. Retourne le montant réellement débité."""
    row = conn.execute("SELECT balance_micro FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        return 0
    debit = min(int(row["balance_micro"]), amount_micro)
    conn.execute(
        "UPDATE accounts SET balance_micro = balance_micro - ?, spent_micro = spent_micro + ?,"
        " tokens_used = tokens_used + ? WHERE id = ?",
        (debit, debit, tokens, account_id),
    )
    return debit


# ---------------------------------------------------------------- réservations & débit


def reserve(account_id: str, balance_micro: int, amount_micro: int) -> bool:
    """Réserve le coût maximal d'une requête : deux requêtes simultanées ne
    peuvent pas dépenser deux fois le même crédit."""
    with _lock:
        if balance_micro - _reserved[account_id] < amount_micro:
            return False
        _reserved[account_id] += amount_micro
        return True


def release(account_id: str, amount_micro: int) -> None:
    with _lock:
        _reserved[account_id] = max(0, _reserved[account_id] - amount_micro)


def allow_request(account_id: str) -> bool:
    """Plafond de requêtes par minute et par compte (fenêtre glissante)."""
    now = time.time()
    with _lock:
        window = _recent[account_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.REQUESTS_PER_MINUTE:
            return False
        window.append(now)
        return True
