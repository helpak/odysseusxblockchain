"""Comptabilité des époques : points -> wei, halving, règlement merkle.

Toute la comptabilité est en entiers (milli-points et wei). Le règlement d'une
époque produit exactement le fichier que `contracts/scripts/submit-epoch.js`
publie on-chain, plus les preuves merkle que chaque mineur utilisera pour
réclamer ses ODY.
"""

from __future__ import annotations

import json
import os
import time

import db
import merkle
import settings

_GENESIS_TS = 0  # figé par init_genesis() au démarrage


def init_genesis(genesis_ts: int) -> None:
    global _GENESIS_TS
    _GENESIS_TS = genesis_ts


def genesis_ts() -> int:
    return _GENESIS_TS


def current_epoch(now: int | None = None) -> int:
    now = int(time.time()) if now is None else now
    if now < _GENESIS_TS:
        return 0
    return (now - _GENESIS_TS) // settings.EPOCH_SECONDS


def epoch_bounds(epoch_id: int) -> tuple[int, int]:
    start = _GENESIS_TS + epoch_id * settings.EPOCH_SECONDS
    return start, start + settings.EPOCH_SECONDS


def epoch_reward_wei(epoch_id: int) -> int:
    """Miroir exact de RewardsDistributor.epochReward."""
    halvings = epoch_id // settings.HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return settings.INITIAL_EPOCH_REWARD_WEI >> halvings


def next_halving_epoch(epoch_id: int) -> int:
    return ((epoch_id // settings.HALVING_INTERVAL) + 1) * settings.HALVING_INTERVAL


GPU_KINDS = ("bench", "improve", "vote", "promotion_bonus")
STORAGE_KINDS = ("store", "challenge")


def _points_by_wallet(conn, epoch_id: int, kinds: tuple[str, ...]) -> dict[str, int]:
    placeholders = ",".join("?" for _ in kinds)
    rows = conn.execute(
        f"""
        SELECT n.wallet AS wallet, SUM(j.points) AS pts
        FROM jobs j JOIN nodes n ON n.id = j.node_id
        WHERE j.epoch_id = ? AND j.status = 'done' AND j.points > 0
          AND j.kind IN ({placeholders})
        GROUP BY n.wallet
        """,
        (epoch_id, *kinds),
    ).fetchall()
    return {row["wallet"]: int(row["pts"]) for row in rows}


def _allocate(pool_wei: int, points: dict[str, int]) -> dict[str, int]:
    """Répartit un pool au prorata des points, en arithmétique entière (plancher)."""
    total = sum(points.values())
    if total <= 0 or pool_wei <= 0:
        return {}
    return {
        wallet: (pool_wei * pts) // total
        for wallet, pts in points.items()
        if (pool_wei * pts) // total > 0
    }


def settle_epoch(epoch_id: int) -> dict:
    """Règle une époque terminée : agrège les points, répartit la récompense,
    construit l'arbre merkle et écrit settlements/epoch_<id>.json."""
    now = int(time.time())
    if epoch_id >= current_epoch(now):
        raise ValueError(
            f"l'époque {epoch_id} n'est pas terminée (époque courante: {current_epoch(now)})"
        )

    with db.read() as conn:
        if conn.execute("SELECT 1 FROM epochs WHERE id = ?", (epoch_id,)).fetchone():
            raise ValueError(f"époque {epoch_id} déjà réglée")
        gpu_points = _points_by_wallet(conn, epoch_id, GPU_KINDS)
        storage_points = _points_by_wallet(conn, epoch_id, STORAGE_KINDS)

    reward = epoch_reward_wei(epoch_id)
    if reward <= 0:
        raise ValueError(f"émission terminée : récompense nulle pour l'époque {epoch_id}")
    if not gpu_points and not storage_points:
        raise ValueError(f"aucune activité sur l'époque {epoch_id} : rien à régler")

    gpu_pool = (reward * settings.GPU_POOL_BPS) // 10_000
    storage_pool = reward - gpu_pool
    # Bootstrap : si un pool n'a aucune activité, sa part bascule sur l'autre,
    # pour que les premiers contributeurs (le fondateur inclus) soient payés.
    if not gpu_points:
        storage_pool += gpu_pool
        gpu_pool = 0
    if not storage_points:
        gpu_pool += storage_pool
        storage_pool = 0

    payouts: dict[str, int] = {}
    for wallet, amount in _allocate(gpu_pool, gpu_points).items():
        payouts[wallet] = payouts.get(wallet, 0) + amount
    for wallet, amount in _allocate(storage_pool, storage_points).items():
        payouts[wallet] = payouts.get(wallet, 0) + amount
    if not payouts:
        raise ValueError(f"aucun payout calculable pour l'époque {epoch_id}")

    tree = merkle.build_payout_tree(
        epoch_id, [{"account": w, "amount": a} for w, a in payouts.items()]
    )

    settlement = {
        "epoch_id": epoch_id,
        "settled_at": now,
        "merkle_root": tree["merkle_root"],
        "reward_wei": str(reward),
        "gpu_pool_wei": str(gpu_pool),
        "storage_pool_wei": str(storage_pool),
        "gpu_points": {w: p for w, p in gpu_points.items()},
        "storage_points": {w: p for w, p in storage_points.items()},
        "total_payout_wei": tree["total_amount"],
        "claims": tree["claims"],
    }

    with db.write() as conn:
        if conn.execute("SELECT 1 FROM epochs WHERE id = ?", (epoch_id,)).fetchone():
            raise ValueError(f"époque {epoch_id} déjà réglée")
        conn.execute(
            "INSERT INTO epochs (id, settled_at, merkle_root, reward_wei, gpu_points,"
            " storage_points, settlement) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                epoch_id,
                now,
                tree["merkle_root"],
                str(reward),
                sum(gpu_points.values()),
                sum(storage_points.values()),
                json.dumps(settlement),
            ),
        )

    path = os.path.join(settings.SETTLEMENTS_DIR, f"epoch_{epoch_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(settlement, fh, indent=2)

    return settlement


def wallet_rewards(wallet: str) -> dict:
    """Points en cours + claims réglés (avec preuves merkle) pour un wallet."""
    wallet = merkle.normalize_address(wallet)
    epoch = current_epoch()
    out: dict = {"wallet": wallet, "current_epoch": epoch, "pending_points": {}, "claims": []}

    with db.read() as conn:
        for label, kinds in (("gpu", GPU_KINDS), ("storage", STORAGE_KINDS)):
            placeholders = ",".join("?" for _ in kinds)
            row = conn.execute(
                f"""
                SELECT COALESCE(SUM(j.points), 0) AS pts
                FROM jobs j JOIN nodes n ON n.id = j.node_id
                WHERE n.wallet = ? AND j.epoch_id = ? AND j.status = 'done'
                  AND j.kind IN ({placeholders})
                """,
                (wallet, epoch, *kinds),
            ).fetchone()
            out["pending_points"][label] = int(row["pts"])

        for row in conn.execute("SELECT settlement FROM epochs ORDER BY id"):
            settlement = json.loads(row["settlement"])
            for claim in settlement["claims"]:
                if claim["account"] == wallet:
                    out["claims"].append(
                        {
                            "epoch_id": settlement["epoch_id"],
                            "merkle_root": settlement["merkle_root"],
                            "index": claim["index"],
                            "amount_wei": claim["amount"],
                            "proof": claim["proof"],
                            "note": "statut réclamé/non réclamé visible on-chain (RewardsDistributor.isClaimed)",
                        }
                    )
    return out
