#!/usr/bin/env python3
"""End-to-end test of the complete AQL stack, under real local conditions.

Starts a real chain (ganache), deploys the contracts, starts the coordinator
and real miner processes, then checks the whole cycle:

   1. a user creates an account and pays USDT on-chain -> automatic credit;
   2. a CHEATING miner serves wrong answers -> check, arbitration,
      penalty, exclusion;
   3. honest miners serve the AI; the account is charged at the current price;
   4. the AI improves itself: candidate prompt measured on the benchmark, promoted;
   5. public benchmark: the network answers the generated tasks;
   6. end of epoch: two oracles vote (AQL + USDT from the miner pool);
   7. an honest miner claims its earnings (claimMany): AQL + USDT received.

The miners' "models" are OpenAI-compatible test servers: the honest one solves
the tasks when its system prompt contains "IMPROVED", the cheater returns
random text.

Requirements: cd contracts && npm install && npm run compile;
              pip install -r network/coordinator/requirements.txt
Run:          python3 network/tests/e2e_stack.py      (≈ 5 minutes)
"""

from __future__ import annotations

import atexit
import json
import os
import random
import re
import signal
import sqlite3
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
COORD = ROOT / "network" / "coordinator"
MINER = ROOT / "network" / "miner" / "aql_miner.py"
HELPER = ROOT / "network" / "tests" / "chain_helper.js"
sys.path.insert(0, str(COORD))
import tasks  # noqa: E402  (shared generator: days, normalisation)

RPC_PORT, COORD_PORT, HONEST_PORT, LIAR_PORT = 8555, 9400, 18001, 18002
RPC = f"http://127.0.0.1:{RPC_PORT}"
COORDINATOR = f"http://127.0.0.1:{COORD_PORT}"
ADMIN = "e2e-admin-token"
MODEL = "stub-model"
EPOCH0_SECONDS_LEFT = 240

# Ganache deterministic accounts.
KEYS = [
    "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d",
    "0x6cbed15c793ce57650b9877cf6fa156fbef513c4e6134f022a85b1ffdd59b2a1",
    "0x6370fd033278c143179d81c5526140625662b8daa446c22ee2d73db3707e620c",
    "0x646f1ce2fdad0e6deeeb5c7e8e5543bdde65e86029e2fd9fc169899c440a7913",
]
ORACLES = [
    "0xFFcf8FDEE72ac11b5c542428B35EEF5769C409f0",
    "0x22d491Bde2303f2f43325b2108D26f1eAbA1e32b",
    "0xE11BA2b4D45Eaed5996Cd0823791E0C93114882d",
]
HONEST = ["0x" + c * 40 for c in "abc"]
LIAR = "0x" + "d" * 40

WORK = Path(tempfile.mkdtemp(prefix="aql-e2e-"))
PROCS: list[subprocess.Popen] = []


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"OK  {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"FAIL  {msg}\n(logs: {WORK})", flush=True)
    sys.exit(1)


def cleanup() -> None:
    for p in PROCS:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
    for p in PROCS:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


atexit.register(cleanup)


def spawn(name: str, cmd: list[str], env: dict | None = None, cwd: Path | None = None) -> subprocess.Popen:
    out = open(WORK / f"{name}.log", "w")
    p = subprocess.Popen(cmd, cwd=cwd, env={**os.environ, **(env or {})}, stdout=out, stderr=subprocess.STDOUT)
    PROCS.append(p)
    return p


def http(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: int = 240):
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def node_helper(*args: str) -> str:
    out = subprocess.run(["node", str(HELPER), *args], env={**os.environ, "RPC_URL": RPC},
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        fail(f"chain_helper {args[0]}: {out.stderr.strip()}")
    return out.stdout.strip()


def wait_until(predicate, timeout: float, what: str, step: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    fail(f"timed out: {what}")


# ---------------------------------------------------------------- test models


def solve(question: str) -> str | None:
    q = question.strip()
    m = re.search(r"Compute \((\d+) × (\d+)\) \+ (\d+) − (\d+)\.", q)
    if m:
        a, b, c, d = map(int, m.groups())
        return str(a * b + c - d)
    m = re.search(r"What is (\d+)% of (\d+)\?", q)
    if m:
        p, base = map(int, m.groups())
        return str(base * p // 100)
    m = re.search(r"constant (\d+) km/h for (\d+) h(?: (\d+) min)?\.", q)
    if m:
        v, h, mins = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return str(v * h + v * mins // 60)
    m = re.search(r"minutes are there in ([\d.]+) hours", q)
    if m:
        return str(int(float(m.group(1)) * 60))
    m = re.search(r"the sequence: ([\d, ]+), \?", q)
    if m:
        n = [int(x) for x in m.group(1).split(",")]
        return str(n[-1] * (n[-1] // n[-2]))
    m = re.search(r"ascending order: ([\d, ]+)\.", q)
    if m:
        return ", ".join(map(str, sorted(int(x) for x in m.group(1).split(","))))
    m = re.search(r"If today is (\w+), what day of the week will it be in (\d+) days", q)
    if m:
        return tasks.DAYS[(tasks.DAYS.index(m.group(1)) + int(m.group(2))) % 7]
    m = re.search(r'the letter "(.)" appear in the word "(\w+)"', q)
    if m:
        return str(m.group(2).count(m.group(1)))
    m = re.search(r"Solve: (\d+)x \+ (\d+) = (\d+)\.", q)
    if m:
        a, b, c = map(int, m.groups())
        return str((c - b) // a)
    return None


def honest_answer(messages: list[dict]) -> str:
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if "You are improving the system prompt" in system:
        return ("IMPROVED system prompt: read each question carefully, compute step by step, "
                "check your result, then end with the line ANSWER: <answer>.")
    if "ANSWER: <final answer>" in user:
        if "IMPROVED" in system:
            return f"I reason step by step.\nANSWER: {solve(user.split(chr(10))[0]) or '?'}"
        return "ANSWER: 0"
    return f"AQL model answer (test) to: {user[:200]}"


def liar_answer(_messages: list[dict]) -> str:
    return "".join(random.choice(string.ascii_letters + " ") for _ in range(300))


def stub_server(port: int, answer) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"message": {"role": "assistant", "content": answer(body["messages"])}}]})
            data = out.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def start_miner(name: str, wallet: str, port: int) -> None:
    spawn(name, [sys.executable, str(MINER), "--wallet", wallet, "--mode", "gpu",
                 "--coordinator", COORDINATOR, "--model-endpoint", f"http://127.0.0.1:{port}/v1",
                 "--name", name, "--state-file", str(WORK / f"{name}.json")])


def reputation(wallet: str) -> int:
    conn = sqlite3.connect(WORK / "coordinator.db")
    row = conn.execute("SELECT reputation FROM nodes WHERE wallet = ?", (wallet,)).fetchone()
    conn.close()
    return row[0] if row else -1


def chat(api_key: str, text: str) -> dict:
    return http("POST", f"{COORDINATOR}/v1/chat/completions",
                {"messages": [{"role": "user", "content": text}], "max_tokens": 200},
                {"Authorization": f"Bearer {api_key}"})


# ---------------------------------------------------------------- scenario


def main() -> None:
    log(f"working directory: {WORK}")

    # --- chain + contracts
    spawn("ganache", [str(CONTRACTS / "node_modules" / ".bin" / "ganache"), "--deterministic",
                      "--server.port", str(RPC_PORT), "--logging.quiet"])
    wait_until(lambda: _rpc_alive(), 30, "ganache start")
    genesis = int(time.time()) - 86_400 + EPOCH0_SECONDS_LEFT
    out = subprocess.run(
        ["node", "scripts/deploy.js"], cwd=CONTRACTS, capture_output=True, text=True, timeout=120,
        env={**os.environ, "RPC_URL": RPC, "DEPLOYER_PRIVATE_KEY": KEYS[0], "ORACLES": ",".join(ORACLES),
             "ORACLE_THRESHOLD": "2", "GENESIS_TS": str(genesis)},
    )
    if out.returncode != 0:
        fail(f"deployment: {out.stderr}")
    dep_file = CONTRACTS / "deployments.1337.json"
    deployed = json.loads(dep_file.read_text())
    (WORK / "deployments.json").write_text(dep_file.read_text())
    dep_file.unlink()
    dep = str(WORK / "deployments.json")
    ok(f"contracts deployed (genesis: epoch 0 ends in {EPOCH0_SECONDS_LEFT} s)")

    # --- coordinator + test models
    stub_server(HONEST_PORT, honest_answer)
    stub_server(LIAR_PORT, liar_answer)
    spawn("coordinator", [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                          "--port", str(COORD_PORT)], cwd=COORD, env={
        "COORDINATOR_DB": str(WORK / "coordinator.db"), "SETTLEMENTS_DIR": str(WORK / "settlements"),
        "COORDINATOR_ADMIN_TOKEN": ADMIN, "GENESIS_TS": str(genesis), "NETWORK_MODEL": MODEL,
        "RPC_URL": RPC, "AQL_NETWORK_ADDRESS": deployed["contracts"]["AQLNetwork"],
        "CHAIN_POLL_SECONDS": "1", "CHAIN_CONFIRMATIONS": "0", "VERIFY_SAMPLE_RATE": "1.0",
        "LONG_POLL_SECONDS": "2", "BENCH_INTERVAL_SECONDS": "0",
    })
    wait_until(lambda: _http_alive(f"{COORDINATOR}/"), 30, "coordinator start")
    ok("coordinator started, network model: " + http("GET", f"{COORDINATOR}/v1/models")["data"][0]["id"])

    # --- 1. account + on-chain payment -> automatic credit
    account = http("POST", f"{COORDINATOR}/api/accounts")
    key = account["api_key"]
    node_helper("pay", dep, KEYS[0], "50", account["account_ref"])
    me = wait_until(
        lambda: (lambda m: m if m["balance_usdt"] > 0 else None)(
            http("GET", f"{COORDINATOR}/api/accounts/me", headers={"Authorization": f"Bearer {key}"})),
        30, "account credit after payment",
    )
    if me["balance_usdt"] != 50:
        fail(f"expected 50 USDT credit, got {me['balance_usdt']}")
    ok("50 USDT paid on-chain -> account credited automatically (no intervention)")

    # --- 2. a cheater alone serves two requests, then the honest miners expose it
    start_miner("liar", LIAR, LIAR_PORT)
    for i in range(2):
        chat(key, f"Question {i} served by the cheater")
    for i, wallet in enumerate(HONEST):
        start_miner(f"honest{i}", wallet, HONEST_PORT)
    wait_until(lambda: reputation(LIAR) < 5, 90, "cheater penalty")
    ok(f"cheater exposed by check + arbitration: reputation {reputation(LIAR)} (< 5, excluded from serving)")

    # --- 3. honest serving, charged
    before = http("GET", f"{COORDINATOR}/api/accounts/me", headers={"Authorization": f"Bearer {key}"})
    answers = [chat(key, f"Hello, question number {i}") for i in range(8)]
    if not all("AQL model answer" in a["choices"][0]["message"]["content"] for a in answers):
        fail("an answer did not come from an honest miner")
    after = http("GET", f"{COORDINATOR}/api/accounts/me", headers={"Authorization": f"Bearer {key}"})
    cost = before["balance_usdt"] - after["balance_usdt"]
    if not cost > 0:
        fail("the account was not charged")
    ok(f"8 requests served by honest miners, account charged {cost:.6f} USDT at the automatic price")

    # --- 4. self-improvement proven on the benchmark
    evo = wait_until(
        lambda: (lambda e: e if e["active_prompt"]["id"] else None)(http("GET", f"{COORDINATOR}/api/evolution")),
        120, "promotion of an improved prompt",
    )
    promoted = next(c for c in evo["candidates"] if c["status"] == "promoted")
    gains = ", ".join(f"{m['baseline']}→{m['candidate']}/{m['total']}" for m in promoted["measurements"])
    ok(f"AI improved automatically: prompt promoted after measurements ({gains})")

    # --- 5. public benchmark
    http("POST", f"{COORDINATOR}/api/admin/benchmark/run", headers={"X-Admin-Token": ADMIN})
    run = wait_until(
        lambda: next((r for r in http("GET", f"{COORDINATOR}/api/benchmark")["history"]
                      if r["target"] == "network"), None),
        120, "benchmark result",
    )
    if run["correct"] is None or run["correct"] < run["total"] * 0.8:
        fail(f"network benchmark too low: {run}")
    ok(f"public benchmark: the network passes {run['correct']}/{run['total']} generated tasks")
    pricing = http("GET", f"{COORDINATOR}/api/pricing")
    ok(f"automatic price: {pricing['price_usdt_per_million_tokens']} USDT / million tokens")

    # --- 6. end of epoch: oracle vote (AQL + USDT)
    log("waiting for the end of epoch 0 (genesis + 1 day)…")
    wait_until(lambda: time.time() > genesis + 86_400 + 2, EPOCH0_SECONDS_LEFT + 30, "end of epoch 0", step=2)
    node_helper("mine")
    pool_before = int(node_helper("minerpool", dep))
    for i in (1, 2):
        out = subprocess.run(
            ["node", "scripts/oracle-daemon.js", "--once"], cwd=CONTRACTS, capture_output=True, text=True,
            timeout=120, env={**os.environ, "COORDINATOR_URL": COORDINATOR, "COORDINATOR_ADMIN_TOKEN": ADMIN,
                              "RPC_URL": RPC, "ORACLE_PRIVATE_KEY": KEYS[i],
                              "AQL_NETWORK_ADDRESS": deployed["contracts"]["AQLNetwork"],
                              "ORACLE_STATE_FILE": str(WORK / f"oracle{i}.json")},
        )
        (WORK / f"oracle{i}.log").write_text(out.stdout + out.stderr)
    settlement = http("GET", f"{COORDINATOR}/api/epochs/0/settlement")
    if "FINALIZED" not in (WORK / "oracle2.log").read_text():
        fail("epoch 0 not finalized by the oracles")
    usdt_total = int(settlement["usdt_total"])
    if not 0 < usdt_total <= pool_before:
        fail(f"inconsistent epoch USDT: {usdt_total} (pool {pool_before})")
    ok(f"epoch 0 finalized by 2 of 3 oracles: {int(settlement['aql_total']) / 1e18:,.2f} AQL "
       f"+ {usdt_total / 1e6:.6f} USDT (miner pool {pool_before / 1e6:.6f})")
    liar_claim = next((c for c in settlement["claims"] if c["account"] == LIAR.lower()), None)
    if liar_claim and int(liar_claim["usdt"]) > 0:
        fail(f"the cheater receives USDT: {liar_claim}")
    ok("the cheater receives none of the users' USDT")

    # --- 7. claim by an honest miner
    wallet = HONEST[0]
    claim = next(c for c in settlement["claims"] if c["account"] == wallet.lower())
    node_helper("claim", dep, COORDINATOR, wallet, KEYS[0])
    bal = json.loads(node_helper("balances", dep, wallet))
    if int(bal["aql_wei"]) != int(claim["aql"]) or int(bal["usdt"]) != int(claim["usdt"]):
        fail(f"inconsistent balances after claim: {bal} vs {claim}")
    ok(f"honest miner paid on-chain: {int(bal['aql_wei']) / 1e18:,.2f} AQL + {int(bal['usdt']) / 1e6:.6f} USDT")

    print("\nFULL-STACK E2E: payment -> credit -> serving -> check -> improvement -> "
          "benchmark -> oracles -> claims, verified.")


def _rpc_alive() -> bool:
    try:
        http("POST", RPC, {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, timeout=3)
        return True
    except Exception:
        return False


def _http_alive(url: str) -> bool:
    try:
        http("GET", url, timeout=3)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
