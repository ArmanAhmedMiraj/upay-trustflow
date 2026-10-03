"""The Shield API must score correctly, reject bad input, and fail safely."""
import pytest
from fastapi.testclient import TestClient

import scorer
import shield_api
from features import FEATURES
from test_single_signal import BASE

pytestmark = pytest.mark.skipif(not (scorer.ARTIFACT_DIR / "model.txt").exists(), reason="run train.py first")

FAKE_CREDIT_SMS = dict(BASE, is_first_time_recipient=1, sms_claims_credit=1, sms_mentions_recipient=1,
                       claim_ledger_mismatch=1, claim_mismatch_on_recipient=1, recipient_age_days=3.0,
                       first_time_senders_24h=11)


@pytest.fixture(scope="module")
def client():
    with TestClient(shield_api.app) as c:
        yield c


def test_health_reports_a_loaded_model(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["model_loaded"] is True
    assert body["feature_count"] == len(FEATURES)
    assert body["tier_thresholds"]["note"] < body["tier_thresholds"]["high"] < body["tier_thresholds"]["very_high"]


def test_api_accepts_exactly_the_features_the_model_uses():
    assert set(shield_api.TransferFeatures.model_fields) == set(FEATURES)


def test_ordinary_transfer_passes_silently(client):
    out = client.post("/risk/score", json=BASE).json()
    assert out["tier"] == "low" and out["action"] == "allow" and out["reasons"] == []


def test_fake_credit_sms_is_held_with_a_rule_reason_first(client):
    out = client.post("/risk/score", json=FAKE_CREDIT_SMS).json()
    assert out["tier"] == "very_high" and out["action"] == "hold_30min"
    assert out["risk_pct"] >= 90
    assert out["reasons"][0]["source"] == "rule"
    assert out["scam_type"] == "return_by_mistake"


def test_api_matches_the_scorer_exactly(client):
    direct = scorer.score_transfer(FAKE_CREDIT_SMS, shield_api.app.state.artifacts)
    over_http = client.post("/risk/score", json=FAKE_CREDIT_SMS).json()
    assert over_http["risk_pct"] == direct["risk_pct"] and over_http["tier"] == direct["tier"]


def test_scoring_is_fast(client):
    assert client.post("/risk/score", json=BASE).json()["latency_ms"] < 200


def test_missing_field_is_rejected(client):
    bad = {k: v for k, v in BASE.items() if k != "on_call"}
    assert client.post("/risk/score", json=bad).status_code == 422


def test_impossible_values_are_rejected(client):
    assert client.post("/risk/score", json=dict(BASE, balance_share=1.7)).status_code == 422
    assert client.post("/risk/score", json=dict(BASE, on_call=2)).status_code == 422
    assert client.post("/risk/score", json=dict(BASE, hesitation_secs=-5)).status_code == 422


def test_shield_fails_safely_when_the_model_is_missing(monkeypatch):
    def broken(*a, **k):
        raise FileNotFoundError("model.txt not found")
    monkeypatch.setattr(scorer, "load_artifacts", broken)
    with TestClient(shield_api.app) as c:
        assert c.get("/health").json()["status"] == "degraded"
        assert c.post("/risk/score", json=BASE).status_code == 503   # wallet then falls back to "allow"
