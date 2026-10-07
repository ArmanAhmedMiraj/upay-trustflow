"""The demo contacts must really land where the send screen says they do, from every demo account."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import demo_contacts as dc
import lab_features
import risk_features
import security
import seed_wallet as sw
import shield_api
import shield_client
import wallet_service as svc
from models import AccountProfile, LabEntry, Transaction, User
from wallet_helpers import make_session

ACTION = {"low": "allow", "note": "allow_with_note", "check": "safety_check", "hold": "hold_30min"}
SENDERS = ("rahim", "nusrat", "sumon")


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture(scope="module")
def world():
    db = make_session()
    sw.seed(db, n_users=1500, days=60, log=lambda *_: None)
    with TestClient(shield_api.app) as shield:
        yield db, shield


def user(db, phone):
    return db.scalar(select(User).where(User.phone == phone))


def live(db, shield, sender, recipient, amount):
    v1 = risk_features.build_live_features(db, sender, recipient, amount)
    graded = lab_features.build_graded_features(db, sender, recipient, amount, v1=v1)
    return shield.post("/risk/score-live", json={"features": v1, "graded_features": graded}).json()


def test_every_contact_exists_with_a_profile_and_a_ledger_that_adds_up(world):
    db, _ = world
    assert sw.check_ledger(db) == []
    for key, name, phone, group, why in dc.CONTACTS:
        u = user(db, phone)
        assert u is not None and u.role == "customer", key
        assert db.get(AccountProfile, u.id) is not None, key
    assert len({c[2] for c in dc.CONTACTS}) == len(dc.CONTACTS)               # numbers are unique
    assert not {c[2] for c in dc.CONTACTS} & {sw.DEMO[k] for k in ("rahim", "nusrat", "sumon")}


def test_each_contact_lands_at_the_level_the_send_screen_promises_from_every_demo_account(world):
    db, shield = world
    wrong = []
    for sender_key in SENDERS:
        sender = user(db, sw.DEMO[sender_key])
        for key, name, phone, group, why in dc.CONTACTS:
            r = live(db, shield, sender, user(db, phone), 3000)
            if r["action"] != ACTION[group]:
                wrong.append(f"{sender_key} -> {key}: promised {group}, got {r['action']} ({r['risk_pct']}%)")
    assert not wrong, "\n".join(wrong)


def test_the_risk_lab_agrees_with_the_payment_screen_for_every_contact(world):
    """The tier the Lab shows (graded model alone) is the level promised on the chip, so judges see one story in both places."""
    import graded_risk.engine as graded
    db, _ = world
    tier = {"low": "low", "note": "note", "check": "high", "hold": "very_high"}
    wrong = []
    for sender_key in SENDERS:
        sender = user(db, sw.DEMO[sender_key])
        for key, name, phone, group, why in dc.CONTACTS:
            out = graded.get_engine().explain(lab_features.build_graded_features(db, sender, user(db, phone), 3000))
            if out["tier"] != tier[group]:
                wrong.append(f"{sender_key} -> {key}: promised {tier[group]}, Lab says {out['tier']} ({out['risk_pct']}%)")
    assert not wrong, "\n".join(wrong)


def test_all_four_levels_are_represented_and_risk_rises_with_the_level(world):
    db, shield = world
    sender = user(db, sw.DEMO["rahim"])
    by_level = {}
    for key, name, phone, group, why in dc.CONTACTS:
        by_level.setdefault(group, []).append(live(db, shield, sender, user(db, phone), 3000)["risk_pct"])
    assert set(by_level) == {"low", "note", "check", "hold"}
    assert max(by_level["low"]) < min(by_level["note"]) <= max(by_level["note"]) < min(by_level["check"]) \
        <= max(by_level["check"]) < min(by_level["hold"])
    assert len(by_level["hold"]) >= 3 and len(set(by_level["check"])) >= 2     # graded, not a single number


def test_the_two_models_disagree_where_the_graded_one_sees_more(world):
    """A rented-SIM mule looks ordinary to the first model; the graded model, which sees SIM age and ID checks, does not."""
    db, shield = world
    sender, rina = user(db, sw.DEMO["rahim"]), user(db, "01613308841")
    v1 = risk_features.build_live_features(db, sender, rina, 3000)
    first_only = shield.post("/risk/score", json=v1).json()
    both = live(db, shield, sender, rina, 3000)
    assert first_only["action"] != "hold_30min" and both["action"] == "hold_30min" and both["model_version"] == "v1+graded-1"


def test_nothing_is_pre_filled_in_the_lab(world):
    db, _ = world
    assert db.scalar(select(func.count()).select_from(LabEntry)) == 0


def test_a_real_transfer_to_a_contact_is_recorded_and_nothing_else(world, monkeypatch):
    db, shield = world
    monkeypatch.setattr(shield_client, "_post", lambda path, payload: shield.post(path, json=payload).json())
    monkeypatch.setattr(shield_client, "lab_call", lambda m, p, payload=None: shield.request(m, p, json=payload).json())
    rahim, rina = user(db, sw.DEMO["rahim"]), user(db, "01613308841")
    before = db.scalar(select(func.count()).select_from(LabEntry))
    txn = svc.send_money(db, rahim, rina.phone, 3000, "12345", acknowledged_risk=True)
    entries = db.scalars(select(LabEntry)).all()
    assert before == 0 and len(entries) == 1 and entries[0].transaction_id == txn.id
    assert entries[0].risk_pct > 90 and txn.status == "held" and entries[0].status == "held"
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.id == txn.id)) == 1


def test_contact_list_helper_gives_name_number_level_and_reason(world):
    db, _ = world
    out = dc.contact_list(db, User)
    assert len(out) == len(dc.CONTACTS) and {c["level"] for c in out} == {"low", "note", "check", "hold"}
    assert all(c["name"] and c["phone"].startswith("01") and len(c["phone"]) == 11 and len(c["why"]) > 20 for c in out)


def test_the_demo_contacts_route_hides_the_logged_in_person_and_can_be_switched_off(world, monkeypatch):
    import database
    import wallet_api
    db, _ = world
    rahim = user(db, sw.DEMO["rahim"])
    wallet_api.app.dependency_overrides[wallet_api.current_user] = lambda: rahim
    wallet_api.app.dependency_overrides[database.get_db] = lambda: db
    try:
        with TestClient(wallet_api.app) as c:
            body = c.get("/demo/contacts").json()
            assert len(body["contacts"]) == len(dc.CONTACTS) and rahim.phone not in {x["phone"] for x in body["contacts"]}
            assert {"key", "name", "phone", "level", "level_label", "why"} <= set(body["contacts"][0])
            monkeypatch.setattr(wallet_api, "DEMO_MODE", False)
            assert c.get("/demo/contacts").status_code == 404
    finally:
        wallet_api.app.dependency_overrides.clear()
