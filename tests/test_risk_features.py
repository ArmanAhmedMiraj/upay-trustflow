"""The live feature builder must follow the same rules as the training builder."""
from datetime import datetime, timedelta

import numpy as np
import pytest

import generate_transfers as sim
import risk_features as rf
import security
import shield_api
import wallet_service as svc
from features import FEATURES, build_features
from models import Report, SmsMessage, Transaction, User
from wallet_helpers import make_session

NOW = datetime(2026, 3, 10, 9, 0, 0)       # 15:00 in Dhaka


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture()
def db():
    return make_session()


def user(db, phone, name="U", created=NOW - timedelta(days=400), balance=20000, role="customer"):
    u = User(phone=phone, name=name, pin_hash="x", balance=balance, role=role, created_at=created)
    db.add(u)
    db.commit()
    return u


def txn(db, kind, sender, receiver, amount, when):
    t = Transaction(kind=kind, sender_id=sender.id if sender else None, receiver_id=receiver.id if receiver else None,
                    amount=amount, created_at=when)
    db.add(t)
    db.commit()
    return t


def sms(db, owner, number, amount, official, when):
    m = SmsMessage(user_id=owner.id, sender_label="upay" if official else number, kind="credit_claim", official=official,
                   claimed_amount=amount, claimed_number=number, text="x", created_at=when)
    db.add(m)
    db.commit()
    return m


def history(db, sender, recipient, n=20, amount=800):
    for i in range(n):
        txn(db, "send_money", sender, recipient, amount + 50 * (i % 5), NOW - timedelta(days=30 - i, hours=-1))


# ------------------------------------------------------------------ the output is always valid for Shield
def test_output_has_exactly_shields_signals_and_passes_its_validation(db):
    a, b = user(db, "01711000001"), user(db, "01711000002")
    f = rf.build_live_features(db, a, b, 1500, now=NOW)
    assert set(f) == set(FEATURES)
    shield_api.TransferFeatures(**f)                      # raises if any value is out of range


def test_extreme_inputs_are_clipped_into_valid_ranges(db):
    a, b = user(db, "01711000001", balance=100), user(db, "01711000002")
    f = rf.build_live_features(db, a, b, 50000, {"hesitation_secs": 99999, "amount_edits": 999, "on_call": True}, now=NOW)
    shield_api.TransferFeatures(**f)
    assert f["balance_share"] == 1 and f["hesitation_secs"] == 3600 and f["amount_edits"] == 50


# ------------------------------------------------------------------ sender signals
def test_first_time_recipient_and_round_amounts(db):
    a, mum, stranger = user(db, "01711000001"), user(db, "01711000002"), user(db, "01711000003")
    history(db, a, mum)
    assert rf.build_live_features(db, a, mum, 800, now=NOW)["is_first_time_recipient"] == 0
    f = rf.build_live_features(db, a, stranger, 5000, now=NOW)
    assert f["is_first_time_recipient"] == 1 and f["is_round_amount"] == 1
    assert rf.build_live_features(db, a, stranger, 4999, now=NOW)["is_round_amount"] == 0


def test_a_large_amount_is_unusual_compared_with_the_senders_own_history(db):
    a, mum = user(db, "01711000001"), user(db, "01711000002")
    history(db, a, mum)
    usual = rf.build_live_features(db, a, mum, 850, now=NOW)["amount_zscore"]
    large = rf.build_live_features(db, a, mum, 20000, now=NOW)["amount_zscore"]
    assert abs(usual) < 1 and large > 3


def test_sending_at_an_unusual_hour_is_flagged_using_bangladesh_time(db):
    a, mum = user(db, "01711000001"), user(db, "01711000002")
    history(db, a, mum, n=30)                              # all history around 15:00-16:00 Dhaka time
    day = rf.build_live_features(db, a, mum, 800, now=NOW)["hour_unusual"]
    night = rf.build_live_features(db, a, mum, 800, now=NOW.replace(hour=21))["hour_unusual"]   # 03:00 in Dhaka
    assert night > day and night > 0.9


def test_time_since_money_arrived(db):
    a, friend = user(db, "01711000001"), user(db, "01711000002")
    assert rf.build_live_features(db, a, friend, 800, now=NOW)["log_mins_since_incoming"] > 9          # never received: capped
    txn(db, "add_money", None, a, 5000, NOW - timedelta(minutes=3))
    f = rf.build_live_features(db, a, friend, 800, now=NOW)
    assert f["log_mins_since_incoming"] < 1.5


# ------------------------------------------------------------------ recipient signals
def test_recipient_signals_for_a_fresh_wallet_that_collects_from_strangers_and_cashes_out(db):
    victim = user(db, "01711000001")
    scam = user(db, "01711999999", created=NOW - timedelta(days=3))
    agent = user(db, "01811000009", role="agent")
    for i in range(9):
        payer = user(db, f"017115000{i:02d}")
        txn(db, "send_money", payer, scam, 3000, NOW - timedelta(hours=5 - i * 0.3))
    txn(db, "cash_out", scam, agent, 25000, NOW - timedelta(hours=1))
    f = rf.build_live_features(db, victim, scam, 5000, now=NOW)
    assert abs(f["recipient_age_days"] - 3) < 0.01
    assert f["first_time_senders_24h"] == 9 and f["recipient_inflow_count_24h"] == 9
    assert f["recipient_outflow_ratio_24h"] == pytest.approx(25000 / 27000)


def test_repeat_payers_are_not_counted_as_first_time_senders(db):
    shop = user(db, "01711777777")
    for day in (5, 3, 1):
        for i in range(4):
            payer = user(db, f"01711600{day}{i}") if day == 5 else db.query(User).filter_by(phone=f"01711600{5}{i}").one()
            txn(db, "send_money", payer, shop, 200, NOW - timedelta(days=day, hours=-i))
    me = user(db, "01711000001")
    assert rf.build_live_features(db, me, shop, 200, now=NOW)["first_time_senders_24h"] == 0


def test_reports_and_report_rate(db):
    me, scam = user(db, "01711000001"), user(db, "01711999999")
    for i in range(3):
        r = user(db, f"01711800{i:03d}")
        db.add(Report(reporter_id=r.id, reported_id=scam.id, created_at=NOW - timedelta(hours=2)))
    db.commit()
    f = rf.build_live_features(db, me, scam, 5000, now=NOW)
    assert f["report_count"] == 3 and f["report_rate"] == pytest.approx(3 / 5.0)


# ------------------------------------------------------------------ the story check
def test_fake_credit_sms_naming_the_recipient_is_a_mismatch(db):
    me, scam = user(db, "01711000001"), user(db, "01711999999")
    sms(db, me, scam.phone, 5000, False, NOW - timedelta(minutes=10))
    f = rf.build_live_features(db, me, scam, 5000, now=NOW)
    assert (f["sms_claims_credit"], f["sms_mentions_recipient"], f["ledger_confirms_credit"]) == (1, 1, 0)
    assert f["claim_ledger_mismatch"] == 1 and f["claim_mismatch_on_recipient"] == 1 and f["sms_official_sender"] == 0


def test_a_genuine_return_is_confirmed_by_the_ledger(db):
    me, friend = user(db, "01711000001"), user(db, "01711000002")
    txn(db, "send_money", friend, me, 2000, NOW - timedelta(minutes=40))          # the money really arrived
    sms(db, me, friend.phone, 2000, True, NOW - timedelta(minutes=40))
    f = rf.build_live_features(db, me, friend, 2000, now=NOW)
    assert f["ledger_confirms_credit"] == 1 and f["claim_ledger_mismatch"] == 0 and f["sms_official_sender"] == 1


def test_wrong_amount_or_too_old_credit_does_not_confirm_the_claim(db):
    me, friend = user(db, "01711000001"), user(db, "01711000002")
    txn(db, "send_money", friend, me, 1000, NOW - timedelta(minutes=40))          # arrived, but not the claimed 2000
    txn(db, "send_money", friend, me, 2000, NOW - timedelta(hours=9))             # right amount, far too long ago
    sms(db, me, friend.phone, 2000, False, NOW - timedelta(minutes=30))
    assert rf.build_live_features(db, me, friend, 2000, now=NOW)["ledger_confirms_credit"] == 0


def test_official_messages_about_other_people_are_not_treated_as_claims(db):
    me, friend, shop = user(db, "01711000001"), user(db, "01711000002"), user(db, "01711000003")
    txn(db, "send_money", friend, me, 2000, NOW - timedelta(minutes=40))
    sms(db, me, friend.phone, 2000, True, NOW - timedelta(minutes=40))           # a true credit; I now pay someone else
    assert rf.build_live_features(db, me, shop, 500, now=NOW)["sms_claims_credit"] == 0


def test_an_unrelated_fake_claim_is_unverified_but_does_not_name_the_recipient(db):
    me, shop, stranger = user(db, "01711000001"), user(db, "01711000003"), user(db, "01711000004")
    sms(db, me, stranger.phone, 3000, False, NOW - timedelta(minutes=20))
    f = rf.build_live_features(db, me, shop, 500, now=NOW)
    assert f["claim_ledger_mismatch"] == 1 and f["sms_mentions_recipient"] == 0 and f["claim_mismatch_on_recipient"] == 0


# ------------------------------------------------------------------ no peeking into the future
def test_nothing_that_happens_after_the_transfer_changes_the_features(db):
    me, scam = user(db, "01711000001"), user(db, "01711999999", created=NOW - timedelta(days=3))
    before = rf.build_live_features(db, me, scam, 5000, now=NOW)
    later = NOW + timedelta(minutes=5)
    for i in range(6):
        payer = user(db, f"017119000{i:02d}")
        txn(db, "send_money", payer, scam, 3000, later + timedelta(minutes=i))
    reporter = user(db, "01711900099")
    db.add(Report(reporter_id=reporter.id, reported_id=scam.id, created_at=later))
    txn(db, "send_money", me, scam, 100, later)
    sms(db, me, scam.phone, 5000, False, later)
    db.commit()
    assert rf.build_live_features(db, me, scam, 5000, now=NOW) == before


# ------------------------------------------------------------------ parity with the training builder
def test_live_and_training_features_agree_on_a_whole_simulated_world(db):
    """Replays a simulation into the wallet database, then compares live features with the bulk builder."""
    data = sim.simulate(n_users=250, days=45, seed=5)
    base = datetime(2025, 12, 31, 18, 0, 0)               # so Dhaka local time = simulation clock
    at = lambda minutes: base + timedelta(minutes=float(minutes))   # noqa: E731

    wallets = data["wallets"]
    phone = {int(w): f"017{int(w):08d}" for w in wallets["wallet"]}
    users = {}
    for w, created in zip(wallets["wallet"], wallets["created_ts"]):
        u = User(phone=phone[int(w)], name=f"W{int(w)}", pin_hash="x", balance=10**9, created_at=at(created))
        db.add(u)
        users[int(w)] = u
    agent = User(phone="01800000000", name="Agent", pin_hash="x", role="agent")
    db.add(agent)
    db.commit()

    t = data["transfers"].sort_values("txn_id")
    for r in t.itertuples():
        db.add(Transaction(kind="send_money", sender_id=users[r.sender].id, receiver_id=users[r.recipient].id,
                           amount=int(r.amount), created_at=at(r.ts)))
        if not np.isnan(r.claim_amount):
            db.add(SmsMessage(user_id=users[r.sender].id, sender_label="x", kind="credit_claim", official=bool(r.claim_official),
                              claimed_amount=int(r.claim_amount), claimed_number=phone[int(r.claim_number)],
                              text="x", created_at=at(r.ts) - timedelta(seconds=30)))
    for r in data["salary"].itertuples():
        db.add(Transaction(kind="add_money", sender_id=None, receiver_id=users[r.receiver].id, amount=int(r.amount), created_at=at(r.ts)))
    for r in data["outflows"].itertuples():
        if r.amount > 0:
            db.add(Transaction(kind="cash_out", sender_id=users[r.wallet].id, receiver_id=agent.id, amount=int(r.amount), created_at=at(r.ts)))
    db.commit()
    for i, r in enumerate(data["reports"].itertuples()):
        reporter = User(phone=f"019{i:08d}", name="R", pin_hash="x", created_at=at(-10000))
        db.add(reporter)
        db.flush()
        db.add(Report(reporter_id=reporter.id, reported_id=users[r.wallet].id, created_at=at(r.ts)))
    db.commit()

    batch = build_features(data).set_index("txn_id")
    rng = np.random.default_rng(3)
    late = batch[batch["ts"] > 12 * 1440]
    picks = np.concatenate([
        rng.choice(late[late["label"] == 1].index.to_numpy(), 25, replace=False),
        rng.choice(late[late["claim_ledger_mismatch"] == 1].index.to_numpy(), 8, replace=False),
        rng.choice(late[late["ledger_confirms_credit"] == 1].index.to_numpy(), 5, replace=False),
        rng.choice(late[late["report_count"] > 0].index.to_numpy(), 10, replace=False),
        rng.choice(late[late["first_time_senders_24h"] > 0].index.to_numpy(), 10, replace=False),
        rng.choice(late.index.to_numpy(), 30, replace=False),
    ])
    rows = {int(r.txn_id): r for r in t.itertuples()}
    for tid in picks:
        r = rows[int(tid)]
        live = rf.build_live_features(
            db, users[r.sender], users[r.recipient], int(r.amount),
            {"hesitation_secs": r.hesitation_secs, "amount_edits": r.amount_edits, "on_call": bool(r.on_call)},
            now=at(r.ts), balance_before=int(r.balance_before), sms_window_minutes=1)
        for f in FEATURES:
            assert live[f] == pytest.approx(float(batch.loc[tid, f]), abs=1e-5, rel=1e-5), f"{f} differs for transfer {tid}"
