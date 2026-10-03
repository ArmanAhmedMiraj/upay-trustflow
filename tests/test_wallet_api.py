import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import database
import security
import wallet_api
import wallet_service as svc
from wallet_helpers import make_engine


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture()
def client():
    engine = make_engine()
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    wallet_api.app.dependency_overrides[database.get_db] = override
    with TestClient(wallet_api.app) as c:
        c.session_factory = Session
        yield c
    wallet_api.app.dependency_overrides.clear()


def signup(client, phone, name, pin="12345"):
    assert client.post("/auth/register", json={"phone": phone, "name": name, "pin": pin}).status_code == 201
    token = client.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_full_customer_journey(client):
    rahim = signup(client, "01711000001", "Rahim")
    signup(client, "01711000002", "Karim")
    assert client.post("/wallet/add-money", json={"amount": 10000}, headers=rahim).json()["balance"] == 10000
    sent = client.post("/wallet/send", headers=rahim, json={
        "recipient_phone": "01711000002", "amount": 2500, "pin": "12345",
        "behavior": {"hesitation_secs": 8.5, "amount_edits": 0, "on_call": False}}).json()
    assert sent["balance"] == 7500 and sent["transaction"]["kind"] == "send_money"
    hist = client.get("/wallet/transactions", headers=rahim).json()["transactions"]
    assert [h["kind"] for h in hist] == ["send_money", "add_money"]
    assert client.get("/me", headers=rahim).json()["user"]["balance"] == 7500


def test_pin_never_appears_in_any_response(client):
    h = signup(client, "01711000001", "Rahim", "13579")
    for resp in (client.get("/me", headers=h), client.get("/wallet/transactions", headers=h)):
        assert "13579" not in resp.text and "pin_hash" not in resp.text


def test_protected_routes_need_a_valid_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.post("/wallet/send", json={"recipient_phone": "01711000002", "amount": 100, "pin": "12345"}).status_code == 401


def test_logout_ends_the_session(client):
    h = signup(client, "01711000001", "Rahim")
    client.post("/auth/logout", headers=h)
    assert client.get("/me", headers=h).status_code == 401


def test_wrong_pin_is_401_and_repeated_wrong_pins_lock_with_423(client):
    signup(client, "01711000001", "Rahim")
    for _ in range(svc.MAX_PIN_ATTEMPTS):
        assert client.post("/auth/login", json={"phone": "01711000001", "pin": "00000"}).status_code == 401
    r = client.post("/auth/login", json={"phone": "01711000001", "pin": "12345"})
    assert r.status_code == 423 and r.json()["code"] == "account_locked"


def test_errors_use_one_clear_shape(client):
    h = signup(client, "01711000001", "Rahim")
    r = client.post("/wallet/send", headers=h, json={"recipient_phone": "01799999999", "amount": 100, "pin": "12345"})
    assert r.status_code == 404 and set(r.json()) == {"code", "detail"}


def test_insufficient_balance_and_bad_input(client):
    h = signup(client, "01711000001", "Rahim")
    signup(client, "01711000002", "Karim")
    r = client.post("/wallet/send", headers=h, json={"recipient_phone": "01711000002", "amount": 500, "pin": "12345"})
    assert r.status_code == 400 and r.json()["code"] == "insufficient_balance"
    assert client.post("/wallet/send", headers=h, json={"recipient_phone": "01711000002", "amount": "lots", "pin": "12345"}).status_code == 422
    assert client.post("/auth/register", json={"phone": "123", "name": "X", "pin": "12345"}).status_code == 400


def test_double_tap_with_the_same_key_moves_money_once(client):
    h = signup(client, "01711000001", "Rahim")
    signup(client, "01711000002", "Karim")
    client.post("/wallet/add-money", json={"amount": 5000}, headers=h)
    body = {"recipient_phone": "01711000002", "amount": 1000, "pin": "12345", "idempotency_key": "abc"}
    a = client.post("/wallet/send", headers=h, json=body).json()
    b = client.post("/wallet/send", headers=h, json=body).json()
    assert a["transaction"]["id"] == b["transaction"]["id"] and b["balance"] == 4000


def test_cash_out_to_an_agent(client):
    h = signup(client, "01711000001", "Rahim")
    db = client.session_factory()
    svc.create_user(db, "01811000009", "Agent Babul", "11111", role="agent")
    db.close()
    client.post("/wallet/add-money", json={"amount": 5000}, headers=h)
    r = client.post("/wallet/cash-out", headers=h, json={"agent_phone": "01811000009", "amount": 2000, "pin": "12345"})
    assert r.status_code == 200 and r.json()["balance"] == 3000


def test_a_risk_interruption_returns_409_with_the_decision_and_moves_no_money(client, monkeypatch):
    import risk_hook
    h = signup(client, "01711000001", "Rahim")
    signup(client, "01711000002", "Karim")
    client.post("/wallet/add-money", json={"amount": 5000}, headers=h)
    monkeypatch.setattr(risk_hook, "check_transfer", lambda *a, **k: risk_hook.RiskDecision("hold_30min", 96, "very_high"))
    r = client.post("/wallet/send", headers=h, json={"recipient_phone": "01711000002", "amount": 3000, "pin": "12345"})
    assert r.status_code == 409 and r.json()["risk"] == {"action": "hold_30min", "risk_pct": 96, "tier": "very_high"}
    assert client.get("/me", headers=h).json()["user"]["balance"] == 5000
