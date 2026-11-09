#!/usr/bin/env python3
"""Test de bout en bout de la pile AQL complète, en conditions réelles locales.

Lance une vraie chaîne (ganache), déploie les contrats, démarre le coordinateur
et de vrais processus mineurs, puis vérifie tout le cycle :

   1. un utilisateur crée un compte et paie en USDT on-chain -> crédit automatique ;
   2. un mineur TRICHEUR sert des réponses fausses -> contrôle, arbitrage,
      sanction, exclusion ;
   3. les mineurs honnêtes servent l'IA ; le compte est débité au prix du moment ;
   4. l'IA s'améliore toute seule : prompt candidat mesuré au benchmark, promu ;
   5. benchmark public : le réseau répond aux tâches générées ;
   6. fin d'époque : deux oracles votent (AQL + USDT du pool mineurs) ;
   7. un mineur honnête réclame ses gains (claimMany) : AQL + USDT reçus.

Les « modèles » des mineurs sont des serveurs de test compatibles OpenAI :
l'honnête résout les tâches quand son prompt système contient « AMÉLIORÉ »,
le tricheur renvoie du texte aléatoire.

Prérequis : cd contracts && npm install && npm run compile ;
            pip install -r network/coordinator/requirements.txt
Lancer    : python3 network/tests/e2e_stack.py      (≈ 5 minutes)
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
import tasks  # noqa: E402  (générateur partagé : jours, normalisation)

RPC_PORT, COORD_PORT, HONEST_PORT, LIAR_PORT = 8555, 9400, 18001, 18002
RPC = f"http://127.0.0.1:{RPC_PORT}"
COORDINATOR = f"http://127.0.0.1:{COORD_PORT}"
ADMIN = "e2e-admin-token"
MODEL = "stub-model"
EPOCH0_SECONDS_LEFT = 240

# Comptes déterministes de ganache.
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
    print(f"ÉCHEC  {msg}\n(journaux : {WORK})", flush=True)
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
        fail(f"chain_helper {args[0]} : {out.stderr.strip()}")
    return out.stdout.strip()


def wait_until(predicate, timeout: float, what: str, step: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    fail(f"délai dépassé : {what}")


# ---------------------------------------------------------------- modèles de test


def solve(question: str) -> str | None:
    q = question.strip()
    m = re.search(r"Calcule \((\d+) × (\d+)\) \+ (\d+) − (\d+)\.", q)
    if m:
        a, b, c, d = map(int, m.groups())
        return str(a * b + c - d)
    m = re.search(r"Combien font (\d+) % de (\d+) \?", q)
    if m:
        p, base = map(int, m.groups())
        return str(base * p // 100)
    m = re.search(r"de (\d+) km/h pendant (\d+) h(?: (\d+) min)?\.", q)
    if m:
        v, h, mins = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return str(v * h + v * mins // 60)
    m = re.search(r"minutes dans ([\d,]+) heures", q)
    if m:
        return str(int(float(m.group(1).replace(",", ".")) * 60))
    m = re.search(r"la suite : ([\d, ]+), \?", q)
    if m:
        n = [int(x) for x in m.group(1).split(",")]
        return str(n[-1] * (n[-1] // n[-2]))
    m = re.search(r"ordre croissant : ([\d, ]+)\.", q)
    if m:
        return ", ".join(map(str, sorted(int(x) for x in m.group(1).split(","))))
    m = re.search(r"aujourd'hui est (\w+), quel jour de la semaine serons-nous dans (\d+) jours", q)
    if m:
        return tasks.DAYS[(tasks.DAYS.index(m.group(1)) + int(m.group(2))) % 7]
    m = re.search(r"la lettre « (.) » apparaît-elle dans le mot « (\w+) »", q)
    if m:
        return str(tasks._strip_accents(m.group(2)).count(m.group(1)))
    m = re.search(r"Résous : (\d+)x \+ (\d+) = (\d+)\.", q)
    if m:
        a, b, c = map(int, m.groups())
        return str((c - b) // a)
    return None


def honest_answer(messages: list[dict]) -> str:
    system = " ".join(m["content"] for m in messages if m["role"] == "system")
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if "Tu améliores le prompt système" in system:
        return ("Prompt système AMÉLIORÉ : lis chaque question attentivement, calcule étape par étape, "
                "vérifie ton résultat, puis termine par la ligne RÉPONSE: <réponse>.")
    if "RÉPONSE: <réponse finale>" in user:
        if "AMÉLIORÉ" in system:
            return f"Je raisonne étape par étape.\nRÉPONSE: {solve(user.split(chr(10))[0]) or '?'}"
        return "RÉPONSE: 0"
    return f"Réponse du modèle AQL (test) à : {user[:200]}"


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


# ---------------------------------------------------------------- scénario


def main() -> None:
    log(f"répertoire de travail : {WORK}")

    # --- chaîne + contrats
    spawn("ganache", [str(CONTRACTS / "node_modules" / ".bin" / "ganache"), "--deterministic",
                      "--server.port", str(RPC_PORT), "--logging.quiet"])
    wait_until(lambda: _rpc_alive(), 30, "démarrage de ganache")
    genesis = int(time.time()) - 86_400 + EPOCH0_SECONDS_LEFT
    out = subprocess.run(
        ["node", "scripts/deploy.js"], cwd=CONTRACTS, capture_output=True, text=True, timeout=120,
        env={**os.environ, "RPC_URL": RPC, "DEPLOYER_PRIVATE_KEY": KEYS[0], "ORACLES": ",".join(ORACLES),
             "ORACLE_THRESHOLD": "2", "GENESIS_TS": str(genesis)},
    )
    if out.returncode != 0:
        fail(f"déploiement : {out.stderr}")
    dep_file = CONTRACTS / "deployments.1337.json"
    deployed = json.loads(dep_file.read_text())
    (WORK / "deployments.json").write_text(dep_file.read_text())
    dep_file.unlink()
    dep = str(WORK / "deployments.json")
    ok(f"contrats déployés (genèse : fin d'époque 0 dans {EPOCH0_SECONDS_LEFT} s)")

    # --- coordinateur + modèles de test
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
    wait_until(lambda: _http_alive(f"{COORDINATOR}/"), 30, "démarrage du coordinateur")
    ok("coordinateur démarré, modèle du réseau : " + http("GET", f"{COORDINATOR}/v1/models")["data"][0]["id"])

    # --- 1. compte + paiement on-chain -> crédit automatique
    account = http("POST", f"{COORDINATOR}/api/accounts")
    key = account["api_key"]
    node_helper("pay", dep, KEYS[0], "50", account["account_ref"])
    me = wait_until(
        lambda: (lambda m: m if m["balance_usdt"] > 0 else None)(
            http("GET", f"{COORDINATOR}/api/accounts/me", headers={"Authorization": f"Bearer {key}"})),
        30, "crédit du compte après paiement",
    )
    if me["balance_usdt"] != 50:
        fail(f"crédit attendu 50 USDT, obtenu {me['balance_usdt']}")
    ok("paiement de 50 USDT on-chain -> compte crédité automatiquement (aucune intervention)")

    # --- 2. un tricheur seul sert deux requêtes, puis les honnêtes le démasquent
    start_miner("liar", LIAR, LIAR_PORT)
    for i in range(2):
        chat(key, f"Question {i} servie par le tricheur")
    for i, wallet in enumerate(HONEST):
        start_miner(f"honest{i}", wallet, HONEST_PORT)
    wait_until(lambda: reputation(LIAR) < 5, 90, "sanction du tricheur")
    ok(f"tricheur démasqué par contrôle + arbitrage : réputation {reputation(LIAR)} (< 5, exclu du service)")

    # --- 3. service honnête facturé
    before = http("GET", f"{COORDINATOR}/api/accounts/me", headers={"Authorization": f"Bearer {key}"})
    answers = [chat(key, f"Bonjour, question numéro {i}") for i in range(8)]
    if not all("Réponse du modèle AQL" in a["choices"][0]["message"]["content"] for a in answers):
        fail("une réponse ne vient pas d'un mineur honnête")
    after = http("GET", f"{COORDINATOR}/api/accounts/me", headers={"Authorization": f"Bearer {key}"})
    cost = before["balance_usdt"] - after["balance_usdt"]
    if not cost > 0:
        fail("le compte n'a pas été débité")
    ok(f"8 requêtes servies par les mineurs honnêtes, compte débité de {cost:.6f} USDT au prix automatique")

    # --- 4. auto-amélioration prouvée au benchmark
    evo = wait_until(
        lambda: (lambda e: e if e["active_prompt"]["id"] else None)(http("GET", f"{COORDINATOR}/api/evolution")),
        120, "promotion d'un prompt amélioré",
    )
    promoted = next(c for c in evo["candidates"] if c["status"] == "promoted")
    gains = ", ".join(f"{m['baseline']}→{m['candidate']}/{m['total']}" for m in promoted["measurements"])
    ok(f"IA améliorée automatiquement : prompt promu après mesures ({gains})")

    # --- 5. benchmark public
    http("POST", f"{COORDINATOR}/api/admin/benchmark/run", headers={"X-Admin-Token": ADMIN})
    run = wait_until(
        lambda: next((r for r in http("GET", f"{COORDINATOR}/api/benchmark")["history"]
                      if r["target"] == "network"), None),
        120, "résultat du benchmark",
    )
    if run["correct"] is None or run["correct"] < run["total"] * 0.8:
        fail(f"benchmark réseau trop bas : {run}")
    ok(f"benchmark public : le réseau réussit {run['correct']}/{run['total']} tâches générées")
    pricing = http("GET", f"{COORDINATOR}/api/pricing")
    ok(f"prix automatique : {pricing['price_usdt_per_million_tokens']} USDT / million de tokens")

    # --- 6. fin d'époque : vote des oracles (AQL + USDT)
    log(f"attente de la fin de l'époque 0 (genèse + 1 jour)…")
    wait_until(lambda: time.time() > genesis + 86_400 + 2, EPOCH0_SECONDS_LEFT + 30, "fin de l'époque 0", step=2)
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
    if "FINALISÉE" not in (WORK / "oracle2.log").read_text():
        fail("époque 0 non finalisée par les oracles")
    usdt_total = int(settlement["usdt_total"])
    if not 0 < usdt_total <= pool_before:
        fail(f"USDT de l'époque incohérent : {usdt_total} (pool {pool_before})")
    ok(f"époque 0 finalisée à 2 oracles sur 3 : {int(settlement['aql_total']) / 1e18:,.2f} AQL "
       f"+ {usdt_total / 1e6:.6f} USDT (pool mineurs {pool_before / 1e6:.6f})")
    liar_claim = next((c for c in settlement["claims"] if c["account"] == LIAR.lower()), None)
    if liar_claim and int(liar_claim["usdt"]) > 0:
        fail(f"le tricheur touche de l'USDT : {liar_claim}")
    ok("le tricheur ne touche aucun USDT des utilisateurs")

    # --- 7. réclamation par un mineur honnête
    wallet = HONEST[0]
    claim = next(c for c in settlement["claims"] if c["account"] == wallet.lower())
    node_helper("claim", dep, COORDINATOR, wallet, KEYS[0])
    bal = json.loads(node_helper("balances", dep, wallet))
    if int(bal["aql_wei"]) != int(claim["aql"]) or int(bal["usdt"]) != int(claim["usdt"]):
        fail(f"soldes après claim incohérents : {bal} vs {claim}")
    ok(f"mineur honnête payé on-chain : {int(bal['aql_wei']) / 1e18:,.2f} AQL + {int(bal['usdt']) / 1e6:.6f} USDT")

    print("\nE2E PILE COMPLÈTE : paiement -> crédit -> service -> contrôle -> amélioration -> "
          "benchmark -> oracles -> claims, vérifiés.")


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
