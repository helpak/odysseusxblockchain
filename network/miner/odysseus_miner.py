#!/usr/bin/env python3
"""Mineur Odysseus Network — un seul fichier, zéro dépendance (Python 3.10+).

Donnez votre wallet, choisissez ce que vous fournissez, et les récompenses ODY
s'accumulent sur votre adresse à chaque époque.

  Minage GPU/calcul :
      python3 odysseus_miner.py --wallet 0xVOTRE_WALLET --mode gpu
    Avec un modèle local (Ollama, vLLM, llama.cpp — endpoint OpenAI-compatible),
    votre nœud devient AMÉLIORATEUR + VOTEUR (jobs les mieux payés) :
      python3 odysseus_miner.py --wallet 0x… --mode gpu \
          --model-endpoint http://localhost:11434/v1 --model llama3.1

  Minage stockage (héberge la mémoire chiffrée de l'IA, payé en continu) :
      python3 odysseus_miner.py --wallet 0xVOTRE_WALLET --mode storage \
          --allocate-gb 100 --storage-path ./odysseus_storage

Options : --coordinator URL, --name, --max-jobs N (0 = infini), --state-file.
L'identité du nœud est persistée : relancer le mineur reprend le même nœud.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

DEFAULT_COORDINATOR = "http://127.0.0.1:9000"
WALLET_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------- API


class CoordinatorApi:
    def __init__(self, base_url: str, state_path: str):
        self.base_url = base_url.rstrip("/")
        self.state_path = state_path
        self.node_id: str | None = None
        self.node_token: str | None = None

    def _request(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
        headers = {"Content-Type": "application/json"}
        if auth and self.node_id:
            headers["X-Node-Id"] = self.node_id
            headers["X-Node-Token"] = self.node_token or ""
        req = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())

    # --- identité du nœud ---

    def _state_key(self, args) -> str:
        return f"{self.base_url}|{args.wallet.lower()}|{args.mode}"

    def load_or_register(self, args) -> None:
        state = {}
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as fh:
                    state = json.load(fh)
            except (OSError, ValueError):
                state = {}
        entry = state.get(self._state_key(args))
        if entry:
            self.node_id, self.node_token = entry["node_id"], entry["node_token"]
            try:
                self._request("POST", "/api/nodes/heartbeat", {})
                log(f"Nœud existant repris: {self.node_id}")
                return
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise
                log("Identité expirée, ré-enregistrement…")

        out = self._request(
            "POST",
            "/api/nodes/register",
            {
                "wallet": args.wallet,
                "node_type": args.mode,
                "name": args.name,
                "has_model": bool(args.model_endpoint),
                "storage_allocated_gb": args.allocate_gb if args.mode == "storage" else 0,
            },
            auth=False,
        )
        self.node_id, self.node_token = out["node_id"], out["node_token"]
        state[self._state_key(args)] = {"node_id": self.node_id, "node_token": self.node_token}
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        try:
            os.chmod(self.state_path, 0o600)
        except OSError:
            pass
        log(out["message"])

    def heartbeat_forever(self, interval: int = 60) -> None:
        def loop():
            while True:
                time.sleep(interval)
                try:
                    self._request("POST", "/api/nodes/heartbeat", {})
                except Exception:
                    pass  # le prochain next_job re-signalera l'activité

        threading.Thread(target=loop, daemon=True).start()

    def next_job(self) -> dict:
        return self._request("POST", "/api/jobs/next")

    def submit(self, job_id: str, result: dict) -> dict:
        return self._request("POST", "/api/jobs/submit", {"job_id": job_id, "result": result})


# ---------------------------------------------------------------- jobs GPU


def leading_zero_bits(digest: bytes) -> int:
    bits = 0
    for byte in digest:
        if byte == 0:
            bits += 8
            continue
        bits += 8 - byte.bit_length()
        break
    return bits


def run_bench(payload: dict) -> dict:
    """Sonde de capacité façon difficulté Bitcoin : cherche des nonces dont le
    sha256(seed || nonce) commence par target_bits zéros."""
    seed = bytes.fromhex(payload["seed"])
    target = int(payload["target_bits"])
    deadline = time.monotonic() + int(payload["duration_s"])
    max_nonces = int(payload["max_nonces"])
    nonces: list[str] = []
    nonce = int.from_bytes(os.urandom(4), "big") << 16  # départ aléatoire par nœud
    hashed = 0
    while time.monotonic() < deadline and len(nonces) < max_nonces:
        for _ in range(20_000):
            digest = hashlib.sha256(seed + nonce.to_bytes(8, "big")).digest()
            hashed += 1
            if leading_zero_bits(digest) >= target:
                nonces.append(str(nonce))
                if len(nonces) >= max_nonces:
                    break
            nonce += 1
    rate = hashed / max(1e-9, int(payload["duration_s"]))
    log(f"  bench: {hashed:,} hashes (~{rate/1000:,.0f} kH/s), {len(nonces)} nonce(s) trouvé(s)")
    return {"nonces": nonces, "hashes": hashed}


def call_model(args, system: str, user: str) -> str:
    body = {
        "model": args.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 1500,
    }
    headers = {"Content-Type": "application/json"}
    if args.model_key:
        headers["Authorization"] = f"Bearer {args.model_key}"
    req = urllib.request.Request(
        args.model_endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        out = json.loads(resp.read())
    return out["choices"][0]["message"]["content"]


def run_improve(payload: dict, args) -> dict:
    content = call_model(args, payload["context"], payload["goal"])
    log(f"  improve: candidat de {len(content)} caractères généré par {args.model}")
    return {"content": content, "model": args.model}


def heuristic_vote(goal: str, content: str) -> tuple[float, str]:
    """Notation déterministe de repli quand aucun modèle local n'est configuré."""
    score = 0.0
    checks = []
    if 200 <= len(content) <= 12_000:
        score += 0.3
        checks.append("longueur ok")
    if re.search(r"(^|\n)#{1,3} ", content) or re.search(r"(^|\n)[-*] ", content):
        score += 0.25
        checks.append("structuré")
    keywords = [w for w in re.findall(r"\w{5,}", goal.lower())][:8]
    if keywords:
        hits = sum(1 for w in keywords if w in content.lower())
        score += 0.35 * (hits / len(keywords))
        checks.append(f"pertinence {hits}/{len(keywords)}")
    if not re.search(r"TODO|FIXME|lorem ipsum|\[à compléter\]", content, re.IGNORECASE):
        score += 0.1
        checks.append("sans placeholder")
    return round(min(1.0, score), 3), "heuristique: " + ", ".join(checks)


def run_vote(payload: dict, args) -> dict:
    goal, content = payload["goal"], payload["content"]
    if args.model_endpoint:
        try:
            raw = call_model(
                args,
                payload["rubric"],
                f"OBJECTIF:\n{goal}\n\nCANDIDAT:\n{content}",
            )
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(match.group(0)) if match else {}
            score = max(0.0, min(1.0, float(parsed.get("score"))))
            rationale = str(parsed.get("rationale", ""))[:500]
            log(f"  vote ({args.model}): score {score}")
            return {"score": score, "rationale": rationale}
        except Exception as exc:
            log(f"  vote: modèle indisponible ({exc}), repli heuristique")
    score, rationale = heuristic_vote(goal, content)
    log(f"  vote (heuristique): score {score}")
    return {"score": score, "rationale": rationale}


# ---------------------------------------------------------------- jobs stockage


def chunk_path(storage_dir: str, chunk_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{8,64}", chunk_id):
        raise ValueError(f"chunk_id invalide: {chunk_id!r}")
    return os.path.join(storage_dir, f"chunk_{chunk_id}.bin")


def run_store(payload: dict, storage_dir: str) -> dict:
    data = base64.b64decode(payload["data_b64"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != payload["sha256"]:
        raise ValueError("intégrité: sha256 reçu != annoncé")
    path = chunk_path(storage_dir, payload["chunk_id"])
    with open(path, "wb") as fh:
        fh.write(data)
    log(f"  store: chunk {payload['chunk_id'][:8]}… ({len(data)} octets) écrit")
    return {"sha256": digest}


def run_challenge(payload: dict, storage_dir: str) -> dict:
    path = chunk_path(storage_dir, payload["chunk_id"])
    with open(path, "rb") as fh:
        fh.seek(int(payload["offset"]))
        slice_ = fh.read(int(payload["length"]))
    digest = hashlib.sha256(bytes.fromhex(payload["nonce"]) + slice_).hexdigest()
    log(f"  challenge: chunk {payload['chunk_id'][:8]}… offset {payload['offset']}")
    return {"digest": digest}


# ---------------------------------------------------------------- détection GPU


def detect_gpu() -> str:
    for cmd in (["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                ["rocm-smi", "--showproductname"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip().splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "aucun GPU détecté (le bench tourne sur CPU)"


# ---------------------------------------------------------------- boucle principale


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mineur Odysseus Network — fournissez du calcul ou du stockage, recevez des ODY.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Options :")[0],
    )
    parser.add_argument("--wallet", required=True, help="votre adresse EVM (0x…), reçoit les ODY")
    parser.add_argument("--mode", required=True, choices=["gpu", "storage"])
    parser.add_argument("--coordinator", default=os.getenv("COORDINATOR_URL", DEFAULT_COORDINATOR))
    parser.add_argument("--name", default="", help="nom d'affichage du nœud")
    parser.add_argument("--model-endpoint", default=os.getenv("MODEL_ENDPOINT", ""),
                        help="endpoint OpenAI-compatible local (active améliorateur+voteur)")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", "llama3.1"))
    parser.add_argument("--model-key", default=os.getenv("MODEL_API_KEY", ""))
    parser.add_argument("--allocate-gb", type=float, default=0.0,
                        help="espace alloué au réseau (mode storage)")
    parser.add_argument("--storage-path", default="./odysseus_storage")
    parser.add_argument("--max-jobs", type=int, default=0, help="s'arrêter après N jobs (0 = infini)")
    parser.add_argument("--state-file",
                        default=os.path.expanduser("~/.odysseus/miner_state.json"))
    args = parser.parse_args()

    if not WALLET_RE.match(args.wallet):
        parser.error("--wallet doit être une adresse EVM 0x + 40 caractères hexadécimaux")
    if args.mode == "storage":
        if args.allocate_gb <= 0:
            parser.error("--allocate-gb est requis en mode storage")
        os.makedirs(args.storage_path, exist_ok=True)
        free_gb = shutil.disk_usage(args.storage_path).free / 1024**3
        if args.allocate_gb > free_gb:
            parser.error(f"--allocate-gb {args.allocate_gb} > espace libre ({free_gb:.1f} Go)")

    print("=" * 62)
    print(" Odysseus Network — mineur")
    print(f"   coordinateur : {args.coordinator}")
    print(f"   wallet       : {args.wallet}")
    print(f"   mode         : {args.mode}"
          + (f" ({args.allocate_gb} Go -> {args.storage_path})" if args.mode == "storage" else ""))
    if args.mode == "gpu":
        print(f"   GPU          : {detect_gpu()}")
        print(f"   modèle local : {args.model_endpoint or 'non configuré (jobs bench uniquement)'}")
    print("=" * 62, flush=True)

    api = CoordinatorApi(args.coordinator, args.state_file)
    api.load_or_register(args)
    api.heartbeat_forever()

    session_points, jobs_done = 0, 0
    while True:
        try:
            out = api.next_job()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            log(f"coordinateur injoignable ({exc}), nouvel essai dans 15 s")
            time.sleep(15)
            continue

        job = out.get("job")
        if not job:
            wait = int(out.get("retry_in", 30))
            log(f"pas de travail (époque {out.get('epoch')}), nouvel essai dans {wait} s")
            time.sleep(wait)
            continue

        kind, payload = job["kind"], job["payload"]
        log(f"job {job['id'][:8]}… [{kind}] (époque {out.get('epoch')})")
        try:
            if kind == "bench":
                result = run_bench(payload)
            elif kind == "improve":
                result = run_improve(payload, args)
            elif kind == "vote":
                result = run_vote(payload, args)
            elif kind == "store":
                result = run_store(payload, args.storage_path)
            elif kind == "challenge":
                result = run_challenge(payload, args.storage_path)
            else:
                log(f"  type de job inconnu: {kind} — ignoré")
                result = {}
        except Exception as exc:
            log(f"  échec local du job: {exc}")
            result = {"error": str(exc)[:500]}

        try:
            receipt = api.submit(job["id"], result)
        except urllib.error.HTTPError as exc:
            log(f"  soumission refusée: {exc.code} {exc.read().decode(errors='replace')[:200]}")
            continue

        session_points += int(receipt.get("points", 0))
        jobs_done += 1
        log(
            f"  -> {receipt.get('message', '')} | +{receipt.get('points', 0)} pts "
            f"(session: {session_points} pts, {jobs_done} jobs)"
        )
        if args.max_jobs and jobs_done >= args.max_jobs:
            log(f"--max-jobs atteint ({args.max_jobs}), arrêt. Total session: {session_points} pts")
            return 0
        time.sleep(1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nArrêt demandé — à bientôt sur le réseau.")
        sys.exit(0)
