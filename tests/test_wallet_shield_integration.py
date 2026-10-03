"""The wallet and Shield working together, end to end, in one process (no network needed)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import database
import scorer
import security
import shield_api
import shield_client
import wallet_api
import wallet_service as svc
from models import Report, RiskEvent, SmsMessage, Transaction, User, utcnow
from wallet_helpers import make_engine

pytestmark = pytest.mark.skipif(not (scorer.ARTIFACT_DIR / "model.txt").exists(), reason="run train.py first")


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture()
def world(monkeypatch):
    """A wallet database plus a running Shield, connected the way the real services are."""
    engine = make_engine()
    Session = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    wallet_api.app.dependency_overrides[database.get_db] = override
    with TestClient(shield_api.app) as shield, TestClient(wallet_api.app) as wallet:
        def to_shield(path, payload):
            response = shield.post(path, json=payload)
            response.raise_for_status()          # like the real call: an error status is an error
            return response.json()

        monkeypatch.setattr(shield_client, "_post", to_shield)
        wallet.Session, wallet.shield = Session, shield
        yield wallet
    wallet_api.app.dependency_overrides.clear()


def person(db, phone, name, pin="12345", created_days_ago=400, balance=0, role="customer"):
    u = svc.create_user(db, phone, name, pin, role=role, balance=balance)
    u.created_at = utcnow() - timedelta(days=created_days_ago)
    db.commit()
    return u


def login(wallet, phone, pin="12345"):
    return {"Authorization": "Bearer " + wallet.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]}


def give_history(db, sender, recipient, n=25):
    """Make `sender` an established customer who regularly pays `recipient` about 800 taka."""
    usual = [350, 1200, 800, 2500, 500, 1500, 900, 650, 1800, 400]      # a realistic spread, not one fixed amount
    for i in range(n):
        db.add(Transaction(kind="send_money", sender_id=sender.id, receiver_id=recipient.id, amount=usual[i % len(usual)],
                           created_at=utcnow() - timedelta(days=40 - i)))
    db.commit()


def make_scam_wallet(db, victims=10, reports=0, phone="01711999999"):
    """A 3-day-old wallet that collects first payments from strangers and cashes out fast."""
    scam = person(db, phone, "Fraudster", created_days_ago=3)
    agent = db.query(User).filter_by(role="agent").first() or person(db, "01811000009", "Agent", role="agent")
    for i in range(victims):
        payer = person(db, f"017115{i:05d}", f"Payer{i}")
        db.add(Transaction(kind="send_money", sender_id=payer.id, receiver_id=scam.id, amount=3000,
                           created_at=utcnow() - timedelta(hours=6 - i * 0.4)))
    db.add(Transaction(kind="cash_out", sender_id=scam.id, receiver_id=agent.id, amount=victims * 2800,
                       created_at=utcnow() - timedelta(minutes=45)))
    for i in range(reports):
        reporter = person(db, f"017116{i:05d}", f"Reporter{i}")
        db.add(Report(reporter_id=reporter.id, reported_id=scam.id, created_at=utcnow() - timedelta(hours=1)))
    db.commit()
    return scam


def setup_victim(wallet):
    db = wallet.Session()
    rahim = person(db, "01711000001", "Rahim", balance=30000)
    mum = person(db, "01711000002", "Mum")
    give_history(db, rahim, mum)
    return db, rahim, mum


# ---------------------------------------------------------------- everyday life must be untouched
def test_a_normal_transfer_to_a_known_person_goes_straight_through(world):
    db, rahim, mum = setup_victim(world)
    h = login(world, rahim.phone)
    prev = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": mum.phone, "amount": 800}).json()["risk"]
    assert prev["shield_available"] and prev["action"] == "allow" and prev["risk_pct"] < 10
    r = world.post("/wallet/send", headers=h, json={"recipient_phone": mum.phone, "amount": 800, "pin": "12345"})
    assert r.status_code == 200 and r.json()["balance"] == 29200
    assert r.json()["transaction"]["risk_tier"] == "low"


# ---------------------------------------------------------------- the headline demo
def test_the_fake_money_received_scam_is_held_and_no_money_moves(world):
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db)
    h = login(world, rahim.phone)
    assert world.post("/demo/fake-sms", headers=h, json={"amount": 5000, "from_number": scam.phone}).status_code == 200
    body = {"recipient_phone": scam.phone, "amount": 5000, "pin": "12345",
            "behavior": {"hesitation_secs": 25, "amount_edits": 1, "on_call": True}}
    r = world.post("/wallet/send", headers=h, json=body)
    risk = r.json()["risk"]
    assert r.status_code == 409 and risk["action"] == "hold_30min" and risk["risk_pct"] >= 90
    assert risk["reasons"][0]["source"] == "rule" and "ledger" in risk["reasons"][0]["text"]
    assert "৩০ মিনিট" in risk["message_bn"] and risk["scam_type"] == "return_by_mistake"
    me = world.get("/me", headers=h).json()["user"]
    assert me["balance"] == 30000                                           # not one taka moved
    assert db.query(Transaction).filter_by(sender_id=rahim.id, receiver_id=scam.id).count() == 0


def test_the_preview_shows_the_same_risk_without_asking_for_a_pin(world):
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db)
    h = login(world, rahim.phone)
    world.post("/demo/fake-sms", headers=h, json={"amount": 5000, "from_number": scam.phone})
    prev = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": scam.phone, "amount": 5000,
                      "behavior": {"on_call": True}}).json()
    assert prev["risk"]["risk_pct"] >= 90 and prev["recipient"]["name"] == "Fraudster"
    assert world.get("/me", headers=h).json()["user"]["balance"] == 30000


def test_a_genuine_first_payment_to_a_new_shop_is_not_stopped(world):
    db, rahim, mum = setup_victim(world)
    shop = person(db, "01711777777", "Old Shop", created_days_ago=700)
    h = login(world, rahim.phone)
    r = world.post("/wallet/send", headers=h, json={"recipient_phone": shop.phone, "amount": 1200, "pin": "12345"})
    assert r.status_code == 200


# ---------------------------------------------------------------- network learning
def test_after_victims_report_the_next_person_sees_a_higher_risk(world):
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db, victims=4)
    h = login(world, rahim.phone)
    ask = lambda: world.post("/wallet/send/preview", headers=h, json={"recipient_phone": scam.phone, "amount": 3000}).json()["risk"]["risk_pct"]  # noqa: E731
    before = ask()
    for i in range(3):
        db.add(Report(reporter_id=person(db, f"017117{i:05d}", f"R{i}").id, reported_id=scam.id, created_at=utcnow() - timedelta(minutes=30)))
    db.commit()
    assert ask() > before


def test_reporting_a_number_has_sensible_limits(world):
    db, rahim, mum = setup_victim(world)
    h = login(world, rahim.phone)
    assert world.post("/wallet/report", headers=h, json={"phone": mum.phone, "reason": "scam call"}).status_code == 200
    assert world.post("/wallet/report", headers=h, json={"phone": mum.phone}).status_code == 409        # no report-bombing
    assert world.post("/wallet/report", headers=h, json={"phone": rahim.phone}).status_code == 400      # not yourself
    assert world.post("/wallet/report", headers=h, json={"phone": "01799999999"}).status_code == 404


# ---------------------------------------------------------------- the customer can still choose (safety-check tier)
def test_a_safety_check_warning_lets_the_customer_continue_after_acknowledging(world):
    db, rahim, mum = setup_victim(world)
    seller = person(db, "01711555555", "Online Seller", created_days_ago=60)      # a young wallet with only two past payers
    for i in range(2):
        payer = person(db, f"017113{i:05d}", f"Past{i}")
        db.add(Transaction(kind="send_money", sender_id=payer.id, receiver_id=seller.id, amount=2000,
                           created_at=utcnow() - timedelta(days=30 + i)))
    db.commit()
    h = login(world, rahim.phone)
    body = {"recipient_phone": seller.phone, "amount": 4000, "pin": "12345"}
    first = world.post("/wallet/send", headers=h, json=body)
    risk = first.json()["risk"]
    assert first.status_code == 409 and risk["action"] == "safety_check" and 30 <= risk["risk_pct"] < 60
    assert len(risk["questions"]) == 2 and risk["message_bn"]
    assert world.get("/me", headers=h).json()["user"]["balance"] == 30000          # nothing moved yet
    second = world.post("/wallet/send", headers=h, json={**body, "acknowledged_risk": True})
    assert second.status_code == 200 and second.json()["transaction"]["risk_tier"] == "high"
    assert second.json()["balance"] == 26000


def test_a_brand_new_wallet_with_no_history_is_treated_with_suspicion(world):
    """Known behaviour, documented: in our data, honest wallets nearly always have some history."""
    db, rahim, mum = setup_victim(world)
    ghost = person(db, "01711666666", "Nobody Yet", created_days_ago=60)
    h = login(world, rahim.phone)
    prev = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": ghost.phone, "amount": 1000}).json()["risk"]
    assert prev["action"] in ("safety_check", "hold_30min")


# ---------------------------------------------------------------- Shield problems never stop the wallet
def test_if_shield_is_down_the_transfer_still_works_and_says_so(world, monkeypatch):
    db, rahim, mum = setup_victim(world)
    h = login(world, rahim.phone)

    def down(path, payload):
        raise ConnectionError("Shield is down")
    monkeypatch.setattr(shield_client, "_post", down)
    prev = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": mum.phone, "amount": 800}).json()["risk"]
    assert prev["shield_available"] is False and prev["action"] == "allow"
    assert world.post("/wallet/send", headers=h, json={"recipient_phone": mum.phone, "amount": 800, "pin": "12345"}).status_code == 200


def test_shield_switched_off_by_configuration_means_allow(world, monkeypatch):
    monkeypatch.undo()                                                    # remove the in-process connection
    monkeypatch.delenv("SHIELD_API_URL", raising=False)
    db, rahim, mum = setup_victim(world)
    h = login(world, rahim.phone)
    assert world.post("/wallet/send", headers=h, json={"recipient_phone": mum.phone, "amount": 800, "pin": "12345"}).status_code == 200


# ---------------------------------------------------------------- records and inbox
def test_every_assessment_is_recorded_and_linked_to_its_transfer(world):
    db, rahim, mum = setup_victim(world)
    h = login(world, rahim.phone)
    world.post("/wallet/send/preview", headers=h, json={"recipient_phone": mum.phone, "amount": 800})
    r = world.post("/wallet/send", headers=h, json={"recipient_phone": mum.phone, "amount": 800, "pin": "12345"})
    events = db.query(RiskEvent).order_by(RiskEvent.id).all()
    assert [e.source for e in events] == ["preview", "send"]
    assert events[1].transaction_id == r.json()["transaction"]["id"] and events[1].transaction_id is not None


def test_the_receiver_gets_a_true_official_credit_message(world):
    db, rahim, mum = setup_victim(world)
    world.post("/wallet/send", headers=login(world, rahim.phone), json={"recipient_phone": mum.phone, "amount": 800, "pin": "12345"})
    msgs = world.get("/sms/inbox", headers=login(world, mum.phone)).json()["messages"]
    assert msgs[0]["from"] == "upay" and msgs[0]["official"] is True and "800" in msgs[0]["text"] and rahim.phone in msgs[0]["text"]


def test_demo_tools_can_be_switched_off(world, monkeypatch):
    db, rahim, mum = setup_victim(world)
    monkeypatch.setattr(wallet_api, "DEMO_MODE", False)
    r = world.post("/demo/fake-sms", headers=login(world, rahim.phone), json={"amount": 5000, "from_number": mum.phone})
    assert r.status_code == 404
