#!/usr/bin/env python3
"""Synchronise les améliorations promues par le réseau vers le cœur IA.

Boucle fermée de l'auto-amélioration :
  améliorateurs → votes → promotion (coordinateur) → CE SCRIPT → skill du cœur IA.

Le script lit `GET <coordinateur>/api/evolution/active` et pousse chaque
promotion non encore synchronisée vers `POST <ia>/api/skills/add` (l'API
Skills d'Odysseus, authentifiée par un jeton API `ody_…` créé dans
Settings → API Tokens par un admin).

Garde-fou : les skills arrivent en statut **draft** — un humain les revoit
dans l'UI Skills avant activation. Le quorum de votes est un filtre de
qualité, pas un filtre de sécurité (cf. docs/LEGAL.md §5).

Usage :
    python3 evolution_sync.py             # dry-run : montre ce qui serait envoyé
    python3 evolution_sync.py --install   # envoie réellement vers le cœur IA

Env :
    COORDINATOR_URL        défaut http://127.0.0.1:9000
    AI_URL                 défaut http://127.0.0.1:7000
    AI_API_TOKEN           jeton API ody_… (requis pour --install)
    EVOLUTION_SYNC_STATE   défaut ./data/evolution_sync_state.json

Zéro dépendance (stdlib). À lancer en cron après chaque règlement d'époque.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

COORDINATOR_URL = os.getenv("COORDINATOR_URL", "http://127.0.0.1:9000").rstrip("/")
AI_URL = os.getenv("AI_URL", "http://127.0.0.1:7000").rstrip("/")
AI_API_TOKEN = os.getenv("AI_API_TOKEN", "")
STATE_PATH = os.getenv("EVOLUTION_SYNC_STATE", "./data/evolution_sync_state.json")


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"synced": []}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(STATE_PATH)), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def _skill_payload(promotion: dict) -> dict:
    """Traduit une promotion du réseau en requête POST /api/skills/add."""
    goal = str(promotion.get("goal", "")).strip()
    content = str(promotion.get("content", "")).strip()
    return {
        "name": f"network-{promotion['id']}"[:80],
        "description": (goal[:197] + "…") if len(goal) > 200 else goal,
        "category": "network-evolution",
        "tags": ["odysseus-network", "auto-promu"],
        "when_to_use": goal[:2000],
        # Champ rétro-compatible de l'API Skills : le corps libre du candidat.
        "solution": content[:5000],
        "status": "draft",  # revue humaine avant activation
        "confidence": float(promotion.get("average_score", 0.0)),
    }


def _post_skill(payload: dict) -> dict:
    req = urllib.request.Request(
        AI_URL + "/api/skills/add",
        method="POST",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AI_API_TOKEN}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main(argv: list[str]) -> int:
    install = "--install" in argv
    if install and not AI_API_TOKEN:
        sys.exit("--install exige AI_API_TOKEN (Settings → API Tokens du cœur IA)")

    try:
        promotions = _get(COORDINATOR_URL + "/api/evolution/active")["promotions"]
    except (urllib.error.URLError, KeyError) as exc:
        sys.exit(f"coordinateur injoignable ({COORDINATOR_URL}): {exc}")

    state = _load_state()
    pending = [p for p in promotions if p["id"] not in state["synced"]]
    if not pending:
        print(f"Rien à synchroniser ({len(promotions)} promotion(s), toutes déjà installées).")
        return 0

    for promotion in pending:
        payload = _skill_payload(promotion)
        if not install:
            print(f"[dry-run] installerait '{payload['name']}' — {payload['description'][:70]}"
                  f" (score {payload['confidence']})")
            continue
        try:
            out = _post_skill(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            print(f"ÉCHEC '{payload['name']}': {exc.code} {detail}", file=sys.stderr)
            continue
        state["synced"].append(promotion["id"])
        _save_state(state)
        print(f"Installé '{payload['name']}' en draft — réponse: {json.dumps(out)[:120]}")

    if not install:
        print(f"\n{len(pending)} promotion(s) à installer. Relancer avec --install "
              "(AI_API_TOKEN requis), puis revue dans l'UI Skills avant activation.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
