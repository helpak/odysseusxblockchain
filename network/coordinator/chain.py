"""Lecture des paiements on-chain : chaque AQLNetwork.pay() crédite un compte.

Client JSON-RPC minimal (stdlib) : eth_blockNumber + eth_getLogs sur l'événement
  Paid(address indexed payer, bytes32 indexed accountRef,
       uint256 received, uint256 minerCut, uint256 holderCut)
L'accountRef EST l'identifiant de compte (32 octets) : le crédit arrive tout
seul. Seuls les blocs ayant CHAIN_CONFIRMATIONS confirmations sont lus, et
chaque log n'est compté qu'une fois (clé : tx_hash + log_index).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import accounts
import db
import settings

# keccak256("Paid(address,bytes32,uint256,uint256,uint256)") — hashlib n'a pas
# keccak : valeur calculée avec ethers et vérifiée par le test d'intégration.
PAID_TOPIC = "0x960eb94ee51eb27e7e5e10d3a732bfe1df2676ad57ce834122d082f6ae103181"

_status = {"enabled": False, "last_block": None, "last_error": "", "last_run": None}


def status() -> dict:
    return dict(_status)


def _rpc(method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(settings.RPC_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(f"{method}: {out['error']}")
    return out["result"]


def decode_paid(log: dict) -> dict:
    topics = log["topics"]
    data = log["data"][2:]
    return {
        "tx_hash": log["transactionHash"],
        "log_index": int(log["logIndex"], 16),
        "block_number": int(log["blockNumber"], 16),
        "payer": "0x" + topics[1][-40:],
        "account_id": topics[2][2:].lower(),
        "received": int(data[0:64], 16),
    }


def ingest(logs: list[dict]) -> int:
    """Enregistre et crédite des logs Paid. Retourne le nombre de nouveaux paiements."""
    added = 0
    with db.write() as conn:
        for log in logs:
            p = decode_paid(log)
            cur = conn.execute(
                "INSERT OR IGNORE INTO payments (tx_hash, log_index, block_number, payer, account_id,"
                " received_micro, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (p["tx_hash"], p["log_index"], p["block_number"], p["payer"], p["account_id"],
                 p["received"], int(time.time())),
            )
            if cur.rowcount == 1:
                added += 1
                if accounts.credit(conn, p["account_id"], p["received"]):
                    conn.execute(
                        "UPDATE payments SET credited = 1 WHERE tx_hash = ? AND log_index = ?",
                        (p["tx_hash"], p["log_index"]),
                    )
    return added


def poll_once() -> int:
    latest = int(_rpc("eth_blockNumber", []), 16)
    safe = latest - settings.CHAIN_CONFIRMATIONS
    with db.read() as conn:
        stored = db.get_meta(conn, "chain_last_block")
    start = int(stored) + 1 if stored is not None else settings.CHAIN_START_BLOCK
    added = 0
    while start <= safe:
        end = min(safe, start + settings.CHAIN_LOG_CHUNK - 1)
        logs = _rpc(
            "eth_getLogs",
            [{
                "address": settings.AQL_NETWORK_ADDRESS,
                "topics": [PAID_TOPIC],
                "fromBlock": hex(start),
                "toBlock": hex(end),
            }],
        )
        added += ingest(logs)
        with db.write() as conn:
            db.set_meta(conn, "chain_last_block", str(end))
        _status["last_block"] = end
        start = end + 1
    return added


def start_background() -> None:
    if not (settings.RPC_URL and settings.AQL_NETWORK_ADDRESS):
        return
    _status["enabled"] = True

    def loop():
        while True:
            try:
                poll_once()
                _status["last_error"] = ""
            except Exception as exc:  # réseau, RPC : on réessaie au prochain tour
                _status["last_error"] = str(exc)[:300]
            _status["last_run"] = int(time.time())
            time.sleep(settings.CHAIN_POLL_SECONDS)

    threading.Thread(target=loop, daemon=True, name="chain-payments").start()
