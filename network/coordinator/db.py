"""Accès SQLite du coordinateur — stdlib uniquement, WAL, écritures sérialisées."""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

import settings

_write_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    wallet TEXT NOT NULL,
    node_type TEXT NOT NULL CHECK (node_type IN ('gpu', 'storage')),
    name TEXT NOT NULL DEFAULT '',
    has_model INTEGER NOT NULL DEFAULT 0,
    storage_allocated_bytes INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES nodes(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'assigned',
    result TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    epoch_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    completed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_jobs_epoch ON jobs(epoch_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_node ON jobs(node_id, status);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL,
    author_node TEXT NOT NULL,
    author_wallet TEXT NOT NULL,
    goal TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    votes INTEGER NOT NULL DEFAULT 0,
    score_sum REAL NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    decided_at INTEGER
);
CREATE TABLE IF NOT EXISTS votes (
    candidate_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    score REAL NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    PRIMARY KEY (candidate_id, node_id)
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    seq INTEGER NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    data BLOB NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_key ON chunks(key, seq);
CREATE TABLE IF NOT EXISTS assignments (
    chunk_id TEXT NOT NULL REFERENCES chunks(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    status TEXT NOT NULL DEFAULT 'pending',
    fails INTEGER NOT NULL DEFAULT 0,
    last_challenge_at INTEGER NOT NULL DEFAULT 0,
    stored_at INTEGER,
    PRIMARY KEY (chunk_id, node_id)
);
CREATE TABLE IF NOT EXISTS epochs (
    id INTEGER PRIMARY KEY,
    settled_at INTEGER NOT NULL,
    merkle_root TEXT NOT NULL,
    reward_wei TEXT NOT NULL,
    gpu_points INTEGER NOT NULL,
    storage_points INTEGER NOT NULL,
    settlement TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def read():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write():
    """Transaction d'écriture sérialisée (un seul écrivain à la fois)."""
    with _write_lock:
        conn = connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
    return row["v"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, value),
    )


def init() -> dict:
    """Crée le schéma et fige les valeurs de genèse.

    Retourne {genesis_ts, admin_token, admin_token_generated}.
    """
    os.makedirs(os.path.dirname(os.path.abspath(settings.DB_PATH)), exist_ok=True)
    os.makedirs(settings.SETTLEMENTS_DIR, exist_ok=True)
    with write() as conn:
        conn.executescript(_SCHEMA)

        genesis = get_meta(conn, "genesis_ts")
        if genesis is None:
            genesis = str(settings.GENESIS_TS or int(time.time()))
            set_meta(conn, "genesis_ts", genesis)

        admin_token = settings.ADMIN_TOKEN or get_meta(conn, "admin_token") or ""
        generated = False
        if not admin_token:
            admin_token = secrets.token_hex(24)
            generated = True
        set_meta(conn, "admin_token", admin_token)

    return {
        "genesis_ts": int(genesis),
        "admin_token": admin_token,
        "admin_token_generated": generated,
    }
