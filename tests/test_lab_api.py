"""The Risk Lab: analysts only, real transfers only (recorded when they happen), filterable, honest when Shield is off."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import database
import lab
import security
import shield_client
import wallet_api
import wallet_service as svc
from models import LabEntry, Transaction, utcnow
from wallet_helpers import make_engine


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture()
def world(monkeypatch):
    """A wallet database wired to a running Shield (for payment checks AND for the Lab)."""
    import shield_api
    Session = sessionmaker(bind=make_engine(), autoflush=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    wallet_api.app.dependency_overrides[database.get_db] = override
    with TestClient(shield_api.app) as shield, TestClient(wallet_api.app) as wallet:
        def post(path, payload):
            r = shield.post(path, json=payload)
            r.raise_for_status()
            return r.json()

        def lab_call(method, path, payload=None):
            r = shield.request(method, path, json=payload)
            r.raise_for_status()
            return r.json()

        monkeypatch.setattr(shield_client, "_post", post)
        monkeypatch.setattr(shield_client, "lab_call", lab_call)
        db = Session()
        svc.create_user(db, "01900000001", "Analyst Nadia", "99999", role="analyst")
        svc.create_user(db, "01711000001", "Rahim Uddin", "12345", balance=100000)
        svc.create_user(db, "01711000005", "Nusrat Jahan", "12345", balance=100000)
        svc.create_user(db, "01711000002", "Rahima Begum (Mum)", "12345")
        svc.create_user(db, "01711000004", "Shahin Grocery", "12345")
        db.close()
        wallet.Session = Session
        yield wallet
    wallet_api.app.dependency_overrides.clear()


def login(w, phone, pin="12345"):
    return {"Authorization": "Bearer " + w.post("/auth/login", json={"phone": phone, "pin": pin}).json()["token"]}


def send(w, who, to, amount, **kw):
    return w.post("/wallet/send", headers=login(w, who), json={"recipient_phone": to, "amount": amount, "pin": "12345", "acknowledged_risk": True, **kw})


def analyst(w):
    return login(w, "01900000001", "99999")


def test_customers_cannot_open_the_lab(world):
    h = login(world, "01711000001")
    for path in ("/lab/transactions", "/lab/filters", "/lab/catalogue", "/lab/report"):
        assert world.get(path, headers=h).status_code == 403
        assert world.get(path).status_code == 401
    assert world.post("/lab/transactions/1/explain", headers=h, json={}).status_code == 403


def test_the_lab_is_empty_until_a_real_transfer_happens(world):
    h = analyst(world)
    assert world.get("/lab/transactions", headers=h).json() == {"entries": [], "total_recorded": 0}
    assert world.get("/lab/filters", headers=h).json() == {"senders": [], "recipients": [], "total": 0}


def test_every_real_transfer_is_scored_and_recorded_when_it_happens(world):
    r = send(world, "01711000001", "01711000002", 500)
    assert r.status_code in (200, 201), r.text
    entries = world.get("/lab/transactions", headers=analyst(world)).json()["entries"]
    assert len(entries) == 1
    e = entries[0]
    assert e["amount"] == 500 and e["sender"]["phone"] == "01711000001" and e["recipient"]["phone"] == "01711000002"
    assert e["risk_pct"] is not None and e["tier"] in ("low", "note", "high", "very_high") and e["status"] == "completed"


def test_a_refused_transfer_leaves_no_trace(world):
    assert send(world, "01711000001", "01711000002", 500).status_code in (200, 201)
    bad = world.post("/wallet/send", headers=login(world, "01711000001"),
                     json={"recipient_phone": "01711000002", "amount": 500, "pin": "00000"})
    assert bad.status_code >= 400 and send(world, "01711000001", "01711000099", 500).status_code >= 400
    assert world.get("/lab/transactions", headers=analyst(world)).json()["total_recorded"] == 1


def test_filters_by_sender_recipient_name_and_time(world):
    h = analyst(world)
    send(world, "01711000001", "01711000002", 500)
    for who, to, amt in (("01711000005", "01711000004", 700), ("01711000001", "01711000004", 900)):
        r = send(world, who, to, amt)
        assert r.status_code in (200, 201), r.text
    opts = world.get("/lab/filters", headers=h).json()
    assert {s["phone"] for s in opts["senders"]} == {"01711000001", "01711000005"}
    assert {s["phone"] for s in opts["recipients"]} == {"01711000002", "01711000004"} and opts["total"] == 3
    get = lambda **q: world.get("/lab/transactions", headers=h, params=q).json()["entries"]   # noqa: E731
    assert len(get()) == 3
    assert {e["amount"] for e in get(sender="01711000001")} == {500, 900}
    assert {e["amount"] for e in get(recipient="01711000004")} == {700, 900}
    assert [e["amount"] for e in get(sender="01711000001", recipient="01711000004")] == [900]
    assert {e["amount"] for e in get(name="nusrat")} == {700}                    # the sender's registered name
    assert {e["amount"] for e in get(name="grocery")} == {700, 900}              # the recipient's registered name
    assert get(name="nobody") == []
    dhaka_now = (utcnow() + timedelta(hours=6)).replace(microsecond=0)
    fmt = lambda t: t.isoformat(timespec="seconds")                                # noqa: E731
    assert len(get(since=fmt(dhaka_now - timedelta(minutes=5)), until=fmt(dhaka_now + timedelta(minutes=5)))) == 3
    assert get(since=fmt(dhaka_now + timedelta(hours=1))) == []                    # in the future: nothing
    assert get(until=fmt(dhaka_now - timedelta(hours=1))) == []                    # before anything happened
    assert world.get("/lab/transactions", headers=h, params={"since": "yesterday-ish"}).status_code == 422


def test_explain_shows_all_31_signals_and_the_hide_a_group_what_if(world):
    h = analyst(world)
    send(world, "01711000001", "01711000002", 500)
    entry_id = world.get("/lab/transactions", headers=h).json()["entries"][0]["id"]
    full = world.post(f"/lab/transactions/{entry_id}/explain", headers=h, json={}).json()
    assert len(full["contributions"]) == 31 and full["entry"]["id"] == entry_id and "combination" in full
    hidden = world.post(f"/lab/transactions/{entry_id}/explain", headers=h, json={"mute_sides": ["pair"]}).json()
    assert hidden["muted"] and all(c["muted"] for c in hidden["contributions"] if c["side"] == "pair")
    assert world.post("/lab/transactions/9999/explain", headers=h, json={}).status_code == 404


def test_the_recorded_signals_are_what_the_ledger_said_at_that_moment(world):
    h = analyst(world)
    send(world, "01711000001", "01711000002", 500)          # first ever payment between the two
    send(world, "01711000001", "01711000002", 500)          # now they have history
    db = world.Session()
    first, second = db.query(LabEntry).order_by(LabEntry.id).all()
    import json
    f1, f2 = json.loads(first.features_json), json.loads(second.features_json)
    assert f1["i_first_time_recipient"] == 1.0 and f2["i_first_time_recipient"] == 0.0
    assert f2["s_history_count"] == f1["s_history_count"] + 1
    assert db.query(Transaction).filter_by(kind="send_money").count() == 2
    db.close()


def test_a_payment_still_goes_through_when_shield_is_off(world, monkeypatch):
    def down(*a, **k):
        raise RuntimeError("Shield is down")
    monkeypatch.setattr(shield_client, "_post", down)
    monkeypatch.setattr(shield_client, "lab_call", down)
    assert send(world, "01711000001", "01711000002", 500).status_code in (200, 201)
    h = analyst(world)
    e = world.get("/lab/transactions", headers=h).json()["entries"]
    assert len(e) == 1 and e[0]["risk_pct"] is None                    # recorded, scored later
    r = world.post(f"/lab/transactions/{e[0]['id']}/explain", headers=h, json={})
    assert r.status_code == 503 and r.json()["code"] == "shield_unavailable"


def test_the_lab_never_breaks_a_payment(world, monkeypatch):
    monkeypatch.setattr(lab_module(), "build_graded_features", lambda *a, **k: 1 / 0)
    assert send(world, "01711000001", "01711000002", 500).status_code in (200, 201)
    assert world.get("/lab/transactions", headers=analyst(world)).json()["total_recorded"] == 0


def lab_module():
    import lab_features
    return lab_features


def test_lab_calls_are_signed_like_payment_checks(monkeypatch):
    monkeypatch.setenv("SHIELD_API_SECRET", "s3cret")
    headers = shield_client._signed_headers(b'{"a":1}')
    assert {"X-Shield-Timestamp", "X-Shield-Signature"} <= set(headers)
    monkeypatch.delenv("SHIELD_API_SECRET")
    assert "X-Shield-Signature" not in shield_client._signed_headers(b"")
