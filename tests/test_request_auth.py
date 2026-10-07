"""Shield only answers calls the wallet has signed (when SHIELD_API_SECRET is set)."""
import json
import pathlib
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
for folder in ("shield-api", "wallet-api"):
    sys.path.insert(0, str(ROOT / folder))

import request_auth  # noqa: E402
import shield_client  # noqa: E402

SECRET = "test-secret"


def make_app():
    app = FastAPI()
    app.add_middleware(request_auth.SignedRequests)

    @app.post("/risk/score")
    def score(payload: dict):
        return {"echo": payload}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def signed_headers(body: bytes, ts=None, secret=SECRET):
    ts = str(int(time.time())) if ts is None else ts
    return {"content-type": "application/json", "x-shield-timestamp": ts,
            "x-shield-signature": request_auth.sign(secret, ts, body)}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SHIELD_API_SECRET", SECRET)
    return TestClient(make_app())


def test_a_correctly_signed_call_is_answered(client):
    body = json.dumps({"amount": 5}).encode()
    r = client.post("/risk/score", content=body, headers=signed_headers(body))
    assert r.status_code == 200 and r.json() == {"echo": {"amount": 5}}


def test_an_unsigned_call_is_refused(client):
    assert client.post("/risk/score", json={"amount": 5}).status_code == 401


def test_a_wrong_secret_is_refused(client):
    body = b'{"amount": 5}'
    assert client.post("/risk/score", content=body, headers=signed_headers(body, secret="other")).status_code == 401


def test_a_changed_body_is_refused(client):
    headers = signed_headers(b'{"amount": 5}')
    assert client.post("/risk/score", content=b'{"amount": 9999}', headers=headers).status_code == 401


def test_an_old_signed_call_is_refused_as_a_replay(client):
    body = b'{"amount": 5}'
    old = str(int(time.time()) - 3600)
    assert client.post("/risk/score", content=body, headers=signed_headers(body, ts=old)).status_code == 401


def test_health_stays_open_without_a_signature(client):
    assert client.get("/health").status_code == 200


def test_with_no_secret_set_nothing_is_checked(monkeypatch):
    monkeypatch.delenv("SHIELD_API_SECRET", raising=False)
    assert TestClient(make_app()).post("/risk/score", json={"amount": 5}).status_code == 200


def test_the_wallet_signs_its_calls_so_shield_accepts_them(monkeypatch):
    """The wallet's real client talks to the protected app through a test transport."""
    monkeypatch.setenv("SHIELD_API_SECRET", SECRET)
    monkeypatch.setenv("SHIELD_API_URL", "http://shield.test")
    test_client = TestClient(make_app(), base_url="http://shield.test")
    monkeypatch.setattr(shield_client.httpx, "post", lambda url, **kw: test_client.post(url, **{k: v for k, v in kw.items() if k != "timeout"}))
    assert shield_client._post("/risk/score", {"amount": 7}) == {"echo": {"amount": 7}}


def test_the_wallet_sends_no_signature_when_no_secret_is_set(monkeypatch):
    monkeypatch.delenv("SHIELD_API_SECRET", raising=False)
    monkeypatch.setenv("SHIELD_API_URL", "http://shield.test")
    seen = {}

    class Reply:
        def raise_for_status(self): pass
        def json(self): return {}

    def fake_post(url, **kw):
        seen.update(kw)
        return Reply()

    monkeypatch.setattr(shield_client.httpx, "post", fake_post)
    shield_client._post("/risk/score", {"amount": 1})
    assert "x-shield-signature" not in {k.lower() for k in seen["headers"]}