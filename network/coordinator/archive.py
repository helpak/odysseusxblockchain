#!/usr/bin/env python3
"""CLI d'archivage vers le réseau de stockage Odysseus (stdlib uniquement).

Usage :
    python3 archive.py put <clé> <fichier>
    python3 archive.py get <clé> <fichier_sortie>

Env :
    COORDINATOR_URL          (défaut http://127.0.0.1:9000)
    COORDINATOR_ADMIN_TOKEN  (obligatoire)

Important : chiffrez les données sensibles AVANT l'archivage — le réseau de
stockage ne doit voir que des blobs opaques.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

COORDINATOR_URL = os.getenv("COORDINATOR_URL", "http://127.0.0.1:9000").rstrip("/")
ADMIN_TOKEN = os.getenv("COORDINATOR_ADMIN_TOKEN", "")


def _request(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        COORDINATOR_URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Admin-Token": ADMIN_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        sys.exit(f"Erreur {exc.code} sur {path}: {detail}")


def main(argv: list[str]) -> int:
    if not ADMIN_TOKEN:
        sys.exit("COORDINATOR_ADMIN_TOKEN manquant (voir les logs de démarrage du coordinateur)")
    if len(argv) == 4 and argv[1] == "put":
        with open(argv[3], "rb") as fh:
            data = fh.read()
        out = _request(
            "POST",
            "/api/admin/storage/archive",
            {"key": argv[2], "data_b64": base64.b64encode(data).decode()},
        )
        print(f"Archivé: {out['key']} ({out['bytes']} octets, {out['chunks']} chunk(s))")
        return 0
    if len(argv) == 4 and argv[1] == "get":
        out = _request("GET", f"/api/admin/storage/retrieve/{urllib.parse.quote(argv[2], safe='')}")
        with open(argv[3], "wb") as fh:
            fh.write(base64.b64decode(out["data_b64"]))
        print(f"Restauré: {argv[2]} -> {argv[3]}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
