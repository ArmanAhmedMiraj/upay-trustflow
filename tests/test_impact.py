"""The impact numbers must match what really happened to each flagged transfer."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import database
import impact
import security
import wallet_api
import wallet_service as svc
from models import Report, RiskEvent, Transaction, User, utcnow
from wallet_helpers import make_engine, make_session

NOW = utcnow()


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


def customer(db, phone, name):
    return svc.create_user(db, phone, name, "12345", balance=100000)


def preview(db, sender, recipient, amount, tier, minutes_ago=60, available=True):
    e = RiskEvent(sender_id=sender.id, recipient_id=recipient.id, amount=amount, risk_pct=90 if tier in ("high", "very_high") else 5,
                  tier=tier, action="x", source="preview", shield_available=available, created_at=NOW - timedelta(minutes=minutes_ago))
    db.add(e)
    db.commit()
    return e


def follow_up(db, sender, recipient, amount, status, held=False, minutes_ago=58):
    t = Transaction(kind="send_money", sender_id=sender.id, receiver_id=recipient.id, amount=amount, status=status,
                    created_at=NOW - timedelta(minutes=minutes_ago), release_at=(NOW if held else None))
    db.add(t)
    db.commit()
    return t


@pytest.fixture()
def world():
    db = make_session()
    a, b, bad = customer(db, "01711000001", "Rahim"), customer(db, "01711000002", "Mum"), customer(db, "01711999999", "Jamal")
    return db, a, b, bad


def test_every_outcome_is_counted_with_its_amount(world):
    db, a, b, bad = world
    preview(db, a, b, 800, "low")                                                    # fine: not flagged
    preview(db, a, b, 900, "note")                                                   # note: not flagged
    preview(db, a, bad, 5000, "very_high")                                           # saw the warning, walked away
    preview(db, a, bad, 6000, "very_high", minutes_ago=50); follow_up(db, a, bad, 6000, "cancelled", held=True, minutes_ago=48)
    preview(db, a, bad, 7000, "very_high", minutes_ago=40); follow_up(db, a, bad, 7000, "rejected", held=True, minutes_ago=38)
    preview(db, a, bad, 8000, "very_high", minutes_ago=30); follow_up(db, a, bad, 8000, "held", held=True, minutes_ago=28)
    preview(db, a, bad, 9000, "high", minutes_ago=20); follow_up(db, a, bad, 9000, "completed", held=True, minutes_ago=18)   # hold ran out
    preview(db, a, bad, 4000, "high", minutes_ago=10); follow_up(db, a, bad, 4000, "completed", held=False, minutes_ago=8)   # sent anyway
    r = impact.impact(db, 24, NOW)
    assert r["checks"] == 8 and r["flagged"] == 6
    assert r["tiers"] == {"low": 1, "note": 1, "high": 2, "very_high": 4}
    o = r["outcomes"]
    assert o["walked_away"] == {"count": 1, "bdt": 5000}
    assert o["cancelled"] == {"count": 1, "bdt": 6000}
    assert o["rejected"] == {"count": 1, "bdt": 7000}
    assert o["on_hold"] == {"count": 1, "bdt": 8000}
    assert o["released_after_hold"] == {"count": 1, "bdt": 9000}
    assert o["sent_after_warning"] == {"count": 1, "bdt": 4000}
    assert r["kept_back_bdt"] == 5000 + 6000 + 7000
    assert r["released_bdt"] == 9000 + 4000 and r["on_hold_bdt"] == 8000
    assert r["heeded"] == 3 and r["heeded_rate"] == 0.5
    assert r["friction_rate"] == 0.75


def test_a_payment_of_a_different_amount_or_to_someone_else_is_not_the_follow_up(world):
    db, a, b, bad = world
    preview(db, a, bad, 5000, "very_high")
    follow_up(db, a, bad, 4999, "completed")           # different amount
    follow_up(db, a, b, 5000, "completed")             # different person
    assert impact.impact(db, 24, NOW)["outcomes"]["walked_away"]["count"] == 1


def test_a_payment_long_after_the_warning_is_not_the_follow_up(world):
    db, a, b, bad = world
    preview(db, a, bad, 5000, "very_high", minutes_ago=300)
    follow_up(db, a, bad, 5000, "completed", minutes_ago=100)
    assert impact.impact(db, 24, NOW)["outcomes"]["walked_away"]["count"] == 1


def test_old_activity_is_outside_the_window(world):
    db, a, b, bad = world
    preview(db, a, bad, 5000, "very_high", minutes_ago=60 * 30)
    assert impact.impact(db, 24, NOW)["checks"] == 0
    assert impact.impact(db, 24 * 7, NOW)["checks"] == 1


def test_an_empty_system_reports_zeros_not_errors(world):
    db, *_ = world
    r = impact.impact(db, 24, NOW)
    assert r["checks"] == 0 and r["friction_rate"] == 0.0 and r["heeded_rate"] == 0.0 and r["shield_available_rate"] == 1.0


def test_reports_open_cases_and_shield_availability(world):
    db, a, b, bad = world
    preview(db, a, b, 800, "low"); preview(db, a, b, 800, "low", available=False)
    follow_up(db, a, bad, 100, "held", held=True)
    db.add(Report(reporter_id=a.id, reported_id=bad.id, created_at=NOW - timedelta(minutes=5)))
    db.add(Report(reporter_id=b.id, reported_id=bad.id, created_at=NOW - timedelta(minutes=4)))
    db.commit()
    r = impact.impact(db, 24, NOW)
    assert r["open_cases"] == 1 and r["reports"] == 2 and r["reported_wallets"] == 1 and r["shield_available_rate"] == 0.5


# ---------------------------------------------------------------- the offline model report
def test_model_report_reads_the_saved_evaluation():
    r = impact.model_report()
    assert r["test_fraud"] > 500 and 0.5 < r["fraud_caught_pct"] < 1 and r["genuine_disturbed_pct"] < 0.02
    assert r["ranking"]["lightgbm_raw"]["pr_auc"] > r["ranking"]["rules_only_baseline"]["pr_auc"]
    assert set(r["impact_by_heeding_rate"]) == {"0.3", "0.5", "0.7"}


def test_model_report_survives_a_missing_or_broken_file(tmp_path):
    assert impact.model_report(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert impact.model_report(bad) is None


# ---------------------------------------------------------------- over HTTP, and the demo reset
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
        c.Session, c.engine = Session, engine
        yield c
    wallet_api.app.dependency_overrides.clear()


def login(client, phone, pin):
    return {"Authorization": "Bearer " + client.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]}


def test_only_analysts_can_see_the_impact_pages(client):
    d = client.Session()
    svc.create_user(d, "01711000001", "Rahim", "12345")
    svc.create_user(d, "01900000001", "Nadia", "99999", role="analyst")
    d.close()
    cust, analyst = login(client, "01711000001", "12345"), login(client, "01900000001", "99999")
    for path in ("/analyst/impact", "/analyst/model-report"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=cust).status_code == 403
        assert client.get(path, headers=analyst).status_code == 200
    assert client.get("/analyst/impact?hours=24", headers=analyst).json()["window_hours"] == 24
    assert client.get("/analyst/model-report", headers=analyst).json()["report"]["test_fraud"] > 0


def test_reset_rebuilds_the_demo_world_and_old_data_is_gone(client):
    d = client.Session()
    svc.create_user(d, "01711555555", "Temporary", "12345")
    d.close()
    out = svc.reset_demo(client.engine, client.Session, users=120, days=20)
    d = client.Session()
    assert out["users"] > 120 and d.scalar(select(func.count()).select_from(User).where(User.phone == "01711555555")) == 0
    assert d.scalar(select(User).where(User.phone == "01711000001")).name == "Rahim Uddin"
    assert d.scalar(select(User).where(User.role == "analyst")) is not None
    d.close()


def test_the_reset_button_is_for_analysts_and_can_be_switched_off(client, monkeypatch):
    d = client.Session()
    svc.create_user(d, "01711000001", "Rahim", "12345")
    svc.create_user(d, "01900000001", "Nadia", "99999", role="analyst")
    d.close()
    cust, analyst = login(client, "01711000001", "12345"), login(client, "01900000001", "99999")
    assert client.post("/demo/reset", headers=cust).status_code == 403
    monkeypatch.setattr(wallet_api, "DEMO_MODE", False)
    assert client.post("/demo/reset", headers=analyst).status_code == 404
