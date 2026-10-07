"""More than one provider can use Shield: own secret, own field names, nothing shared between them."""
import json
import pathlib
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
for folder in ("shield-api", "wallet-api"):
    sys.path.insert(0, str(ROOT / folder))

import request_auth  # noqa: E402
import shield_api  # noqa: E402

TENANTS = {"upay": {"secret": "upay-secret", "adapter": "upay"}, "demo-mfs": {"secret": "mfs-secret", "adapter": "demo-mfs"}}

NATIVE = dict(amount_zscore=1.2, balance_share=0.8, is_first_time_recipient=1, is_round_amount=1, hour_unusual=0.9,
              log_mins_since_incoming=2.0, hesitation_secs=40.0, amount_edits=2, on_call=1, sender_history_count=12,
              recipient_age_days=3.0, first_time_senders_24h=9, recipient_inflow_count_24h=11, recipient_outflow_ratio_24h=0.9,
              recipient_prior_txns=4, report_count=2, report_rate=0.1, sms_claims_credit=0, sms_mentions_recipient=0,
              ledger_confirms_credit=0, claim_ledger_mismatch=0, claim_mismatch_on_recipient=0, sms_official_sender=0)
# the same transfer, as the invented provider "demo-mfs" would send it: other names, other units
THEIRS = dict(amt_z=1.2, pct_of_balance=80, new_payee="Y", round_amt="Y", odd_hour=0.9, mins_since_credit=7.38905609893065,
              pause_ms=40000, edits=2, on_call="Y", history=12, payee_age_days=3.0, payee_new_senders_24h=9, payee_inflows_24h=11,
              payee_outflow_ratio=0.9, payee_prior_txns=4, payee_reports=2, payee_report_rate=0.1)


def call(client, path, payload, tenant, secret):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    h = {"content-type": "application/json", "x-shield-timestamp": ts, "x-shield-signature": request_auth.sign(secret, ts, body)}
    if tenant:
        h["x-shield-tenant"] = tenant
    return client.post(path, content=body, headers=h)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SHIELD_TENANTS", json.dumps(TENANTS))
    monkeypatch.delenv("SHIELD_API_SECRET", raising=False)
    with TestClient(shield_api.app) as c:
        yield c


def test_a_second_provider_with_its_own_field_names_gets_the_same_score(client):
    ours = call(client, "/risk/score", NATIVE, "upay", "upay-secret")
    theirs = call(client, "/risk/score-adapted", THEIRS, "demo-mfs", "mfs-secret")
    assert ours.status_code == 200 and theirs.status_code == 200
    assert theirs.json()["risk_pct"] == ours.json()["risk_pct"]
    assert theirs.json()["tier"] == ours.json()["tier"]


def test_one_provider_cannot_sign_as_another(client):
    assert call(client, "/risk/score-adapted", THEIRS, "demo-mfs", "upay-secret").status_code == 401
    assert call(client, "/risk/score", NATIVE, "upay", "mfs-secret").status_code == 401


def test_an_unknown_provider_is_refused(client):
    assert call(client, "/risk/score", NATIVE, "nobody", "upay-secret").status_code == 401


def test_a_call_without_a_tenant_is_treated_as_upay(client):
    assert call(client, "/risk/score", NATIVE, None, "upay-secret").status_code == 200
    assert call(client, "/risk/score", NATIVE, None, "mfs-secret").status_code == 401


def test_a_request_the_adapter_cannot_read_is_a_clear_422(client):
    bad = {k: v for k, v in THEIRS.items() if k != "pause_ms"}
    r = call(client, "/risk/score-adapted", bad, "demo-mfs", "mfs-secret")
    assert r.status_code == 422 and "pause_ms" in r.json()["detail"]


def test_without_tenants_configured_shield_behaves_as_before(monkeypatch):
    monkeypatch.delenv("SHIELD_TENANTS", raising=False)
    monkeypatch.delenv("SHIELD_API_SECRET", raising=False)
    with TestClient(shield_api.app) as c:
        assert c.post("/risk/score", json=NATIVE).status_code == 200
        assert c.post("/risk/score-adapted", json=NATIVE).status_code == 200      # upay adapter is a pass-through
    monkeypatch.setenv("SHIELD_API_SECRET", "legacy")
    with TestClient(shield_api.app) as c:
        assert c.post("/risk/score", json=NATIVE).status_code == 401
        assert call(c, "/risk/score", NATIVE, None, "legacy").status_code == 200
