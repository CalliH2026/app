"""Create, once, the Stripe test-mode meter and demo customer that billing/meter.py posts to.

The meter sums `verified_write` events per customer (`payload[stripe_customer_id]`,
`payload[value]`). The customer is the fictitious school "Collège de démonstration". Running
this again reuses the active meter and, when STRIPE_CUSTOMER_ID is set, that customer.

    export STRIPE_SECRET_KEY=sk_test_...     # test mode only, never printed
    python scripts/stripe_setup.py
    export STRIPE_CUSTOMER_ID=cus_...        # the id this prints
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from billing.meter import CUSTOMER_KEY, EVENT_NAME, VALUE_KEY, StripeError, request, secret_key

METER_DISPLAY_NAME = "Verified writes"
CUSTOMER_NAME = "Collège de démonstration"


def meter_mismatches(meter: dict[str, Any]) -> list[str]:
    """Settings of an existing meter that differ from what billing/meter.py sends."""
    expected = {
        ("default_aggregation", "formula"): "sum",
        ("customer_mapping", "event_payload_key"): CUSTOMER_KEY,
        ("customer_mapping", "type"): "by_id",
        ("value_settings", "event_payload_key"): VALUE_KEY,
    }
    return [f"{a}[{b}]={(meter.get(a) or {}).get(b)!r}, expected {want!r}"
            for (a, b), want in expected.items() if (meter.get(a) or {}).get(b) != want]


def ensure_meter(client: Any = None) -> dict[str, Any]:
    meters = request("GET", "/billing/meters", params={"status": "active", "limit": "100"}, client=client)
    for m in meters.get("data") or []:
        if m.get("event_name") == EVENT_NAME:
            wrong = meter_mismatches(m)
            if wrong:
                raise StripeError(f"active meter {m.get('id')} for {EVENT_NAME} is configured differently: "
                                  f"{'; '.join(wrong)}. Deactivate it in the dashboard and run this again.")
            return m
    return request("POST", "/billing/meters", {
        "display_name": METER_DISPLAY_NAME,
        "event_name": EVENT_NAME,
        "default_aggregation[formula]": "sum",
        "customer_mapping[event_payload_key]": CUSTOMER_KEY,
        "customer_mapping[type]": "by_id",
        "value_settings[event_payload_key]": VALUE_KEY,
    }, client=client)


def ensure_customer(client: Any = None) -> dict[str, Any]:
    existing = os.environ.get("STRIPE_CUSTOMER_ID")
    if existing:
        customer = request("GET", f"/customers/{existing}", client=client)
        if not customer.get("deleted"):
            return customer
    return request("POST", "/customers", {"name": CUSTOMER_NAME}, client=client)


def main(argv: list[str] | None = None, client: Any = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.parse_args(argv)
    try:
        secret_key()
        meter = ensure_meter(client)
        customer = ensure_customer(client)
    except StripeError as e:
        print(e, file=sys.stderr)
        return 2
    print(f"meter {meter.get('id')} ({meter.get('display_name')}, event_name {meter.get('event_name')})")
    print(f"customer {customer.get('id')} ({customer.get('name')})")
    print("store it in the environment:")
    print(f"export STRIPE_CUSTOMER_ID={customer.get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
