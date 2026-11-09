"""Public benchmark every BENCH_INTERVAL_SECONDS (2 h by default).

The same task series (published seed) is given:
  - to the AQL network, through the normal serving queue (with the network prompt);
  - to every configured reference model (OpenAI-compatible API).
The coordinator grades all answers the same way: the comparison is on the
SAME test, not on scores published elsewhere.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.request

import db
import evolution
import serving
import settings
import tasks

_running = threading.Lock()


def _store(run_id, started, seed, target, model, correct, total, duration, error=""):
    with db.write() as conn:
        conn.execute(
            "INSERT INTO benchmark_runs (id, started_at, seed, target, model, correct, total, duration_s, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{run_id}-{target}", started, seed, target, model, correct, total, duration, error[:300]),
        )


def _run_network(series: list[dict]) -> tuple[int | None, str]:
    with db.read() as conn:
        prompt = evolution.active(conn)["content"]
    rids = {
        t["id"]: serving.submit(
            serving.with_network_prompt([{"role": "user", "content": t["prompt"]}], prompt),
            512, 0.0, kind="bench",
        )
        for t in series
    }
    deadline = time.time() + settings.BENCH_TIMEOUT_SECONDS
    answers, missing = {}, 0
    for task_id, rid in rids.items():
        req = serving.wait_for(rid, max(1.0, deadline - time.time()))
        if req and req["status"] == "done":
            answers[str(task_id)] = req["content"]
        else:
            missing += 1
        serving.forget(rid)
    if missing == len(series):
        return None, "no miner answered in time"
    note = f"{missing} task(s) unanswered" if missing else ""
    return tasks.score(series, answers), note


def _call_reference(ref: dict, prompt: str) -> str:
    headers = {"Content-Type": "application/json"}
    key = os.getenv(ref.get("key_env", ""), "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps({
        "model": ref["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 512,
    }).encode()
    req = urllib.request.Request(ref["url"].rstrip("/") + "/chat/completions", data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def run_once() -> str:
    if not _running.acquire(blocking=False):
        return "already running"
    try:
        run_id = secrets.token_hex(6)
        seed = int(time.time())
        series = tasks.generate(seed, settings.BENCH_TASKS)

        t0 = time.time()
        correct, note = _run_network(series)
        _store(run_id, int(t0), seed, "network", settings.NETWORK_MODEL, correct, len(series),
               int(time.time() - t0), note)

        for ref in settings.BENCH_REFERENCES:
            t0 = time.time()
            answers, error = {}, ""
            try:
                for t in series:
                    answers[str(t["id"])] = _call_reference(ref, t["prompt"])
                ref_correct = tasks.score(series, answers)
            except Exception as exc:  # reference unavailable: recorded without a score
                ref_correct, error = None, str(exc)
            _store(run_id, int(t0), seed, ref["name"], ref["model"], ref_correct, len(series),
                   int(time.time() - t0), error)
        return run_id
    finally:
        _running.release()


def history(conn, limit: int = 40) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM benchmark_runs ORDER BY started_at DESC, target LIMIT ?", (limit,)
    ).fetchall()
    return [
        {
            "run": r["id"].split("-")[0],
            "started_at": r["started_at"],
            "seed": r["seed"],
            "target": r["target"],
            "model": r["model"],
            "correct": r["correct"],
            "total": r["total"],
            "score_pct": None if r["correct"] is None else round(100 * r["correct"] / r["total"], 1),
            "duration_s": r["duration_s"],
            "note": r["error"],
        }
        for r in rows
    ]


def start_background() -> None:
    if settings.BENCH_INTERVAL_SECONDS <= 0:
        return

    def loop():
        time.sleep(60)  # give miners time to connect after a restart
        while True:
            try:
                run_once()
            except Exception:
                pass
            time.sleep(settings.BENCH_INTERVAL_SECONDS)

    threading.Thread(target=loop, daemon=True, name="benchmark").start()
