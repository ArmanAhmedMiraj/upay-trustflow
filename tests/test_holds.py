"""A 30-minute hold must keep the money safe, give it back on cancel, and never create or lose a taka."""
import random
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import database
import risk_hook
import security
import wallet_api
import wallet_service as svc
from models import SmsMessage, Transaction, User, utcnow
from wallet_helpers import make_engine, make_session

HOLD = risk_hook.RiskDecision("hold_30min", 96, "very_high", scam_type="return_by_mistake")
WARN = risk_hook.RiskDecision("warn_and_confirm", 40, "high")
ALLOW = risk_hook.RiskDecision()


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


def decide(monkeypatch, decision):
    monkeypatch.setattr(risk_hook, "check_transfer", lambda *a, **k: decision)


@pytest.fixture()
def db():
    return make_session()


@pytest.fixture()
def pair(db):
    a = svc.create_user(db, "01711000001", "Rahim", "12345", balance=10000)
    b = svc.create_user(db, "01711000002", "Karim", "12345")
    return a, b


def code_of(call, *a, **k):
    with pytest.raises(svc.WalletError) as e:
        call(*a, **k)
    return e.value.code


# ---------------------------------------------------------------- creating a hold
def test_a_hold_needs_the_customer_to_confirm_first(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, HOLD)
    assert code_of(svc.send_money, db, a, b.phone, 5000, "12345") == "risk_interruption"
    assert (a.balance, b.balance) == (10000, 0) and db.scalar(select(Transaction)) is None


def test_a_confirmed_hold_takes_money_from_the_sender_but_does_not_pay_the_recipient(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, HOLD)
    t = svc.send_money(db, a, b.phone, 5000, "12345", acknowledged_risk=True)
    assert t.status == "held" and (a.balance, b.balance) == (5000, 0)
    assert timedelta(minutes=29) < t.release_at - utcnow() <= timedelta(minutes=30)
    assert db.scalar(select(SmsMessage).where(SmsMessage.user_id == b.id)) is None       # no "money received" yet


def test_a_warning_without_confirmation_moves_nothing(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, WARN)
    assert code_of(svc.send_money, db, a, b.phone, 500, "12345") == "risk_interruption"
    t = svc.send_money(db, a, b.phone, 500, "12345", acknowledged_risk=True)
    assert t.status == "completed" and b.balance == 500


# ---------------------------------------------------------------- cancel
def test_cancelling_a_hold_returns_every_taka(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, HOLD)
    t = svc.send_money(db, a, b.phone, 5000, "12345", acknowledged_risk=True)
    svc.cancel_hold(db, a, t.id)
    assert t.status == "cancelled" and (a.balance, b.balance) == (10000, 0) and t.decided_at is not None


def test_only_the_sender_can_cancel_and_only_while_held(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, HOLD)
    t = svc.send_money(db, a, b.phone, 5000, "12345", acknowledged_risk=True)
    assert code_of(svc.cancel_hold, db, b, t.id) == "transaction_not_found"        # the recipient cannot cancel it
    svc.cancel_hold(db, a, t.id)
    assert code_of(svc.cancel_hold, db, a, t.id) == "not_cancellable"              # cannot cancel twice
    decide(monkeypatch, ALLOW)
    done = svc.send_money(db, a, b.phone, 100, "12345")
    assert code_of(svc.cancel_hold, db, a, done.id) == "not_cancellable"           # a completed payment is final
    assert code_of(svc.cancel_hold, db, a, 9999) == "transaction_not_found"


def test_a_held_amount_cannot_be_spent_twice(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, HOLD)
    svc.send_money(db, a, b.phone, 9000, "12345", acknowledged_risk=True)
    assert code_of(svc.send_money, db, a, b.phone, 2000, "12345", acknowledged_risk=True) == "insufficient_balance"


# ---------------------------------------------------------------- release when the time is up
def test_a_hold_is_released_to_the_recipient_when_time_is_up(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, HOLD)
    t = svc.send_money(db, a, b.phone, 5000, "12345", acknowledged_risk=True)
    assert svc.settle_due_holds(db, utcnow() + timedelta(minutes=10)) == 0            # too early
    assert (t.status, b.balance) == ("held", 0)
    assert svc.settle_due_holds(db, utcnow() + timedelta(minutes=31)) == 1
    db.refresh(b)
    assert (t.status, a.balance, b.balance) == ("completed", 5000, 5000)
    msg = db.scalar(select(SmsMessage).where(SmsMessage.user_id == b.id))
    assert msg.official and msg.claimed_amount == 5000 and a.phone in msg.text      # the true credit message appears now
    assert svc.settle_due_holds(db, utcnow() + timedelta(hours=2)) == 0              # never released twice
    assert b.balance == 5000


def test_a_release_that_would_overfill_the_recipient_goes_back_to_the_sender(db, pair, monkeypatch):
    a, b = pair
    decide(monkeypatch, HOLD)
    t = svc.send_money(db, a, b.phone, 5000, "12345", acknowledged_risk=True)
    b.balance = svc.MAX_BALANCE - 100
    db.commit()
    svc.settle_due_holds(db, utcnow() + timedelta(minutes=31))
    db.refresh(a)
    assert t.status == "rejected" and a.balance == 10000 and "limit" in t.review_note


# ---------------------------------------------------------------- analysts
def test_analysts_can_approve_or_reject_and_customers_cannot(db, pair, monkeypatch):
    a, b = pair
    analyst = svc.create_user(db, "01900000001", "Analyst Nadia", "99999", role="analyst")
    decide(monkeypatch, HOLD)
    t1 = svc.send_money(db, a, b.phone, 3000, "12345", acknowledged_risk=True)
    t2 = svc.send_money(db, a, b.phone, 2000, "12345", acknowledged_risk=True)
    assert code_of(svc.analyst_decide, db, a, t1.id, True) == "forbidden"            # a customer cannot decide cases
    svc.analyst_decide(db, analyst, t1.id, approve=True, note="Looks like a genuine rent payment")
    svc.analyst_decide(db, analyst, t2.id, approve=False, note="Recipient is a known mule")
    db.refresh(a)
    db.refresh(b)
    assert (t1.status, t2.status) == ("completed", "rejected") and (a.balance, b.balance) == (7000, 3000)
    assert t1.reviewed_by == analyst.id and t2.review_note == "Recipient is a known mule"
    assert code_of(svc.analyst_decide, db, analyst, t1.id, False) == "already_decided"


def test_the_case_list_shows_reasons_and_orders_by_risk(db, pair, monkeypatch):
    a, b = pair
    analyst = svc.create_user(db, "01900000001", "Analyst Nadia", "99999", role="analyst")
    decide(monkeypatch, risk_hook.RiskDecision("hold_30min", 70, "very_high", reasons=[{"source": "model", "text": "x"}]))
    svc.send_money(db, a, b.phone, 1000, "12345", acknowledged_risk=True)
    decide(monkeypatch, risk_hook.RiskDecision("hold_30min", 97, "very_high"))
    svc.send_money(db, a, b.phone, 2000, "12345", acknowledged_risk=True)
    cases = svc.analyst_cases(db)
    assert [c["risk_pct"] for c in cases] == [97, 70] and cases[0]["sender"]["name"] == "Rahim"


# ---------------------------------------------------------------- the money invariant, with holds
def test_no_taka_is_ever_created_or_lost_when_holds_cancels_and_reviews_are_mixed(db, monkeypatch):
    rng = random.Random(7)
    users = [svc.create_user(db, f"017110000{i:02d}", f"U{i}", "12345") for i in range(6)]
    analyst = svc.create_user(db, "01900000001", "Analyst", "99999", role="analyst")
    added = 0
    for u in users:
        svc.add_money(db, u, 40000)
        added += 40000
    monkeypatch.setattr(risk_hook, "check_transfer", lambda *a, **k: rng.choice([ALLOW, HOLD, HOLD, WARN]))
    clock = utcnow()
    for _ in range(300):
        u = rng.choice(users)
        op = rng.choice(["send", "send", "send", "cancel", "analyst", "time"])
        try:
            if op == "send":
                svc.send_money(db, u, rng.choice(users).phone, rng.randint(10, 9000), "12345", acknowledged_risk=True)
            elif op == "cancel":
                held = db.scalars(select(Transaction).where(Transaction.status == "held", Transaction.sender_id == u.id)).first()
                if held:
                    svc.cancel_hold(db, u, held.id)
            elif op == "analyst":
                held = db.scalars(select(Transaction).where(Transaction.status == "held")).first()
                if held:
                    svc.analyst_decide(db, analyst, held.id, approve=rng.random() < 0.5)
            else:
                clock += timedelta(minutes=rng.randint(5, 40))
                svc.settle_due_holds(db, clock)
        except svc.WalletError:
            pass
        for x in users:
            db.refresh(x)
            assert x.balance >= 0
        in_escrow = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.status == "held"))
        assert sum(x.balance for x in users) + in_escrow == added           # every taka is somewhere, always


# ---------------------------------------------------------------- over HTTP
@pytest.fixture()
def client():
    engine = make_engine()
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    wallet_api.app.dependency_overrides[database.get_db] = override
    with TestClient(wallet_api.app) as c:
        c.Session = Session
        yield c
    wallet_api.app.dependency_overrides.clear()


def token(client, phone, pin="12345"):
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]}


def test_hold_cancel_and_release_over_http(client, monkeypatch):
    d = client.Session()
    svc.create_user(d, "01711000001", "Rahim", "12345", balance=10000)
    svc.create_user(d, "01711000002", "Karim", "12345")
    d.close()
    decide(monkeypatch, HOLD)
    h = token(client, "01711000001")
    body = {"recipient_phone": "01711000002", "amount": 4000, "pin": "12345"}
    assert client.post("/wallet/send", headers=h, json=body).status_code == 409
    held = client.post("/wallet/send", headers=h, json={**body, "acknowledged_risk": True}).json()
    assert held["transaction"]["status"] == "held" and held["transaction"]["release_at"] and held["balance"] == 6000
    assert client.get("/wallet/transactions", headers=h).json()["transactions"][0]["release_at"]
    cancelled = client.post(f"/wallet/transactions/{held['transaction']['id']}/cancel", headers=h).json()
    assert cancelled["transaction"]["status"] == "cancelled" and cancelled["balance"] == 10000
    # a second hold, released instantly with the demo tool
    again = client.post("/wallet/send", headers=h, json={**body, "acknowledged_risk": True, "idempotency_key": "k2"}).json()
    assert client.post("/demo/release-holds-now", headers=h).json() == {"released": 1}
    assert client.get("/me", headers=h).json()["user"]["balance"] == 6000
    assert again["transaction"]["status"] == "held"


def test_analyst_endpoints_over_http(client, monkeypatch):
    d = client.Session()
    svc.create_user(d, "01711000001", "Rahim", "12345", balance=10000)
    svc.create_user(d, "01711000002", "Karim", "12345")
    svc.create_user(d, "01900000001", "Analyst Nadia", "99999", role="analyst")
    d.close()
    decide(monkeypatch, HOLD)
    cust, analyst = token(client, "01711000001"), token(client, "01900000001", "99999")
    t = client.post("/wallet/send", headers=cust, json={"recipient_phone": "01711000002", "amount": 4000, "pin": "12345",
                                                       "acknowledged_risk": True}).json()["transaction"]
    assert client.get("/analyst/cases", headers=cust).status_code == 403                    # customers are locked out
    assert client.get("/analyst/cases").status_code == 401
    cases = client.get("/analyst/cases", headers=analyst).json()["cases"]
    assert cases[0]["id"] == t["id"] and cases[0]["amount"] == 4000 and cases[0]["recipient"]["name"] == "Karim"
    r = client.post(f"/analyst/cases/{t['id']}/reject", headers=analyst, json={"note": "Known scam wallet"})
    assert r.json()["transaction"]["status"] == "rejected"
    assert client.get("/me", headers=cust).json()["user"]["balance"] == 10000                # refunded in full
    assert client.post(f"/analyst/cases/{t['id']}/approve", headers=analyst).status_code == 409


def test_malformed_replies_from_shield_are_treated_as_shield_being_unavailable(monkeypatch):
    import shield_client
    monkeypatch.setattr(shield_client, "_post", lambda path, payload: {"detail": "unexpected"})
    assert shield_client.assess({}) is None and shield_client.refine({}, []) is None
    monkeypatch.setattr(shield_client, "_post", lambda path, payload: ["not", "a", "dict"])
    assert shield_client.assess({}) is None


def test_tests_are_not_affected_by_settings_left_in_the_developers_terminal():
    """A leftover SHIELD_API_URL once made the whole suite crawl. conftest now clears it for every test."""
    import os
    assert os.getenv("SHIELD_API_URL") is None and os.getenv("HOLD_MINUTES") is None
