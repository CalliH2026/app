import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from agent import run_writer
from agent.journal import Journal
from agent.queue import Queue
from billing import meter

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("stripe_setup", ROOT / "scripts" / "stripe_setup.py")
stripe_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stripe_setup)

FAKE_KEY = "sk_test_fake_for_tests"


class Recorder:
    """A Stripe stand-in: records each request and answers from `replies` keyed by (method, path)."""

    def __init__(self, replies: dict[tuple[str, str], tuple[int, dict]] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.replies = replies or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.replies.get((request.method, request.url.path), (200, {"object": "ok"}))
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def form(self, i: int = 0) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(self.requests[i].content.decode()).items()}


@pytest.fixture
def stripe_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_KEY)
    monkeypatch.setenv("STRIPE_CUSTOMER_ID", "cus_demo")


def _writer(tmp_path: Path, recorder: Recorder):
    items = tmp_path / "items.csv"
    items.write_text("item_id,student,text\ng01,Léa Martin,Très bon trimestre.\n", encoding="utf-8")
    queue = Queue.from_csv(items, stop_file=tmp_path / "STOP")
    journal = Journal(tmp_path / "journal.jsonl")
    report = run_writer.make_report_result(queue, journal, {}, run_id="20261107-150000", arm="calligraphe",
                                           target="moodle", billing_client=recorder.client())
    return queue, journal, report


def test_record_verified_write_posts_one_form_encoded_meter_event(stripe_env):
    rec = Recorder()
    meter.record_verified_write("run1", "g01", "cus_demo", client=rec.client())
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == "https://api.stripe.com/v1/billing/meter_events"
    assert req.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert req.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert req.headers["Idempotency-Key"] == "run1:g01"
    assert rec.form() == {"event_name": "verified_write", "payload[stripe_customer_id]": "cus_demo",
                          "payload[value]": "1", "identifier": "run1:g01"}


def test_live_key_is_refused_before_any_request(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_not_a_real_key")
    rec = Recorder()
    with pytest.raises(meter.StripeError, match="test-mode"):
        meter.record_verified_write("run1", "g01", "cus_demo", client=rec.client())
    assert rec.requests == []


def test_stripe_error_message_has_no_key(stripe_env):
    rec = Recorder({("POST", "/v1/billing/meter_events"): (400, {"error": {"message": "No such customer"}})})
    with pytest.raises(meter.StripeError) as e:
        meter.record_verified_write("run1", "g01", "cus_demo", client=rec.client())
    assert "No such customer" in str(e.value) and FAKE_KEY not in str(e.value)


def test_one_verified_item_sends_exactly_one_event(tmp_path: Path, stripe_env):
    rec = Recorder()
    _queue, journal, report = _writer(tmp_path, rec)
    report("g01", "written", "Léa Martin", "Très bon trimestre.")
    report("g01", "written", "Léa Martin", "Très bon trimestre.")  # repeated report: already recorded
    assert len(rec.requests) == 1
    assert rec.form()["identifier"] == "20261107-150000:g01"
    rows = journal.read()
    assert len(rows) == 1 and rows[0]["status"] == "verified" and rows[0]["billed"] is True


def test_mismatch_sends_nothing(tmp_path: Path, stripe_env):
    rec = Recorder()
    _queue, journal, report = _writer(tmp_path, rec)
    report("g01", "written", "Léa Martin", "Très bon trimestr.")
    assert rec.requests == []
    row = journal.read()[0]
    assert row["status"] == "mismatch" and row["billed"] is None


@pytest.mark.parametrize("missing", ["STRIPE_SECRET_KEY", "STRIPE_CUSTOMER_ID"])
def test_missing_env_sends_nothing(tmp_path: Path, stripe_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    rec = Recorder()
    _queue, journal, report = _writer(tmp_path, rec)
    report("g01", "written", "Léa Martin", "Très bon trimestre.")
    assert rec.requests == []
    row = journal.read()[0]
    assert row["status"] == "verified" and row["billed"] is None


def test_stripe_error_is_logged_and_keeps_the_status(tmp_path: Path, stripe_env, capsys):
    rec = Recorder({("POST", "/v1/billing/meter_events"): (500, {"error": {"message": "boom"}})})
    queue, journal, report = _writer(tmp_path, rec)
    reply = report("g01", "written", "Léa Martin", "Très bon trimestre.")
    assert "recorded as verified" in reply
    assert queue.get("g01").status == "verified"
    row = journal.read()[0]
    assert row["status"] == "verified" and row["billed"] is False and "not billed" in row["note"]
    err = capsys.readouterr().err
    assert "g01 not billed" in err and FAKE_KEY not in err
    assert FAKE_KEY not in json.dumps(journal.read())


def test_setup_creates_meter_and_customer(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_KEY)
    monkeypatch.delenv("STRIPE_CUSTOMER_ID", raising=False)
    rec = Recorder({
        ("GET", "/v1/billing/meters"): (200, {"data": []}),
        ("POST", "/v1/billing/meters"): (200, {"id": "mtr_1", "display_name": "Verified writes",
                                               "event_name": "verified_write"}),
        ("POST", "/v1/customers"): (200, {"id": "cus_new", "name": "Collège de démonstration"}),
    })
    assert stripe_setup.main([], client=rec.client()) == 0
    assert [(r.method, r.url.path) for r in rec.requests] == [
        ("GET", "/v1/billing/meters"), ("POST", "/v1/billing/meters"), ("POST", "/v1/customers")]
    assert rec.form(1) == {
        "display_name": "Verified writes", "event_name": "verified_write", "default_aggregation[formula]": "sum",
        "customer_mapping[event_payload_key]": "stripe_customer_id", "customer_mapping[type]": "by_id",
        "value_settings[event_payload_key]": "value"}
    assert rec.form(2) == {"name": "Collège de démonstration"}
    out = capsys.readouterr().out
    assert "export STRIPE_CUSTOMER_ID=cus_new" in out and FAKE_KEY not in out


EXISTING_METER = {"id": "mtr_1", "event_name": "verified_write", "default_aggregation": {"formula": "sum"},
                  "customer_mapping": {"event_payload_key": "stripe_customer_id", "type": "by_id"},
                  "value_settings": {"event_payload_key": "value"}}


def test_setup_reuses_existing_meter_and_customer(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_KEY)
    monkeypatch.setenv("STRIPE_CUSTOMER_ID", "cus_demo")
    rec = Recorder({
        ("GET", "/v1/billing/meters"): (200, {"data": [EXISTING_METER]}),
        ("GET", "/v1/customers/cus_demo"): (200, {"id": "cus_demo", "name": "Collège de démonstration"}),
    })
    assert stripe_setup.main([], client=rec.client()) == 0
    assert [r.method for r in rec.requests] == ["GET", "GET"]
    assert "export STRIPE_CUSTOMER_ID=cus_demo" in capsys.readouterr().out


def test_setup_without_key_sends_nothing(monkeypatch, capsys):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    rec = Recorder()
    assert stripe_setup.main([], client=rec.client()) == 2
    assert rec.requests == []
    assert "STRIPE_SECRET_KEY is not set" in capsys.readouterr().err


def test_setup_refuses_an_existing_meter_configured_differently(monkeypatch, capsys):
    monkeypatch.setenv("STRIPE_SECRET_KEY", FAKE_KEY)
    other = {**EXISTING_METER, "value_settings": {"event_payload_key": "count"}}
    rec = Recorder({("GET", "/v1/billing/meters"): (200, {"data": [other]})})
    assert stripe_setup.main([], client=rec.client()) == 2
    assert [r.method for r in rec.requests] == ["GET"]
    err = capsys.readouterr().err
    assert "configured differently" in err and "value_settings[event_payload_key]='count'" in err
