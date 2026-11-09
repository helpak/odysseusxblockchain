#!/usr/bin/env python3
"""AQL miner — a single file, zero dependencies (Python 3.10+).

You give your wallet, you choose what you provide, and your earnings
(newly issued AQL + USDT paid by users) accumulate every epoch.

  Compute (GPU) — your machine runs the network's model and:
    - SERVES the AI's users (paid in USDT + AQL);
    - CHECKS other miners' answers (random spot checks);
    - IMPROVES the AI (proposes better prompts) and MEASURES the proposals.
  You need a local OpenAI-compatible model server (Ollama, vLLM,
  llama.cpp) that serves the network's model (shown at startup):

      python3 aql_miner.py --wallet 0xYOUR_WALLET --mode gpu \\
          --model-endpoint http://localhost:11434/v1

  Storage — your disk hosts encrypted network data, paid for
  each proof of storage:

      python3 aql_miner.py --wallet 0xYOUR_WALLET --mode storage \\
          --allocate-gb 100 --storage-path ./aql_storage

Options: --coordinator URL, --model (default: the network's model), --name,
--max-jobs N (0 = unlimited), --state-file. The node identity is persisted.
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


# ---------------------------------------------------------------- coordinator


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
                log(f"Resumed existing node: {self.node_id}")
                return
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise
                log("Identity unknown to the coordinator, registering again…")

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
                    pass  # the next job call will report activity again

        threading.Thread(target=loop, daemon=True).start()

    def next_job(self) -> dict:
        return self.request("POST", "/api/jobs/next")

    def submit(self, job_id: str, result: dict) -> dict:
        return self.request("POST", "/api/jobs/submit", {"job_id": job_id, "result": result})


# ---------------------------------------------------------------- local model


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
    """serve / verify / bench: same work, answer with the network's model."""
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
                "content": f"CURRENT SYSTEM PROMPT:\n{payload['current_prompt']}\n\n"
                           f"TASK EXAMPLES:\n{examples}\n\nNEW SYSTEM PROMPT:",
            },
        ],
        max_tokens=1200,
        temperature=0.7,
    )
    return {"content": content.strip()}


def run_measure(payload: dict, args) -> dict:
    """Answers each task with the current prompt, then with the candidate. The
    coordinator grades them itself: we send back the raw answers."""
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


# ---------------------------------------------------------------- storage


def chunk_path(storage_dir: str, chunk_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{8,64}", chunk_id):
        raise ValueError(f"invalid chunk_id: {chunk_id!r}")
    return os.path.join(storage_dir, f"chunk_{chunk_id}.bin")


def run_store(payload: dict, storage_dir: str) -> dict:
    data = base64.b64decode(payload["data_b64"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != payload["sha256"]:
        raise ValueError("integrity: received sha256 != announced sha256")
    with open(chunk_path(storage_dir, payload["chunk_id"]), "wb") as fh:
        fh.write(data)
    log(f"  store: chunk {payload['chunk_id'][:8]}… ({len(data)} bytes) written")
    return {"sha256": digest}


def run_challenge(payload: dict, storage_dir: str) -> dict:
    with open(chunk_path(storage_dir, payload["chunk_id"]), "rb") as fh:
        fh.seek(int(payload["offset"]))
        slice_ = fh.read(int(payload["length"]))
    digest = hashlib.sha256(bytes.fromhex(payload["nonce"]) + slice_).hexdigest()
    log(f"  challenge: chunk {payload['chunk_id'][:8]}… offset {payload['offset']}")
    return {"digest": digest}


# ---------------------------------------------------------------- hardware


def detect_gpu() -> str:
    for cmd in (["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                ["rocm-smi", "--showproductname"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip().splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "no GPU detected (the model will run on whatever your local server uses)"


# ---------------------------------------------------------------- main loop


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AQL miner — provide compute or storage, earn AQL and USDT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Options:")[0],
    )
    parser.add_argument("--wallet", required=True, help="your EVM address (0x…), receives the earnings")
    parser.add_argument("--mode", required=True, choices=["gpu", "storage"])
    parser.add_argument("--coordinator", default=os.getenv("COORDINATOR_URL", DEFAULT_COORDINATOR))
    parser.add_argument("--name", default="", help="display name of the node")
    parser.add_argument("--model-endpoint", default=os.getenv("MODEL_ENDPOINT", ""),
                        help="local OpenAI-compatible model server (required in gpu mode)")
    parser.add_argument("--model", default=os.getenv("MODEL_NAME", ""),
                        help="model name on your local server (default: the network's model)")
    parser.add_argument("--model-key", default=os.getenv("MODEL_API_KEY", ""))
    parser.add_argument("--allocate-gb", type=float, default=0.0, help="allocated space (storage mode)")
    parser.add_argument("--storage-path", default="./aql_storage")
    parser.add_argument("--max-jobs", type=int, default=0, help="stop after N jobs (0 = unlimited)")
    parser.add_argument("--state-file", default=os.path.expanduser("~/.aql/miner_state.json"))
    args = parser.parse_args()

    if not WALLET_RE.match(args.wallet):
        parser.error("--wallet must be an EVM address: 0x + 40 hexadecimal characters")
    if args.mode == "gpu" and not args.model_endpoint:
        parser.error("--model-endpoint is required in gpu mode: the network pays for the work of YOUR model")
    if args.mode == "storage":
        if args.allocate_gb <= 0:
            parser.error("--allocate-gb is required in storage mode")
        os.makedirs(args.storage_path, exist_ok=True)
        free_gb = shutil.disk_usage(args.storage_path).free / 1024**3
        if args.allocate_gb > free_gb:
            parser.error(f"--allocate-gb {args.allocate_gb} > free space ({free_gb:.1f} GB)")

    api = CoordinatorApi(args.coordinator, args.state_file)
    if args.mode == "gpu":
        network_model = api.network_model()
        if not args.model:
            args.model = network_model
        elif args.model != network_model:
            log(f"WARNING: the network serves '{network_model}', you declared '{args.model}': "
                "no compute work will be assigned to you.")

    print("=" * 66)
    print(" AQL Network — miner")
    print(f"   coordinator  : {args.coordinator}")
    print(f"   wallet       : {args.wallet}")
    print(f"   mode         : {args.mode}"
          + (f" ({args.allocate_gb} GB -> {args.storage_path})" if args.mode == "storage" else ""))
    if args.mode == "gpu":
        print(f"   GPU          : {detect_gpu()}")
        print(f"   model        : {args.model} via {args.model_endpoint}")
    print("=" * 66, flush=True)

    api.load_or_register(args)
    api.heartbeat_forever()

    session_points, jobs_done = 0, 0
    while True:
        try:
            out = api.next_job()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            log(f"coordinator unreachable ({exc}), retrying in 15 s")
            time.sleep(15)
            continue

        job = out.get("job")
        if not job:
            if out.get("reason"):
                log(f"no work: {out['reason']}")
            wait = int(out.get("retry_in", 30))
            if wait:
                time.sleep(wait)
            continue

        kind, payload = job["kind"], job["payload"]
        log(f"job {job['id'][:8]}… [{kind}] (epoch {out.get('epoch')})")
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
                log(f"  unknown job type: {kind} — skipped")
                result = {}
        except Exception as exc:
            log(f"  job failed locally: {exc}")
            result = {"error": str(exc)[:500]}

        try:
            receipt = api.submit(job["id"], result)
        except urllib.error.HTTPError as exc:
            log(f"  submission rejected: {exc.code} {exc.read().decode(errors='replace')[:200]}")
            continue

        session_points += int(receipt.get("points", 0))
        jobs_done += 1
        log(
            f"  -> {receipt.get('message', '')} | +{receipt.get('points', 0)} pts "
            f"(session: {session_points} pts, {jobs_done} jobs, reputation {receipt.get('reputation')})"
        )
        if args.max_jobs and jobs_done >= args.max_jobs:
            log(f"--max-jobs reached ({args.max_jobs}), stopping. Session total: {session_points} pts")
            return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStop requested — see you soon on the network.")
        sys.exit(0)
