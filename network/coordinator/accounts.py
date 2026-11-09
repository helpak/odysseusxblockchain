"""AI user accounts: access key, USDT credit, rate limit.

- The account ID (32 bytes) also serves as the payment reference:
  the user calls AQLNetwork.pay(amount, 0x<account_id>) and the credit
  lands on their account automatically (by reading Paid events, see chain.py).
- The access key is only stored hashed (sha256): a database leak does not
  allow anyone to spend users' credit.
- Amounts in micro-USDT (1 USDT = 1,000,000), matching USDT's 6 decimals.
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
    """Debits at most the available balance. Returns the amount actually debited."""
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


# ---------------------------------------------------------------- reservations & debit


def reserve(account_id: str, balance_micro: int, amount_micro: int) -> bool:
    """Reserves the maximum cost of a request: two concurrent requests
    cannot spend the same credit twice."""
    with _lock:
        if balance_micro - _reserved[account_id] < amount_micro:
            return False
        _reserved[account_id] += amount_micro
        return True


def release(account_id: str, amount_micro: int) -> None:
    with _lock:
        _reserved[account_id] = max(0, _reserved[account_id] - amount_micro)


def allow_request(account_id: str) -> bool:
    """Cap on requests per minute, per account (sliding window)."""
    now = time.time()
    with _lock:
        window = _recent[account_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.REQUESTS_PER_MINUTE:
            return False
        window.append(now)
        return True
