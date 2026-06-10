"""Service de paiements Odysseus Network — abonnements par carte bancaire.

L'utilisateur lambda paie son accès à l'IA par carte, sans rien connaître à la
crypto. Ce service :

  - crée les sessions Stripe Checkout (mode abonnement) ;
  - reçoit les webhooks Stripe (signature vérifiée), tient le registre des
    paiements (le « chiffre d'affaires » du réseau) et les droits d'accès ;
  - expose les droits d'accès (`GET /api/entitlements/{email}`) — le point
    d'intégration du portail IA ;
  - expose le résumé des revenus à distribuer
    (`GET /api/revenue/summary`, admin) et la traçabilité des distributions
    on-chain (`POST /api/revenue/mark-distributed` après
    contracts/scripts/distribute-revenue.js).

Modes (env PAYMENTS_MODE) :
  - "stripe" : production/test Stripe réels (STRIPE_SECRET_KEY, STRIPE_PRICE_ID,
    STRIPE_WEBHOOK_SECRET requis) ;
  - "mock"   : aucun appel externe — le checkout renvoie une page de paiement
    simulée, parfaite pour le dev local et les démos du circuit complet.

Démarrage : uvicorn main:app --host 0.0.0.0 --port 9100
"""

from __future__ import annotations

import hmac
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr

# ---------------------------------------------------------------- config

MODE = os.getenv("PAYMENTS_MODE", "mock").strip().lower()  # mock | stripe
DB_PATH = os.getenv("PAYMENTS_DB", "./data/payments.db")
ADMIN_TOKEN = os.getenv("PAYMENTS_ADMIN_TOKEN", "")
PUBLIC_URL = os.getenv("PAYMENTS_PUBLIC_URL", "http://localhost:9100").rstrip("/")
SITE_URL = os.getenv("SITE_URL", "http://localhost:8088").rstrip("/")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
WEBHOOK_TOLERANCE_S = int(os.getenv("STRIPE_WEBHOOK_TOLERANCE_S", "300"))

# Durée de droit d'accès créditée à chaque facture payée (marge incluse pour
# couvrir les délais de renouvellement Stripe).
ENTITLEMENT_DAYS_PER_INVOICE = int(os.getenv("ENTITLEMENT_DAYS_PER_INVOICE", "35"))
MOCK_PRICE_CENTS = int(os.getenv("MOCK_PRICE_CENTS", "1999"))
MOCK_CURRENCY = os.getenv("MOCK_CURRENCY", "usd")

# ---------------------------------------------------------------- base

_write_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,              -- id de l'événement (idempotence webhook)
    email TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    stripe_customer TEXT NOT NULL DEFAULT '',
    stripe_subscription TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entitlements (
    email TEXT PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    until INTEGER NOT NULL DEFAULT 0,
    stripe_customer TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS distributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    tx_hash TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _read():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _write():
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _init() -> str:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _write() as conn:
        conn.executescript(_SCHEMA)
        token = ADMIN_TOKEN
        row = conn.execute("SELECT v FROM meta WHERE k = 'admin_token'").fetchone()
        generated = False
        if not token:
            token = row["v"] if row else ""
        if not token:
            token = secrets.token_hex(24)
            generated = True
        conn.execute(
            "INSERT INTO meta (k, v) VALUES ('admin_token', ?)"
            " ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (token,),
        )
    if generated:
        print(f"\n=== Odysseus Payments ===\nJeton admin généré : {token}\n", flush=True)
    return token


app = FastAPI(title="Odysseus Network — Paiements", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
_ADMIN = _init()

if MODE == "stripe" and not (STRIPE_SECRET_KEY and STRIPE_PRICE_ID and STRIPE_WEBHOOK_SECRET):
    raise RuntimeError(
        "PAYMENTS_MODE=stripe exige STRIPE_SECRET_KEY, STRIPE_PRICE_ID et STRIPE_WEBHOOK_SECRET"
    )


def _check_admin(token: str | None):
    if not token or not secrets.compare_digest(_ADMIN, token):
        raise HTTPException(401, "X-Admin-Token invalide")


# ---------------------------------------------------------------- Stripe (API directe, stdlib)


def _stripe_post(path: str, fields: dict) -> dict:
    req = urllib.request.Request(
        "https://api.stripe.com" + path,
        method="POST",
        data=urllib.parse.urlencode(fields).encode(),
        headers={
            "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise HTTPException(502, f"Stripe a refusé la requête: {detail}")


def verify_stripe_signature(payload: bytes, header: str, secret: str, now: int | None = None) -> bool:
    """Vérification manuelle de l'en-tête Stripe-Signature (t=…,v1=…).

    signed_payload = f"{t}.{corps brut}" ; v1 = HMAC-SHA256(secret, signed_payload).
    """
    now = int(time.time()) if now is None else now
    timestamp, signatures = None, []
    for part in (header or "").split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        return False
    try:
        if abs(now - int(timestamp)) > WEBHOOK_TOLERANCE_S:
            return False
    except ValueError:
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


# ---------------------------------------------------------------- logique métier


def _record_invoice_paid(
    event_id: str,
    email: str,
    amount_cents: int,
    currency: str,
    customer: str = "",
    subscription: str = "",
) -> bool:
    """Enregistre un paiement et prolonge le droit d'accès. Idempotent par event_id."""
    email = email.strip().lower()
    now = int(time.time())
    with _write() as conn:
        if conn.execute("SELECT 1 FROM payments WHERE id = ?", (event_id,)).fetchone():
            return False
        conn.execute(
            "INSERT INTO payments (id, email, amount_cents, currency, stripe_customer,"
            " stripe_subscription, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, email, amount_cents, currency.lower(), customer, subscription, now),
        )
        row = conn.execute("SELECT until FROM entitlements WHERE email = ?", (email,)).fetchone()
        base = max(now, row["until"]) if row else now
        until = base + ENTITLEMENT_DAYS_PER_INVOICE * 86_400
        conn.execute(
            "INSERT INTO entitlements (email, active, until, stripe_customer, updated_at)"
            " VALUES (?, 1, ?, ?, ?)"
            " ON CONFLICT(email) DO UPDATE SET active = 1, until = excluded.until,"
            " stripe_customer = excluded.stripe_customer, updated_at = excluded.updated_at",
            (email, until, customer, now),
        )
    return True


def _revoke(email: str):
    with _write() as conn:
        conn.execute(
            "UPDATE entitlements SET active = 0, updated_at = ? WHERE email = ?",
            (int(time.time()), email.strip().lower()),
        )


# ---------------------------------------------------------------- routes


class CheckoutRequest(BaseModel):
    email: EmailStr


class MarkDistributedRequest(BaseModel):
    amount_cents: int
    currency: str = "usd"
    tx_hash: str = ""
    note: str = ""


@app.get("/")
def root():
    return {"service": "Odysseus Network — Paiements", "mode": MODE, "docs": "/docs"}


@app.post("/api/checkout")
def create_checkout(req: CheckoutRequest):
    """Crée la session de paiement et renvoie l'URL où envoyer l'utilisateur."""
    if MODE == "mock":
        params = urllib.parse.urlencode({"email": req.email})
        return {"url": f"{PUBLIC_URL}/mock/pay?{params}", "mode": "mock"}

    session = _stripe_post(
        "/v1/checkout/sessions",
        {
            "mode": "subscription",
            "line_items[0][price]": STRIPE_PRICE_ID,
            "line_items[0][quantity]": "1",
            "customer_email": str(req.email),
            "success_url": f"{SITE_URL}/pay.html?status=success",
            "cancel_url": f"{SITE_URL}/pay.html?status=cancel",
        },
    )
    return {"url": session["url"], "mode": "stripe"}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None)):
    payload = await request.body()
    if MODE != "stripe":
        raise HTTPException(409, "webhook Stripe inactif en mode mock")
    if not verify_stripe_signature(payload, stripe_signature or "", STRIPE_WEBHOOK_SECRET):
        raise HTTPException(400, "signature Stripe invalide")

    event = json.loads(payload)
    kind = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    if kind == "invoice.paid":
        email = (obj.get("customer_email") or "").strip()
        if email:
            _record_invoice_paid(
                event_id=str(event.get("id")),
                email=email,
                amount_cents=int(obj.get("amount_paid") or 0),
                currency=str(obj.get("currency") or "usd"),
                customer=str(obj.get("customer") or ""),
                subscription=str(obj.get("subscription") or ""),
            )
    elif kind == "customer.subscription.deleted":
        # Retrouve l'email via le customer du registre.
        customer = str(obj.get("customer") or "")
        if customer:
            with _read() as conn:
                row = conn.execute(
                    "SELECT email FROM entitlements WHERE stripe_customer = ?", (customer,)
                ).fetchone()
            if row:
                _revoke(row["email"])
    # Les autres événements sont acquittés sans action.
    return {"received": True}


@app.get("/api/entitlements/{email}")
def entitlements(email: str):
    """Point d'intégration du portail IA : cet email a-t-il un accès actif ?"""
    email = email.strip().lower()
    with _read() as conn:
        row = conn.execute("SELECT * FROM entitlements WHERE email = ?", (email,)).fetchone()
    now = int(time.time())
    active = bool(row and row["active"] and row["until"] > now)
    return {
        "email": email,
        "active": active,
        "until": row["until"] if row else 0,
        "checked_at": now,
    }


@app.get("/api/revenue/summary")
def revenue_summary(x_admin_token: str | None = Header(default=None)):
    """Revenus encaissés vs distribués on-chain — par devise."""
    _check_admin(x_admin_token)
    with _read() as conn:
        gross = {
            row["currency"]: int(row["total"])
            for row in conn.execute(
                "SELECT currency, SUM(amount_cents) AS total FROM payments GROUP BY currency"
            )
        }
        distributed = {
            row["currency"]: int(row["total"])
            for row in conn.execute(
                "SELECT currency, SUM(amount_cents) AS total FROM distributions GROUP BY currency"
            )
        }
        subscribers = conn.execute(
            "SELECT COUNT(*) AS c FROM entitlements WHERE active = 1 AND until > ?",
            (int(time.time()),),
        ).fetchone()["c"]
    currencies = sorted(set(gross) | set(distributed))
    return {
        "active_subscribers": subscribers,
        "by_currency": {
            cur: {
                "gross_cents": gross.get(cur, 0),
                "distributed_cents": distributed.get(cur, 0),
                "undistributed_cents": gross.get(cur, 0) - distributed.get(cur, 0),
            }
            for cur in currencies
        },
        "next_step": "convertir en stablecoin puis: node contracts/scripts/distribute-revenue.js "
        "<montant> ; enfin POST /api/revenue/mark-distributed",
    }


@app.post("/api/revenue/mark-distributed")
def mark_distributed(req: MarkDistributedRequest, x_admin_token: str | None = Header(default=None)):
    """Trace une distribution on-chain effectuée (comptabilité interne)."""
    _check_admin(x_admin_token)
    if req.amount_cents <= 0:
        raise HTTPException(400, "amount_cents doit être positif")
    if req.tx_hash and not re.fullmatch(r"0x[0-9a-fA-F]{64}", req.tx_hash):
        raise HTTPException(400, "tx_hash invalide")
    with _write() as conn:
        conn.execute(
            "INSERT INTO distributions (amount_cents, currency, tx_hash, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (req.amount_cents, req.currency.lower(), req.tx_hash, req.note[:500], int(time.time())),
        )
    return {"ok": True}


# ---------------------------------------------------------------- mode mock


@app.get("/mock/pay", response_class=HTMLResponse)
def mock_pay_page(email: str):
    if MODE != "mock":
        raise HTTPException(404, "mode mock inactif")
    amount = f"{MOCK_PRICE_CENTS / 100:.2f}"
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Paiement simulé</title></head>
<body style="font-family:sans-serif;background:#0a0e1a;color:#e8ecf8;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0">
<form method="post" action="/mock/pay" style="background:#141b30;padding:32px;border-radius:14px;
border:1px solid #232c4a;text-align:center">
  <h2>Paiement simulé (mode mock)</h2>
  <p>Abonnement Odysseus — {amount} {MOCK_CURRENCY.upper()} / mois</p>
  <p style="opacity:.7">{email}</p>
  <input type="hidden" name="email" value="{email}">
  <button type="submit" style="padding:12px 24px;border:none;border-radius:10px;
  background:linear-gradient(90deg,#6366f1,#22d3ee);font-weight:700;cursor:pointer">
  Payer {amount} {MOCK_CURRENCY.upper()}</button>
</form></body></html>"""


@app.post("/mock/pay")
async def mock_pay_submit(request: Request):
    if MODE != "mock":
        raise HTTPException(404, "mode mock inactif")
    form = await request.form()
    email = str(form.get("email", "")).strip()
    if not email or "@" not in email:
        raise HTTPException(400, "email invalide")
    _record_invoice_paid(
        event_id=f"mock_{secrets.token_hex(8)}",
        email=email,
        amount_cents=MOCK_PRICE_CENTS,
        currency=MOCK_CURRENCY,
    )
    return RedirectResponse(f"{SITE_URL}/pay.html?status=success", status_code=303)
