"""The Risk Lab routes in the wallet: analysts only, Shield-backed, and honest when Shield is off."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import database
import security
import shield_client
import wallet_api
import wallet_service as svc
from wallet_helpers import make_engine


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture()
def client():
    Session = sessionmaker(bind=make_engine(), autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    wallet_api.app.dependency_overrides[database.get_db] = override
    with TestClient(wallet_api.app) as c:
        db = Session()
        svc.create_user(db, "01900000001", "Analyst Nadia", "99999", role="analyst")
        db.close()
        yield c
    wallet_api.app.dependency_overrides.clear()


def login(client, phone, pin):
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]}


def customer(client):
    client.post("/auth/register", json={"phone": "01711000001", "name": "Rahim", "pin": "12345"})
    return login(client, "01711000001", "12345")


def test_customers_cannot_open_the_lab(client):
    h = customer(client)
    assert client.get("/lab/accounts", headers=h).status_code == 403
    assert client.post("/lab/score", headers=h, json={"sender_id": "rahim", "recipient_id": "mother"}).status_code == 403
    assert client.get("/lab/accounts").status_code == 401


def test_analyst_calls_are_passed_to_shield(client, monkeypatch):
    seen = []
    monkeypatch.setattr(shield_client, "lab_call", lambda m, p, payload=None: seen.append((m, p, payload)) or {"ok": True})
    h = login(client, "01900000001", "99999")
    assert client.get("/lab/accounts", headers=h).json() == {"ok": True}
    assert client.get("/lab/catalogue", headers=h).status_code == 200 and client.get("/lab/report", headers=h).status_code == 200
    r = client.post("/lab/score", headers=h, json={"sender_id": "rahim", "recipient_id": "mother", "tx": {"amount": 1000}, "mute_sides": ["pair"]})
    assert r.status_code == 200
    assert seen[0] == ("GET", "/risk/graded/accounts", None)
    assert seen[-1][:2] == ("POST", "/risk/graded") and seen[-1][2]["mute_sides"] == ["pair"]


def test_lab_says_so_plainly_when_shield_is_off(client):
    h = login(client, "01900000001", "99999")      # SHIELD_API_URL is not set in tests
    r = client.get("/lab/accounts", headers=h)
    assert r.status_code == 503 and r.json()["code"] == "shield_unavailable"


def test_lab_calls_are_signed_like_payment_checks(monkeypatch):
    monkeypatch.setenv("SHIELD_API_SECRET", "s3cret")
    headers = shield_client._signed_headers(b'{"a":1}')
    assert {"X-Shield-Timestamp", "X-Shield-Signature"} <= set(headers)
    monkeypatch.delenv("SHIELD_API_SECRET")
    assert "X-Shield-Signature" not in shield_client._signed_headers(b"")


def test_lab_end_to_end_through_a_signing_shield(monkeypatch):
    """The wallet client, the signature check and the graded model together."""
    import httpx
    import shield_api
    monkeypatch.setenv("SHIELD_API_URL", "http://shield.test")
    monkeypatch.setenv("SHIELD_API_SECRET", "s3cret")
    with TestClient(shield_api.app) as shield:
        def fake_request(method, url, content=None, headers=None, timeout=None):
            r = shield.request(method, url.replace("http://shield.test", ""), content=content, headers=headers)
            return httpx.Response(r.status_code, json=r.json(), request=httpx.Request(method, url))
        monkeypatch.setattr(httpx, "request", fake_request)
        out = shield_client.lab_call("POST", "/risk/graded", {"sender_id": "rahim", "recipient_id": "mother", "tx": {"amount": 1000}})
        assert out["tier"] == "low" and len(out["contributions"]) == 31
        assert shield_client.lab_call("GET", "/risk/graded/catalogue")["signals"]
