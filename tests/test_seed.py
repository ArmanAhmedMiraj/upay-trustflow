"""The seeded demo world must be consistent, repeatable, and set up the way the demo needs."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

import risk_features as rf
import security
import seed_wallet as sw
import wallet_service as svc
from models import Report, SmsMessage, Transaction, User
from wallet_helpers import make_session

NOW = datetime(2026, 10, 4, 9, 0, 0)       # 15:00 in Dhaka


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture(scope="module")
def world():
    db = make_session()
    info = sw.seed(db, n_users=200, days=30, seed_value=42, now=NOW, log=lambda *_: None)
    return db, info


def person(db, key):
    return db.scalar(select(User).where(User.phone == sw.DEMO[key]))


def test_the_ledger_is_consistent_everywhere(world):
    db, _ = world
    assert sw.check_ledger(db) == []
    total_added = db.scalar(select(func.sum(Transaction.amount)).where(Transaction.kind == "add_money"))
    total_held = db.scalar(select(func.sum(User.balance)))
    assert total_held == total_added                         # money only ever enters through add_money


def test_every_demo_character_exists_with_the_right_role(world):
    db, _ = world
    assert {k: person(db, k).role for k in ("rahim", "mum", "nusrat", "agent1", "analyst")} == {
        "rahim": "customer", "mum": "customer", "nusrat": "customer", "agent1": "agent", "analyst": "analyst"}
    assert person(db, "rahim").name == "Rahim Uddin" and person(db, "fraudster").name == "Jamal Hossain"
    assert db.scalar(select(func.count()).select_from(User).where(User.role == "agent")) == 3


def test_demo_characters_can_log_in_with_the_published_pins(world):
    db, _ = world
    token, user = svc.login(db, sw.DEMO["rahim"], sw.DEFAULT_PIN)
    assert user.name == "Rahim Uddin" and svc.authenticate(db, token).id == user.id
    assert svc.login(db, sw.DEMO["analyst"], sw.ANALYST_PIN)[1].role == "analyst"


def test_nothing_is_dated_in_the_future_and_nobody_is_below_zero(world):
    db, _ = world
    assert db.scalar(select(func.max(Transaction.created_at))) <= NOW
    assert db.scalar(select(func.max(SmsMessage.created_at))) <= NOW
    assert db.scalar(select(func.max(Report.created_at))) <= NOW
    assert db.scalar(select(func.min(User.balance))) >= 0


def test_everyday_payments_are_not_first_time_or_history_free(world):
    """The cold-start fix: Rahim's regular recipients have real history."""
    db, _ = world
    rahim = person(db, "rahim")
    f = rf.build_live_features(db, rahim, person(db, "mum"), 1000, now=NOW)
    assert f["is_first_time_recipient"] == 0 and f["sender_history_count"] >= 10 and f["recipient_prior_txns"] >= 5


def test_fraud_wallet_one_is_young_busy_cashing_out_and_reported(world):
    db, _ = world
    f = rf.build_live_features(db, person(db, "rahim"), person(db, "fraudster"), 5000, now=NOW)
    assert 2.9 < f["recipient_age_days"] < 3.1 and f["first_time_senders_24h"] >= 8
    assert f["recipient_outflow_ratio_24h"] > 0.5 and f["report_count"] == 2


def test_fraud_wallet_two_looks_the_same_but_nobody_has_reported_it(world):
    db, _ = world
    f = rf.build_live_features(db, person(db, "rahim"), person(db, "fraudster2"), 5000, now=NOW)
    assert f["first_time_senders_24h"] >= 6 and f["report_count"] == 0 and f["recipient_age_days"] < 2.1


def test_the_young_seller_has_exactly_two_past_payers(world):
    db, _ = world
    seller = person(db, "fashion_hub")
    payers = db.scalars(select(Transaction.sender_id).where(Transaction.receiver_id == seller.id)).all()
    assert len(set(payers)) == 2 and 59 < (NOW - seller.created_at).days + 1 < 62


def test_the_inbox_holds_only_recent_true_messages(world):
    db, _ = world
    msgs = db.scalars(select(SmsMessage)).all()
    assert msgs and all(m.official for m in msgs) and min(m.created_at for m in msgs) >= NOW - timedelta(days=2)


def test_seeding_is_repeatable():
    def fingerprint():
        db = make_session()
        info = sw.seed(db, n_users=120, days=20, seed_value=7, now=NOW, log=lambda *_: None)
        return (info["users"], info["transactions"], db.scalar(select(func.sum(Transaction.amount))))
    assert fingerprint() == fingerprint()


def test_demo_characters_can_afford_the_demo(world):
    db, _ = world
    for key in ("rahim", "mum", "nusrat", "sumon"):
        assert person(db, key).balance >= sw.DEMO_MIN_BALANCE, key
