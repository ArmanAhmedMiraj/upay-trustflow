"""The complete story, wallet and Shield together: warning, questions, hold, cancel, review."""
from datetime import timedelta

import pytest

import risk_features as rf
import scorer
import security
import wallet_service as svc
from models import Report, Transaction, User, utcnow
from test_wallet_shield_integration import (give_history, login, make_scam_wallet, person, setup_victim,  # noqa: F401
                                            world)

pytestmark = pytest.mark.skipif(not (scorer.ARTIFACT_DIR / "model.txt").exists(), reason="run train.py first")


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


def young_seller(db):
    """A 60-day-old wallet with two past payers: a transfer of 4000 to it lands in the safety-check tier."""
    seller = person(db, "01711555555", "Online Seller", created_days_ago=60)
    for i in range(2):
        payer = person(db, f"017113{i:05d}", f"Past{i}")
        db.add(Transaction(kind="send_money", sender_id=payer.id, receiver_id=seller.id, amount=2000,
                           created_at=utcnow() - timedelta(days=30 + i)))
    db.commit()
    return seller


def question_ids(world, h, phone, amount, behavior=None):
    risk = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": phone, "amount": amount,
                      "behavior": behavior or {}}).json()["risk"]
    return risk, [q["id"] for q in risk["questions"]]


# ---------------------------------------------------------------- the headline story
def test_victim_is_warned_confirms_gets_held_then_cancels_and_gets_everything_back(world):
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db)
    h = login(world, rahim.phone)
    world.post("/demo/fake-sms", headers=h, json={"amount": 5000, "from_number": scam.phone})
    body = {"recipient_phone": scam.phone, "amount": 5000, "pin": "12345", "behavior": {"on_call": True, "hesitation_secs": 25}}

    warned = world.post("/wallet/send", headers=h, json=body)
    assert warned.status_code == 409 and warned.json()["risk"]["action"] == "hold_30min"
    held = world.post("/wallet/send", headers=h, json={**body, "acknowledged_risk": True}).json()
    assert held["transaction"]["status"] == "held" and held["balance"] == 25000
    assert db.query(User).filter_by(phone=scam.phone).one().balance == 0                  # the fraudster got nothing

    cancelled = world.post(f"/wallet/transactions/{held['transaction']['id']}/cancel", headers=h).json()
    assert cancelled["balance"] == 30000 and cancelled["transaction"]["status"] == "cancelled"


def test_an_analyst_sees_the_case_with_the_reason_and_can_reject_it(world):
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db)
    person(db, "01900000001", "Analyst Nadia", pin="99999", role="analyst")
    h = login(world, rahim.phone)
    world.post("/demo/fake-sms", headers=h, json={"amount": 5000, "from_number": scam.phone})
    t = world.post("/wallet/send", headers=h, json={"recipient_phone": scam.phone, "amount": 5000, "pin": "12345",
                   "acknowledged_risk": True, "behavior": {"on_call": True}}).json()["transaction"]
    a = login(world, "01900000001", "99999")
    case = world.get("/analyst/cases", headers=a).json()["cases"][0]
    assert case["id"] == t["id"] and case["risk_pct"] >= 90 and case["scam_type"] == "return_by_mistake"
    assert any(r["source"] == "rule" and "ledger" in r["text"] for r in case["reasons"])
    world.post(f"/analyst/cases/{t['id']}/reject", headers=a, json={"note": "Fake credit SMS, fraud wallet"})
    assert world.get("/me", headers=h).json()["user"]["balance"] == 30000


def test_an_unanswered_hold_is_released_when_the_time_is_up(world):
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db)
    h = login(world, rahim.phone)
    world.post("/demo/fake-sms", headers=h, json={"amount": 3000, "from_number": scam.phone})
    world.post("/wallet/send", headers=h, json={"recipient_phone": scam.phone, "amount": 3000, "pin": "12345", "acknowledged_risk": True})
    assert db.query(Transaction).filter_by(status="held").count() == 1
    svc.settle_due_holds(db, utcnow() + timedelta(minutes=31))
    assert db.query(Transaction).filter_by(status="held").count() == 0                  # nothing blocks money forever


# ---------------------------------------------------------------- held money is not history
def test_held_and_cancelled_transfers_do_not_count_as_history_for_shield(world):
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db, victims=2)
    before = rf.build_live_features(db, rahim, scam, 1000)
    h = login(world, rahim.phone)
    world.post("/demo/fake-sms", headers=h, json={"amount": 3000, "from_number": scam.phone})
    sent = world.post("/wallet/send", headers=h, json={"recipient_phone": scam.phone, "amount": 3000, "pin": "12345", "acknowledged_risk": True}).json()
    assert sent["transaction"]["status"] == "held"
    db.expire_all()
    during = rf.build_live_features(db, db.get(User, rahim.id), db.get(User, scam.id), 1000)
    world.post(f"/wallet/transactions/{sent['transaction']['id']}/cancel", headers=h)
    db.expire_all()
    after = rf.build_live_features(db, db.get(User, rahim.id), db.get(User, scam.id), 1000)
    for f in ("recipient_prior_txns", "first_time_senders_24h", "recipient_inflow_count_24h", "is_first_time_recipient", "sender_history_count"):
        assert during[f] == before[f] == after[f], f


# ---------------------------------------------------------------- safety-check answers
def test_a_risky_answer_pushes_a_safety_check_up_to_a_hold(world):
    db, rahim, mum = setup_victim(world)
    seller = young_seller(db)
    h = login(world, rahim.phone)
    risk, ids = question_ids(world, h, seller.phone, 4000)
    assert risk["action"] == "safety_check" and len(ids) == 2
    refined = world.post("/wallet/send/preview", headers=h, json={
        "recipient_phone": seller.phone, "amount": 4000, "safety_answers": [{"question_id": ids[0], "answer": "yes"}]}).json()["risk"]
    assert refined["action"] == "hold_30min" and refined["risk_pct"] > risk["risk_pct"] and refined["risk_before_pct"] == risk["risk_pct"]


def test_reassuring_answers_keep_the_warning_but_let_the_customer_go_on(world):
    db, rahim, mum = setup_victim(world)
    seller = young_seller(db)
    h = login(world, rahim.phone)
    risk, ids = question_ids(world, h, seller.phone, 4000)
    spec = risk["questions"][1]
    answers = [{"question_id": ids[0], "answer": "no"},
               {"question_id": ids[1], "answer": "no" if spec["risky_answer"] == "yes" else "yes"}]
    body = {"recipient_phone": seller.phone, "amount": 4000, "pin": "12345", "safety_answers": answers}
    first = world.post("/wallet/send", headers=h, json=body)
    assert first.status_code == 409 and first.json()["risk"]["action"] in ("warn_and_confirm", "safety_check", "allow_with_note")
    if first.json()["risk"]["action"] != "allow_with_note":
        assert first.json()["risk"]["risk_pct"] >= risk["risk_pct"] * 0.6                 # a coached "no" never switches protection off
    done = world.post("/wallet/send", headers=h, json={**body, "acknowledged_risk": True})
    assert done.status_code == 200 and done.json()["transaction"]["status"] == "completed"


def test_the_risky_answer_through_send_creates_a_hold_not_a_payment(world):
    db, rahim, mum = setup_victim(world)
    seller = young_seller(db)
    h = login(world, rahim.phone)
    _, ids = question_ids(world, h, seller.phone, 4000)
    r = world.post("/wallet/send", headers=h, json={"recipient_phone": seller.phone, "amount": 4000, "pin": "12345",
                   "acknowledged_risk": True, "safety_answers": [{"question_id": ids[0], "answer": "yes"}]})
    assert r.status_code == 200 and r.json()["transaction"]["status"] == "held" and r.json()["balance"] == 26000


def test_bad_answers_are_rejected_safely_by_falling_back_to_the_plain_score(world):
    db, rahim, mum = setup_victim(world)
    seller = young_seller(db)
    h = login(world, rahim.phone)
    r = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": seller.phone, "amount": 4000,
                   "safety_answers": [{"question_id": "made_up", "answer": "yes"}]})
    assert r.status_code == 200 and r.json()["risk"]["action"] == "safety_check"          # Shield refused the answers; plain score stands


def test_a_scam_looking_wallet_alone_does_not_trigger_an_alert_but_stacked_signals_do(world):
    """Honest group-fund wallets look the same as fraud wallets, so the recipient pattern alone is not enough."""
    db, rahim, mum = setup_victim(world)
    scam = make_scam_wallet(db)
    h = login(world, rahim.phone)
    calm = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": scam.phone, "amount": 3000}).json()["risk"]
    pressured = world.post("/wallet/send/preview", headers=h, json={"recipient_phone": scam.phone, "amount": 3000,
                           "behavior": {"on_call": True, "hesitation_secs": 30, "amount_edits": 3}}).json()["risk"]
    assert calm["action"] in ("allow", "allow_with_note")
    assert pressured["risk_pct"] > calm["risk_pct"]
