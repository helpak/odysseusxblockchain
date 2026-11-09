#!/usr/bin/env python3
"""Mineur AQL — un seul fichier, zéro dépendance (Python 3.10+).

Vous donnez votre wallet, vous choisissez ce que vous fournissez, et vos gains
(AQL émis + USDT payé par les utilisateurs) s'accumulent à chaque époque.

  Calcul (GPU) — votre machine fait tourner le modèle du réseau et :
    - SERT les utilisateurs de l'IA (payé en USDT + AQL) ;
    - CONTRÔLE les réponses d'autres mineurs (contrôles aléatoires) ;
    - AMÉLIORE l'IA (propose de meilleurs prompts) et MESURE les propositions.
  Il faut un serveur de modèle local compatible OpenAI (Ollama, vLLM,
  llama.cpp) qui sert le modèle du réseau (affiché au démarrage) :

      python3 aql_miner.py --wallet 0xVOTRE_WALLET --mode gpu \\
          --model-endpoint http://localhost:11434/v1

  Stockage — votre disque héberge des données chiffrées du réseau, payé à
  chaque preuve de stockage :

      python3 aql_miner.py --wallet 0xVOTRE_WALLET --mode storage \\
          --allocate-gb 100 --storage-path ./aql_storage

Options : --coordinator URL, --model (défaut : modèle du réseau), --name,
--max-jobs N (0 = infini), --state-file. L'identité du nœud est persistée.
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


# ---------------------------------------------------------------- coordinateur


class CoordinatorApi:
    def __init__(self, base_url: str, state_path: str):
        self.base_url = base_url.rstrip("/")
        self.state_path = state_path
        self.node_id: str | None = None
        self.node_token: str | None = None

    def request(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> dict:
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())

    def network_model(self) -> str:
        return self.request("GET", "/v1/models", auth=False)["data"][0]["id"]

    def _state_key(self, args) -> str:
        return f"{self.base_url}|{args.wallet.lower()}|{args.mode}|{args.model if args.mode == 'gpu' else ''}"

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
                self.request("POST", "/api/nodes/heartbeat", {})
                log(f"Nœud existant repris : {self.node_id}")
                return
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise
                log("Identité inconnue du coordinateur, ré-enregistrement…")

        out = self.request(
            "POST",
            "/api/nodes/register",
            {
                "wallet": args.wallet,
                "node_type": args.mode,
                "name": args.name,
                "model": args.model if args.mode == "gpu" else "",
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
                    self.request("POST", "/api/nodes/heartbeat", {})
                except Exception:
                    pass  # le prochain appel de job re-signalera l'activité

        threading.Thread(target=loop, daemon=True).start()

    def next_job(self) -> dict:
        return self.request("POST", "/api/jobs/next")

    def submit(self, job_id: str, result: dict) -> dict:
        return self.request("POST", "/api/jobs/submit", {"job_id": job_id, "result": result})


# ---------------------------------------------------------------- modèle local


def chat(args, messages: list[dict], max_tokens: int = 1024, temperature: float = 0.0) -> str:
    body = {
        "model": args.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if args.model_key:
        headers["Authorization"] = f"Bearer {args.model_key}"
    req = urllib.request.Request(
        args.model_endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        out = json.loads(resp.read())
    return out["choices"][0]["message"]["content"] or ""


def run_serve(payload: dict, args) -> dict:
    """serve / verify / bench : même travail, répondre avec le modèle du réseau."""
    content = chat(args, payload["messages"], int(payload["max_tokens"]), float(payload["temperature"]))
    return {"content": content}


def run_improve(payload: dict, args) -> dict:
    examples = "\n\n".join(f"- {e}" for e in payload["examples"])
    content = chat(
        args,
        [
            {"role": "system", "content": payload["instructions"]},
            {
                "role": "user",
                "content": f"PROMPT SYSTÈME ACTUEL :\n{payload['current_prompt']}\n\n"
                           f"EXEMPLES DE TÂCHES :\n{examples}\n\nNOUVEAU PROMPT SYSTÈME :",
            },
        ],
        max_tokens=1200,
        temperature=0.7,
    )
    return {"content": content.strip()}


def run_measure(payload: dict, args) -> dict:
    """Répond à chaque tâche avec le prompt actuel puis avec le candidat. Le
    coordinateur corrige lui-même : on renvoie les réponses brutes."""
    out = {"baseline": {}, "candidate": {}}
    for task in payload["tasks"]:
        for label, prompt in (("baseline", payload["baseline_prompt"]), ("candidate", payload["candidate_prompt"])):
            out[label][str(task["id"])] = chat(
                args,
                [{"role": "system", "content": prompt}, {"role": "user", "content": task["prompt"]}],
                max_tokens=512,
                temperature=0.0,
            )
    return out


# ---------------------------------------------------------------- stockage


def chunk_path(storage_dir: str, chunk_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{8,64}", chunk_id):
        raise ValueError(f"chunk_id invalide: {chunk_id!r}")
    return os.path.join(storage_dir, f"chunk_{chunk_id}.bin")


def run_store(payload: dict, storage_dir: str) -> dict:
    data = base64.b64decode(payload["data_b64"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != payload["sha256"]:
        raise ValueError("intégrité : sha256 reçu != annoncé")
    with open(chunk_path(storage_dir, payload["chunk_id"]), "wb") as fh:
        fh.write(data)
    log(f"  store : chunk {payload['chunk_id'][:8]}… ({len(data)} octets) écrit")
    return {"sha256": digest}


def run_challenge(payload: dict, storage_dir: str) -> dict:
    with open(chunk_path(storage_dir, payload["chunk_id"]), "rb") as fh:
        fh.seek(int(payload["offset"]))
        slice_ = fh.read(int(payload["length"]))
    digest = hashlib.sha256(bytes.fromhex(payload["nonce"]) + slice_).hexdigest()
    log(f"  challenge : chunk {payload['chunk_id'][:8]}… offset {payload['offset']}")
    return {"digest": digest}


# ---------------------------------------------------------------- matériel


def detect_gpu() -> str:
    for cmd in (["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                ["rocm-smi", "--showproductname"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip().splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "aucun GPU détecté (le modèle tournera sur ce que votre serveur local utilise)"


# ---------------------------------------------------------------- boucle principale


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mineur AQL — fournissez du calcul ou du stockage, recevez des AQL et des USDT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Options :")[0],
    )
    parser.add_argument("--wallet", required=True, help="votre adresse EVM (0x…), reçoit les gains")
    parser.add_argument("--mode", required=True, choices=["gpu", "storage"])
    parser.add_argument("--coordinator", default=os.getenv("COORDINATOR_URL", DEFAULT_COORDINATOR))
    parser.add_argument("--name", default="", help="nom d'affichage du nœud")
    parser.add_argument("--model-endpoint", default=os.getenv("MODEL_ENDPOINT", ""),
                        help="serveur de modèle local compatible OpenAI (requis en mode gpu)")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", ""),
                        help="nom du modèle chez votre serveur local (défaut : modèle du réseau)")
    parser.add_argument("--model-key", default=os.getenv("MODEL_API_KEY", ""))
    parser.add_argument("--allocate-gb", type=float, default=0.0, help="espace alloué (mode storage)")
    parser.add_argument("--storage-path", default="./aql_storage")
    parser.add_argument("--max-jobs", type=int, default=0, help="s'arrêter après N jobs (0 = infini)")
    parser.add_argument("--state-file", default=os.path.expanduser("~/.aql/miner_state.json"))
    args = parser.parse_args()

    if not WALLET_RE.match(args.wallet):
        parser.error("--wallet doit être une adresse EVM 0x + 40 caractères hexadécimaux")
    if args.mode == "gpu" and not args.model_endpoint:
        parser.error("--model-endpoint est requis en mode gpu : le réseau paie le travail de VOTRE modèle")
    if args.mode == "storage":
        if args.allocate_gb <= 0:
            parser.error("--allocate-gb est requis en mode storage")
        os.makedirs(args.storage_path, exist_ok=True)
        free_gb = shutil.disk_usage(args.storage_path).free / 1024**3
        if args.allocate_gb > free_gb:
            parser.error(f"--allocate-gb {args.allocate_gb} > espace libre ({free_gb:.1f} Go)")

    api = CoordinatorApi(args.coordinator, args.state_file)
    if args.mode == "gpu":
        network_model = api.network_model()
        if not args.model:
            args.model = network_model
        elif args.model != network_model:
            log(f"ATTENTION : le réseau sert « {network_model} », vous déclarez « {args.model} » : "
                "aucun travail de calcul ne vous sera confié.")

    print("=" * 66)
    print(" AQL Network — mineur")
    print(f"   coordinateur : {args.coordinator}")
    print(f"   wallet       : {args.wallet}")
    print(f"   mode         : {args.mode}"
          + (f" ({args.allocate_gb} Go -> {args.storage_path})" if args.mode == "storage" else ""))
    if args.mode == "gpu":
        print(f"   GPU          : {detect_gpu()}")
        print(f"   modèle       : {args.model} via {args.model_endpoint}")
    print("=" * 66, flush=True)

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
            if out.get("reason"):
                log(f"aucun travail : {out['reason']}")
            wait = int(out.get("retry_in", 30))
            if wait:
                time.sleep(wait)
            continue

        kind, payload = job["kind"], job["payload"]
        log(f"job {job['id'][:8]}… [{kind}] (époque {out.get('epoch')})")
        try:
            if kind in ("serve", "verify", "bench"):
                result = run_serve(payload, args)
            elif kind == "improve":
                result = run_improve(payload, args)
            elif kind == "measure":
                result = run_measure(payload, args)
            elif kind == "store":
                result = run_store(payload, args.storage_path)
            elif kind == "challenge":
                result = run_challenge(payload, args.storage_path)
            else:
                log(f"  type de job inconnu : {kind} — ignoré")
                result = {}
        except Exception as exc:
            log(f"  échec local du job : {exc}")
            result = {"error": str(exc)[:500]}

        try:
            receipt = api.submit(job["id"], result)
        except urllib.error.HTTPError as exc:
            log(f"  soumission refusée : {exc.code} {exc.read().decode(errors='replace')[:200]}")
            continue

        session_points += int(receipt.get("points", 0))
        jobs_done += 1
        log(
            f"  -> {receipt.get('message', '')} | +{receipt.get('points', 0)} pts "
            f"(session : {session_points} pts, {jobs_done} jobs, réputation {receipt.get('reputation')})"
        )
        if args.max_jobs and jobs_done >= args.max_jobs:
            log(f"--max-jobs atteint ({args.max_jobs}), arrêt. Total session : {session_points} pts")
            return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nArrêt demandé — à bientôt sur le réseau.")
        sys.exit(0)
