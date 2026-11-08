"""Stripe usage meter: one billing meter event per verified write, test mode only.

Calligraphe bills a school only for comments that passed the read-back check, never for
attempts, retries that failed, abstentions or undos that were not verified. The journal
line with status `verified` is the invoice line: the writer loop calls
`record_verified_write` for that line only, and records the outcome in its `billed` field.

The event `identifier` is `<run_id>:<item_id>`, the journal's own key for the line, and is
also sent as the Idempotency-Key: Stripe deduplicates on it, so a retried request never
bills the same write twice.

Environment: STRIPE_SECRET_KEY (a test-mode key, never printed) and STRIPE_CUSTOMER_ID
(printed by scripts/stripe_setup.py). Without both, the writer loop sends nothing.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE = "https://api.stripe.com/v1"
EVENT_NAME = "verified_write"
CUSTOMER_KEY = "stripe_customer_id"
VALUE_KEY = "value"
TEST_KEY_PREFIXES = ("sk_test_", "rk_test_")
TIMEOUT_S = 10.0


class StripeError(RuntimeError):
    """A refused or failed Stripe call; the message never contains the key."""


def enabled() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_CUSTOMER_ID"))


def secret_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise StripeError("STRIPE_SECRET_KEY is not set")
    if not key.startswith(TEST_KEY_PREFIXES):
        raise StripeError("STRIPE_SECRET_KEY is not a test-mode key; Calligraphe meters in test mode only")
    return key


def request(method: str, path: str, data: dict[str, str] | None = None, *, params: dict[str, str] | None = None,
            idempotency_key: str | None = None, client: httpx.Client | None = None) -> dict[str, Any]:
    """One form-encoded Stripe call; returns the decoded JSON or raises StripeError."""
    headers = {"Authorization": f"Bearer {secret_key()}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        r = http.request(method, f"{API_BASE}{path}", data=data, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise StripeError(f"Stripe {method} {path}: {type(e).__name__}") from None
    finally:
        if own:
            http.close()
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
        raise StripeError(f"Stripe {method} {path}: HTTP {r.status_code}: {message or 'no message'}")
    return body


def identifier(run_id: str, item_id: str) -> str:
    return f"{run_id}:{item_id}"


def record_verified_write(run_id: str, item_id: str, customer_id: str, *,
                          client: httpx.Client | None = None) -> dict[str, Any]:
    """Post one `verified_write` meter event (value 1) for this journal line; returns Stripe's reply."""
    ident = identifier(run_id, item_id)
    data = {
        "event_name": EVENT_NAME,
        f"payload[{CUSTOMER_KEY}]": customer_id,
        f"payload[{VALUE_KEY}]": "1",
        "identifier": ident,
    }
    return request("POST", "/billing/meter_events", data, idempotency_key=ident, client=client)
