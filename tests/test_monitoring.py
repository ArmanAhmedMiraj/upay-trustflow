"""Monitoring: counters, latency, decision counts, and a readiness check that tells the truth."""
import pathlib
import sys

from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
for folder in ("shield-api", "wallet-api"):
    sys.path.insert(0, str(ROOT / folder))

import metrics  # noqa: E402
import shield_api  # noqa: E402
import wallet_api  # noqa: E402

from test_tenants import NATIVE  # noqa: E402


def test_shield_counts_requests_and_decisions_by_tier(monkeypatch):
    monkeypatch.delenv("SHIELD_TENANTS", raising=False)
    monkeypatch.delenv("SHIELD_API_SECRET", raising=False)
    with TestClient(shield_api.app) as c:
        assert c.post("/risk/score", json=NATIVE).status_code == 200
        assert c.post("/risk/score", json={"bad": 1}).status_code == 422
        text = c.get("/metrics").text
    assert 'shield_requests_total{method="POST",route="/risk/score",status="200"}' in text
    assert 'shield_requests_total{method="POST",route="/risk/score",status="422"}' in text
    assert "shield_decisions_total{label=" in text
    assert 'shield_request_seconds_bucket{route="/risk/score",le="+Inf"}' in text
    assert "customer" not in text and "phone" not in text          # counters only, never customer data


def test_shield_is_ready_only_when_the_model_is_loaded(monkeypatch):
    monkeypatch.delenv("SHIELD_TENANTS", raising=False)
    monkeypatch.delenv("SHIELD_API_SECRET", raising=False)
    with TestClient(shield_api.app) as c:
        assert c.get("/ready").status_code == 200
        art = shield_api.app.state.artifacts
        shield_api.app.state.artifacts = None
        try:
            r = c.get("/ready")
            assert r.status_code == 503 and r.json()["ready"] is False
            assert c.get("/health").json()["status"] == "degraded"
        finally:
            shield_api.app.state.artifacts = art


def test_metrics_and_ready_stay_open_when_calls_must_be_signed(monkeypatch):
    monkeypatch.setenv("SHIELD_API_SECRET", "s")
    with TestClient(shield_api.app) as c:
        assert c.get("/metrics").status_code == 200
        assert c.get("/ready").status_code == 200
        assert c.post("/risk/score", json=NATIVE).status_code == 401


def test_wallet_reports_ready_and_counts_requests():
    c = TestClient(wallet_api.app)
    assert c.get("/health").status_code == 200
    assert c.get("/ready").json() == {"ready": True}
    assert 'wallet_requests_total{method="GET",route="/health",status="200"}' in c.get("/metrics").text


def test_the_registry_buckets_latency():
    reg = metrics.Registry("t")
    reg.observe("GET", "/x", 200, 0.004)
    reg.observe("GET", "/x", 200, 5.0)
    text = reg.render()
    assert 't_request_seconds_bucket{route="/x",le="0.005"} 1' in text
    assert 't_request_seconds_bucket{route="/x",le="+Inf"} 2' in text
