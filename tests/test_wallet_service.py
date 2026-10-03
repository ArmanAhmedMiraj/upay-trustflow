import random
from datetime import timedelta

import pytest
from sqlalchemy import select

import risk_hook
import security
import wallet_service as svc
from models import Transaction, User, utcnow
from wallet_helpers import make_session


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(security, "ITERATIONS", 1000)


@pytest.fixture()
def db():
    return make_session()


def customer(db, phone="01711000001", name="Rahim", pin="12345", balance=0):
    return svc.create_user(db, phone, name, pin, balance=balance)


def code_of(call, *a, **k):
    with pytest.raises(svc.WalletError) as e:
        call(*a, **k)
    return e.value.code


# ---------------------------------------------------------------- registration
def test_register_creates_a_customer_with_a_hashed_pin(db):
    u = svc.register(db, "01711000001", "  Rahim  ", "12345")
    assert u.role == "customer" and u.balance == 0 and u.name == "Rahim"
    assert u.pin_hash != "12345"


@pytest.mark.parametrize("phone", ["", "1711000001", "01211000001", "017110000012", "0171100000a", "+8801711000001"])
def test_register_rejects_bad_phone_numbers(db, phone):
    assert code_of(svc.register, db, phone, "Rahim", "12345") == "invalid_phone"


@pytest.mark.parametrize("pin", ["", "1234", "123456", "abcde", "12 45"])
def test_register_rejects_bad_pins(db, pin):
    assert code_of(svc.register, db, "01711000001", "Rahim", pin) == "invalid_pin"


def test_register_rejects_empty_name_and_duplicate_phone(db):
    assert code_of(svc.register, db, "01711000001", "   ", "12345") == "invalid_name"
    svc.register(db, "01711000001", "Rahim", "12345")
    assert code_of(svc.register, db, "01711000001", "Other", "54321") == "phone_taken"


# ---------------------------------------------------------------- login and lockout
def test_login_returns_a_token_that_authenticates(db):
    customer(db)
    token, user = svc.login(db, "01711000001", "12345")
    assert svc.authenticate(db, token).id == user.id


def test_wrong_pin_and_unknown_phone_give_the_same_error(db):
    customer(db)
    assert code_of(svc.login, db, "01711000001", "99999") == "wrong_credentials"
    assert code_of(svc.login, db, "01799999999", "12345") == "wrong_credentials"


def test_five_wrong_pins_lock_the_account_even_for_the_right_pin(db):
    customer(db)
    for _ in range(svc.MAX_PIN_ATTEMPTS):
        assert code_of(svc.login, db, "01711000001", "00000") == "wrong_credentials"
    assert code_of(svc.login, db, "01711000001", "12345") == "account_locked"


def test_lock_expires_and_a_correct_pin_resets_the_counter(db):
    u = customer(db)
    for _ in range(svc.MAX_PIN_ATTEMPTS):
        code_of(svc.login, db, "01711000001", "00000")
    u.locked_until = utcnow() - timedelta(minutes=1)
    db.commit()
    svc.login(db, "01711000001", "12345")
    assert u.failed_pin_attempts == 0 and u.locked_until is None


def test_failed_attempts_are_saved_even_though_the_request_fails(db):
    u = customer(db)
    code_of(svc.login, db, "01711000001", "00000")
    code_of(svc.login, db, "01711000001", "00000")
    db.expire_all()
    assert db.get(User, u.id).failed_pin_attempts == 2


def test_tokens_are_not_stored_in_the_database(db):
    customer(db)
    token, _ = svc.login(db, "01711000001", "12345")
    from models import AuthSession
    assert db.scalar(select(AuthSession.token_hash)) != token


def test_expired_unknown_and_logged_out_tokens_are_rejected(db):
    customer(db)
    token, _ = svc.login(db, "01711000001", "12345")
    assert code_of(svc.authenticate, db, None) == "not_logged_in"
    assert code_of(svc.authenticate, db, "garbage") == "not_logged_in"
    from models import AuthSession
    sess = db.scalar(select(AuthSession))
    sess.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert code_of(svc.authenticate, db, token) == "not_logged_in"
    token2, _ = svc.login(db, "01711000001", "12345")
    svc.logout(db, token2)
    assert code_of(svc.authenticate, db, token2) == "not_logged_in"


# ---------------------------------------------------------------- add money
def test_add_money_increases_balance_and_writes_the_ledger(db):
    u = customer(db)
    svc.add_money(db, u, 5000)
    assert u.balance == 5000
    t = db.scalar(select(Transaction))
    assert (t.kind, t.sender_id, t.receiver_id, t.amount) == ("add_money", None, u.id, 5000)


@pytest.mark.parametrize("amount", [0, 9, -5, svc.MAX_ADD_MONEY + 1, 10.5, "100", True])
def test_add_money_rejects_bad_amounts(db, amount):
    assert code_of(svc.add_money, db, customer(db), amount) == "invalid_amount"


def test_a_wallet_cannot_exceed_the_balance_limit(db):
    u = customer(db, balance=svc.MAX_BALANCE - 100)
    assert code_of(svc.add_money, db, u, 500) == "balance_limit"


# ---------------------------------------------------------------- send money
def test_send_money_moves_exactly_the_amount(db):
    a, b = customer(db, balance=10000), customer(db, "01711000002", "Karim")
    t = svc.send_money(db, a, "01711000002", 2500, "12345")
    assert (a.balance, b.balance) == (7500, 2500) and t.status == "completed"


def test_send_money_checks_the_pin_every_time(db):
    a, b = customer(db, balance=10000), customer(db, "01711000002", "Karim")
    assert code_of(svc.send_money, db, a, "01711000002", 100, "00000") == "wrong_credentials"
    assert (a.balance, b.balance) == (10000, 0)


def test_send_money_refuses_bad_cases_without_moving_anything(db):
    a = customer(db, balance=1000)
    customer(db, "01711000002", "Karim")
    svc.create_user(db, "01811000009", "Agent", "11111", role="agent")
    assert code_of(svc.send_money, db, a, "01711000002", 5000, "12345") == "insufficient_balance"
    assert code_of(svc.send_money, db, a, "01711000001", 100, "12345") == "self_transfer"
    assert code_of(svc.send_money, db, a, "01799999999", 100, "12345") == "recipient_not_found"
    assert code_of(svc.send_money, db, a, "01811000009", 100, "12345") == "recipient_not_found"   # agents get cash-outs only
    assert code_of(svc.send_money, db, a, "01711000002", svc.MAX_SEND + 1, "12345") == "invalid_amount"
    assert a.balance == 1000 and db.scalar(select(Transaction)) is None


def test_the_same_request_sent_twice_moves_money_once(db):
    a, b = customer(db, balance=10000), customer(db, "01711000002", "Karim")
    t1 = svc.send_money(db, a, "01711000002", 1000, "12345", idempotency_key="tap-1")
    t2 = svc.send_money(db, a, "01711000002", 1000, "12345", idempotency_key="tap-1")
    assert t1.id == t2.id and (a.balance, b.balance) == (9000, 1000)


def test_shield_can_stop_a_transfer_before_money_moves(db, monkeypatch):
    a, b = customer(db, balance=10000), customer(db, "01711000002", "Karim")
    monkeypatch.setattr(risk_hook, "check_transfer",
                        lambda *args, **kw: risk_hook.RiskDecision("hold_30min", 96, "very_high"))
    with pytest.raises(svc.RiskInterruption) as e:
        svc.send_money(db, a, "01711000002", 5000, "12345")
    assert e.value.decision.risk_pct == 96 and e.value.status == 409
    assert (a.balance, b.balance) == (10000, 0) and db.scalar(select(Transaction)) is None


def test_the_risk_decision_is_recorded_on_the_ledger_row(db, monkeypatch):
    a, _ = customer(db, balance=10000), customer(db, "01711000002", "Karim")
    monkeypatch.setattr(risk_hook, "check_transfer",
                        lambda *args, **kw: risk_hook.RiskDecision("allow_with_note", 12, "note"))
    t = svc.send_money(db, a, "01711000002", 500, "12345")
    assert (t.risk_pct, t.risk_tier) == (12, "note")


# ---------------------------------------------------------------- cash out
def test_cash_out_goes_to_an_agent_only(db):
    c = customer(db, balance=5000)
    agent = svc.create_user(db, "01811000009", "Agent Babul", "11111", role="agent")
    other = customer(db, "01711000002", "Karim")
    svc.cash_out(db, c, "01811000009", 2000, "12345")
    assert (c.balance, agent.balance) == (3000, 2000)
    assert code_of(svc.cash_out, db, c, other.phone, 100, "12345") == "agent_not_found"


# ---------------------------------------------------------------- history
def test_history_shows_direction_and_counterparty(db):
    a, b = customer(db, balance=10000), customer(db, "01711000002", "Karim")
    svc.send_money(db, a, "01711000002", 700, "12345")
    mine, theirs = svc.history(db, a)[0], svc.history(db, b)[0]
    assert (mine["direction"], mine["counterparty_name"]) == ("out", "Karim")
    assert (theirs["direction"], theirs["counterparty_name"]) == ("in", "Rahim")


# ---------------------------------------------------------------- the money invariant
def test_balances_always_match_the_ledger_after_many_random_operations(db):
    """No money is ever created or lost by transfers, and no balance goes negative."""
    rng = random.Random(1)
    users = [customer(db, f"017110000{i:02d}", f"U{i}") for i in range(8)]
    agent = svc.create_user(db, "01811000009", "Agent", "11111", role="agent")
    added = 0
    for _ in range(400):
        u = rng.choice(users)
        op = rng.choice(["add", "send", "send", "cashout", "bad"])
        try:
            if op == "add":
                amt = rng.randint(10, 20000)
                svc.add_money(db, u, amt)
                added += amt
            elif op == "send":
                svc.send_money(db, u, rng.choice(users).phone, rng.randint(10, 15000), "12345")
            elif op == "cashout":
                svc.cash_out(db, u, agent.phone, rng.randint(10, 15000), "12345")
            else:
                svc.send_money(db, u, rng.choice(users).phone, rng.randint(10, 15000), "00000")   # wrong PIN
        except svc.WalletError:
            pass
        u.failed_pin_attempts = 0
        u.locked_until = None
        db.commit()
    everyone = users + [agent]
    for x in everyone:
        db.refresh(x)
        assert x.balance >= 0
    assert sum(x.balance for x in everyone) == added                      # money only enters through add_money
    for x in everyone:                                                    # replaying the ledger gives each balance
        ins = db.scalar(select(__import__("sqlalchemy").func.coalesce(__import__("sqlalchemy").func.sum(Transaction.amount), 0)).where(Transaction.receiver_id == x.id))
        outs = db.scalar(select(__import__("sqlalchemy").func.coalesce(__import__("sqlalchemy").func.sum(Transaction.amount), 0)).where(Transaction.sender_id == x.id))
        assert x.balance == ins - outs
