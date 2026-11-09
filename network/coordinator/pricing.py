"""Prix automatique de l'IA, sans intervention humaine.

Principe des frais de base d'Ethereum : à chaque nouvelle époque, le prix par
million de tokens est ajusté selon la charge de l'époque précédente.

    charge = requêtes attribuées / (requêtes attribuées + passages à vide)
    nouveau prix = ancien × (1 + PAS_MAX × (charge − CIBLE) / CIBLE)

Un « passage à vide » est une interrogation d'un mineur prêt à servir alors
que la file était vide : de la capacité non utilisée. Réseau saturé : le prix
monte (+12,5 % au plus par époque). Réseau sous-utilisé : il baisse. Aucune
activité : il ne bouge pas. Le prix reste entre PRICE_MIN et PRICE_MAX.
"""

from __future__ import annotations

import settings


def _stats(conn, epoch_id: int) -> tuple[int, int]:
    row = conn.execute(
        "SELECT serve_assigned, idle_polls FROM epoch_stats WHERE epoch_id = ?", (epoch_id,)
    ).fetchone()
    return (int(row["serve_assigned"]), int(row["idle_polls"])) if row else (0, 0)


def utilization_bps(conn, epoch_id: int) -> int | None:
    assigned, idle = _stats(conn, epoch_id)
    if assigned + idle == 0:
        return None
    return (assigned * 10_000) // (assigned + idle)


def next_price(previous_micro: int, util_bps: int | None) -> int:
    if util_bps is None:
        return previous_micro
    target = settings.PRICE_TARGET_UTILIZATION
    u = util_bps / 10_000
    factor = 1 + settings.PRICE_MAX_STEP * (u - target) / target
    factor = max(1 - settings.PRICE_MAX_STEP, min(1 + settings.PRICE_MAX_STEP, factor))
    price = int(previous_micro * factor)
    return max(settings.PRICE_MIN_MICRO, min(settings.PRICE_MAX_MICRO, price))


def price_for_epoch(conn, epoch_id: int) -> int:
    """Prix de l'époque, calculé et mémorisé de proche en proche (à appeler
    dans une transaction d'écriture)."""
    row = conn.execute(
        "SELECT epoch_id, price_micro FROM prices WHERE epoch_id <= ? ORDER BY epoch_id DESC LIMIT 1",
        (epoch_id,),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO prices (epoch_id, price_micro, utilization_bps) VALUES (?, ?, ?)",
            (epoch_id, settings.PRICE_START_MICRO, -1),
        )
        return settings.PRICE_START_MICRO
    last_epoch, price = int(row["epoch_id"]), int(row["price_micro"])
    for e in range(last_epoch + 1, epoch_id + 1):
        util = utilization_bps(conn, e - 1)
        price = next_price(price, util)
        conn.execute(
            "INSERT OR IGNORE INTO prices (epoch_id, price_micro, utilization_bps) VALUES (?, ?, ?)",
            (e, price, util if util is not None else -1),
        )
    return price


def cost_micro(tokens: int, price_micro_per_million: int) -> int:
    """Coût arrondi au micro-USDT supérieur : jamais de requête gratuite."""
    return (tokens * price_micro_per_million + 999_999) // 1_000_000


def history(conn, limit: int = 60) -> list[dict]:
    rows = conn.execute(
        "SELECT epoch_id, price_micro, utilization_bps FROM prices ORDER BY epoch_id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        {
            "epoch_id": r["epoch_id"],
            "price_usdt_per_million": r["price_micro"] / 1_000_000,
            "utilization_pct": None if r["utilization_bps"] < 0 else r["utilization_bps"] / 100,
        }
        for r in reversed(rows)
    ]


def record(conn, epoch_id: int, *, assigned: int = 0, idle: int = 0, tokens: int = 0) -> None:
    conn.execute(
        "INSERT INTO epoch_stats (epoch_id, serve_assigned, idle_polls, tokens_served) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(epoch_id) DO UPDATE SET serve_assigned = serve_assigned + excluded.serve_assigned,"
        " idle_polls = idle_polls + excluded.idle_polls, tokens_served = tokens_served + excluded.tokens_served",
        (epoch_id, assigned, idle, tokens),
    )
