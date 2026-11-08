# Billing: one meter event per verified write (Stripe, test mode)

## Why per verified write

A school pays for comments that are in its application, letter for letter, not for the agent's effort. A write counts only when the read-back comparison recorded `verified`; attempts, `mismatch` lines, abstentions, `not_found`, aborted items and STOP cost nothing. A mismatch followed by a successful corrective write (`g01-r1`) is billed once, for the corrective line. The journal line is the invoice line: every event Stripe receives names a `verified` line in `runs/<run_id>/journal.jsonl`, and that line records `billed`.

## What is sent

For each `verified` line, and only when both `STRIPE_SECRET_KEY` and `STRIPE_CUSTOMER_ID` are set, `agent/run_writer.py` calls `billing.meter.record_verified_write`, which sends one request:

```
POST https://api.stripe.com/v1/billing/meter_events      (form-encoded, Authorization: Bearer $STRIPE_SECRET_KEY)
event_name=verified_write
payload[stripe_customer_id]=<STRIPE_CUSTOMER_ID>
payload[value]=1
identifier=<run_id>:<item_id>                              (also sent as Idempotency-Key)
```

Nothing else leaves the machine: no student name, no comment text, no read-back. Stripe enforces uniqueness of `identifier` over a rolling window, and the Idempotency-Key makes a resent request return the first answer, so a retry never bills twice.

The journal field `billed` is `true` when Stripe accepted the event, `false` when the call failed (the error is printed and appended to the line's `note`), `null` when metering is not configured or the line is not `verified`. A Stripe error never changes the status of a write.

## Test mode only

Both `billing/meter.py` and `scripts/stripe_setup.py` refuse a key that does not start with `sk_test_` or `rk_test_`, before any request. The customer is fictitious. No price, subscription or invoice is created here; in the Stripe test dashboard the meter shows the summed events per customer, and a metered price can be attached to it to see what an invoice would contain.

## Run it

```bash
export STRIPE_SECRET_KEY=sk_test_...       # test mode, never printed, never committed
python scripts/stripe_setup.py             # creates the "Verified writes" meter and "Collège de démonstration", once
export STRIPE_CUSTOMER_ID=cus_...          # the id it prints

python -m agent.run_writer --items data/moodle_batch_a.csv --target moodle   # needs HAI_API_KEY too
```

Running the setup again reuses the active `verified_write` meter and, if `STRIPE_CUSTOMER_ID` is set, that customer. After the run, the number of journal lines with `"billed": true` equals the meter's total for the customer in the test dashboard (Billing > Meters > Verified writes).

Without `STRIPE_SECRET_KEY` or `STRIPE_CUSTOMER_ID`, the writer loop runs exactly as before and sends nothing to Stripe.
