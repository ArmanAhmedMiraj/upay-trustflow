"""Wallet business logic, kept separate from the web layer so it can be tested on its own.

Principles
 - Money moves only inside one database transaction: either both balances change and the ledger
   row is written, or nothing changes.
 - Every transfer passes through the Shield hook (risk_hook.check_transfer) BEFORE money moves.
 - Wrong PINs are counted. After MAX_PIN_ATTEMPTS the account is locked for LOCK_MINUTES.
 - Error messages never reveal whether a phone number is registered (login says only "wrong phone or PIN").
 - Limits below are assumptions for the prototype, not upay's real limits.
"""
from __future__ import annotations

import json
import os
import re
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import lab
import risk_hook
import security
from models import AuthSession, Report, RiskEvent, SmsMessage, Transaction, User, utcnow

PHONE_RE = re.compile(r"^01[3-9]\d{8}$")   # Bangladeshi mobile numbers: 01 + operator digit 3-9 + 8 digits
PIN_RE = re.compile(r"^\d{5}$")

MAX_PIN_ATTEMPTS = 5
LOCK_MINUTES = 15
SESSION_HOURS = 12
MIN_AMOUNT = 10
MAX_SEND = 50_000
MAX_ADD_MONEY = 50_000
MAX_BALANCE = 500_000
ALLOWED_NOW = ("allow", "allow_with_note")   # risk actions that let the money move straight away
NEEDS_ACK = ("safety_check", "warn_and_confirm", "hold_30min")   # the customer must confirm after reading the warning


def hold_minutes() -> int:
    return int(os.getenv("HOLD_MINUTES", "30"))


class WalletError(Exception):
    """An expected problem (bad input, wrong PIN...). Carries a machine code and an HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class RiskInterruption(WalletError):
    """Shield asked for friction (safety check or hold), so the money did NOT move."""

    def __init__(self, decision):
        super().__init__("risk_interruption", "This transfer needs a safety check", 409)
        self.decision = decision


# ------------------------------------------------------------------ validation
def _check_phone(phone: str) -> str:
    if not isinstance(phone, str) or not PHONE_RE.match(phone):
        raise WalletError("invalid_phone", "Enter a valid 11-digit mobile number starting with 01")
    return phone


def _check_amount(amount, maximum: int) -> int:
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise WalletError("invalid_amount", "Amount must be a whole number of taka")
    if amount < MIN_AMOUNT or amount > maximum:
        raise WalletError("invalid_amount", f"Amount must be between {MIN_AMOUNT} and {maximum} taka")
    return amount


# ------------------------------------------------------------------ users and login
def create_user(db: Session, phone: str, name: str, pin: str, role: str = "customer", balance: int = 0) -> User:
    """Create a user. Used by register (customers) and by the seeding scripts (agents, distributors)."""
    _check_phone(phone)
    name = (name or "").strip()
    if not (1 <= len(name) <= 100):
        raise WalletError("invalid_name", "Name must be 1 to 100 characters")
    if not isinstance(pin, str) or not PIN_RE.match(pin):
        raise WalletError("invalid_pin", "PIN must be exactly 5 digits")
    user = User(phone=phone, name=name, pin_hash=security.hash_pin(pin), role=role, balance=balance)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise WalletError("phone_taken", "This number is already registered", 409)
    return user


def register(db: Session, phone: str, name: str, pin: str) -> User:
    return create_user(db, phone, name, pin, role="customer")


def _fail_pin(db: Session, user: User) -> None:
    user.failed_pin_attempts += 1
    if user.failed_pin_attempts >= MAX_PIN_ATTEMPTS:
        user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
        user.failed_pin_attempts = 0
    db.commit()    # saved at once, so the count survives even though the request then fails
    raise WalletError("wrong_credentials", "Wrong phone number or PIN", 401)


def verify_user_pin(db: Session, user: User, pin: str) -> None:
    """Check a PIN with lockout. Used at login and again when a customer confirms a payment."""
    if user.locked_until and user.locked_until > utcnow():
        raise WalletError("account_locked", "Too many wrong PINs. Try again later.", 423)
    if not isinstance(pin, str) or not security.verify_pin(pin, user.pin_hash):
        _fail_pin(db, user)
    user.failed_pin_attempts = 0
    user.locked_until = None
    db.commit()


def login(db: Session, phone: str, pin: str) -> tuple[str, User]:
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        security.hash_pin("00000")          # spend the same time as a real check, so timing reveals nothing
        raise WalletError("wrong_credentials", "Wrong phone number or PIN", 401)
    verify_user_pin(db, user, pin)
    token = security.new_token()
    db.add(AuthSession(token_hash=security.hash_token(token), user_id=user.id,
                       expires_at=utcnow() + timedelta(hours=SESSION_HOURS)))
    db.commit()
    return token, user


def logout(db: Session, token: str) -> None:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == security.hash_token(token)))
    if session:
        db.delete(session)
        db.commit()


def authenticate(db: Session, token: str | None) -> User:
    if not token:
        raise WalletError("not_logged_in", "Please log in", 401)
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == security.hash_token(token)))
    if session is None or session.expires_at < utcnow():
        raise WalletError("not_logged_in", "Your session has expired. Please log in again.", 401)
    return db.get(User, session.user_id)


# ------------------------------------------------------------------ money
def add_money(db: Session, user: User, amount: int) -> Transaction:
    """Simulated top-up from a card or bank (in the real app this is a bank integration)."""
    _check_amount(amount, MAX_ADD_MONEY)
    db.execute(select(User).where(User.id == user.id).with_for_update())   # lock the wallet while it changes
    db.refresh(user)
    if user.balance + amount > MAX_BALANCE:
        raise WalletError("balance_limit", f"A wallet cannot hold more than {MAX_BALANCE} taka")
    user.balance += amount
    txn = Transaction(kind="add_money", sender_id=None, receiver_id=user.id, amount=amount)
    db.add(txn)
    db.commit()
    return txn


def _existing(db: Session, sender: User, key: str | None) -> Transaction | None:
    if not key:
        return None
    return db.scalar(select(Transaction).where(Transaction.sender_id == sender.id,
                                               Transaction.idempotency_key == key))


def _move(db: Session, kind: str, sender: User, recipient: User, amount: int, key: str | None,
          risk_pct: int | None = None, risk_tier: str | None = None) -> Transaction:
    # lock both wallets in a fixed order (lowest id first) so two payments can never deadlock each other
    ids = sorted([sender.id, recipient.id])
    db.execute(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update())
    db.refresh(sender)
    db.refresh(recipient)
    if sender.balance < amount:
        raise WalletError("insufficient_balance", "You do not have enough balance", 400)
    if recipient.balance + amount > MAX_BALANCE:
        raise WalletError("recipient_limit", "The recipient cannot receive this amount", 400)
    sender.balance -= amount
    recipient.balance += amount
    txn = Transaction(kind=kind, sender_id=sender.id, receiver_id=recipient.id, amount=amount,
                      risk_pct=risk_pct, risk_tier=risk_tier, idempotency_key=key)
    db.add(txn)
    db.flush()
    if kind == "send_money":     # the true "money received" message: written by the ledger itself, so it cannot be false
        db.add(SmsMessage(user_id=recipient.id, sender_label="upay", kind="credit_claim", official=True,
                          claimed_amount=amount, claimed_number=sender.phone,
                          text=f"You have received Tk {amount:,} from {sender.phone}. TrxID {txn.id:08d}."))
    try:
        db.commit()
    except IntegrityError:        # the same request arrived twice at the same moment
        db.rollback()
        again = _existing(db, sender, key)
        if again:
            return again
        raise
    return txn


def _hold(db: Session, kind: str, sender: User, recipient: User, amount: int, key: str | None,
          risk_pct: int | None, risk_tier: str | None) -> Transaction:
    """Take the money out of the sender's balance and keep it safe (escrow) until the hold ends."""
    db.execute(select(User).where(User.id == sender.id).with_for_update())
    db.refresh(sender)
    if sender.balance < amount:
        raise WalletError("insufficient_balance", "You do not have enough balance", 400)
    sender.balance -= amount
    txn = Transaction(kind=kind, sender_id=sender.id, receiver_id=recipient.id, amount=amount, status="held",
                      release_at=utcnow() + timedelta(minutes=hold_minutes()), risk_pct=risk_pct, risk_tier=risk_tier,
                      idempotency_key=key)
    db.add(txn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        again = _existing(db, sender, key)
        if again:
            return again
        raise
    return txn


def _credit_message(db: Session, txn: Transaction, sender: User, recipient: User) -> None:
    db.add(SmsMessage(user_id=recipient.id, sender_label="upay", kind="credit_claim", official=True,
                      claimed_amount=txn.amount, claimed_number=sender.phone,
                      text=f"You have received Tk {txn.amount:,} from {sender.phone}. TrxID {txn.id:08d}."))


def _finish_hold(db: Session, txn: Transaction, outcome: str, reviewer: User | None = None,
                 note: str | None = None, now=None) -> Transaction:
    """End a hold. outcome: "release" (money goes to the recipient), "cancel" (back to the sender) or "reject"."""
    ids = sorted([txn.sender_id, txn.receiver_id])
    db.execute(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update())
    sender, recipient = db.get(User, txn.sender_id), db.get(User, txn.receiver_id)
    db.refresh(sender)
    db.refresh(recipient)
    status = {"release": "completed", "cancel": "cancelled", "reject": "rejected"}[outcome]
    if outcome == "release" and recipient.balance + txn.amount > MAX_BALANCE:
        outcome, status, note = "reject", "rejected", "Recipient wallet limit reached"      # the money goes back instead
    if outcome == "release":
        recipient.balance += txn.amount
        _credit_message(db, txn, sender, recipient)
    else:
        sender.balance += txn.amount
    txn.status = status
    txn.decided_at = now or utcnow()
    txn.reviewed_by = reviewer.id if reviewer else None
    txn.review_note = (note or "")[:200] or None
    db.commit()
    return txn


def settle_due_holds(db: Session, now=None) -> int:
    """Release every hold whose time is up. Safe to call as often as you like (it does nothing twice)."""
    now = now or utcnow()
    due = db.scalars(select(Transaction).where(Transaction.status == "held", Transaction.release_at <= now)).all()
    for txn in due:
        _finish_hold(db, txn, "release", now=now)
    return len(due)


def cancel_hold(db: Session, user: User, txn_id: int) -> Transaction:
    """The sender changes their mind (or realises it is a scam) during the hold: the money comes straight back."""
    txn = db.get(Transaction, txn_id)
    if txn is None or txn.sender_id != user.id:
        raise WalletError("transaction_not_found", "Transaction not found", 404)
    if txn.status != "held":
        raise WalletError("not_cancellable", "Only a held transfer can be cancelled", 409)
    return _finish_hold(db, txn, "cancel")


def require_analyst(user: User) -> None:
    if user.role != "analyst":
        raise WalletError("forbidden", "This area is for fraud analysts only", 403)


def analyst_cases(db: Session, status: str = "held", limit: int = 50) -> list[dict]:
    q = select(Transaction).where(Transaction.risk_pct.is_not(None), Transaction.kind == "send_money")
    if status != "all":
        q = q.where(Transaction.status == status)
    rows = db.scalars(q.order_by(Transaction.risk_pct.desc(), Transaction.id.desc()).limit(max(1, min(limit, 200)))).all()
    out = []
    for t in rows:
        s, r = db.get(User, t.sender_id), db.get(User, t.receiver_id)
        ev = db.scalar(select(RiskEvent).where(RiskEvent.transaction_id == t.id))
        out.append({"id": t.id, "status": t.status, "amount": t.amount, "risk_pct": t.risk_pct, "risk_tier": t.risk_tier,
                    "scam_type": ev.scam_type if ev else None, "reasons": json.loads(ev.reasons_json) if ev else [],
                    "sender": {"name": s.name, "phone": s.phone}, "recipient": {"name": r.name, "phone": r.phone},
                    "created_at": t.created_at.isoformat(), "release_at": t.release_at.isoformat() if t.release_at else None,
                    "review_note": t.review_note})
    return out


def analyst_decide(db: Session, analyst: User, txn_id: int, approve: bool, note: str | None = None) -> Transaction:
    require_analyst(analyst)
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise WalletError("transaction_not_found", "Transaction not found", 404)
    if txn.status != "held":
        raise WalletError("already_decided", "This case is no longer waiting for a decision", 409)
    return _finish_hold(db, txn, "release" if approve else "reject", reviewer=analyst, note=note)


def _customer_recipient(db: Session, sender: User, recipient_phone: str) -> User:
    recipient = db.scalar(select(User).where(User.phone == recipient_phone))
    if recipient is None or recipient.role != "customer":
        raise WalletError("recipient_not_found", "No wallet customer found with this number", 404)
    if recipient.id == sender.id:
        raise WalletError("self_transfer", "You cannot send money to yourself")
    return recipient


def preview_send(db: Session, sender: User, recipient_phone: str, amount: int, behavior: dict | None = None,
                 safety_answers: list[dict] | None = None):
    """What Shield thinks of a transfer BEFORE the customer enters their PIN. No money moves, no PIN needed.
    With `safety_answers` it shows how the customer's answers changed the score."""
    _check_phone(recipient_phone)
    _check_amount(amount, MAX_SEND)
    recipient = _customer_recipient(db, sender, recipient_phone)
    if sender.balance < amount:
        raise WalletError("insufficient_balance", "You do not have enough balance", 400)
    return risk_hook.check_transfer(db, sender, recipient, amount, behavior, source="preview", answers=safety_answers), recipient


def send_money(db: Session, sender: User, recipient_phone: str, amount: int, pin: str,
               idempotency_key: str | None = None, behavior: dict | None = None,
               acknowledged_risk: bool = False, safety_answers: list[dict] | None = None) -> Transaction:
    _check_phone(recipient_phone)
    _check_amount(amount, MAX_SEND)
    again = _existing(db, sender, idempotency_key)
    if again:
        return again                                   # a retry of a payment that already went through
    verify_user_pin(db, sender, pin)
    recipient = _customer_recipient(db, sender, recipient_phone)
    # The server decides again here. It never trusts that the app already showed a preview.
    decision = risk_hook.check_transfer(db, sender, recipient, amount, behavior, source="send", answers=safety_answers)
    proceed = decision.action in ALLOWED_NOW or (decision.action in NEEDS_ACK and acknowledged_risk)
    if not proceed:
        raise RiskInterruption(decision)               # nothing has moved yet
    if decision.action == "hold_30min":                # the customer has seen the warning and confirmed: hold, do not send
        txn = _hold(db, "send_money", sender, recipient, amount, idempotency_key, decision.risk_pct, decision.tier)
    else:
        txn = _move(db, "send_money", sender, recipient, amount, idempotency_key, decision.risk_pct, decision.tier)
    if decision.event_id:
        event = db.get(RiskEvent, decision.event_id)
        if event and event.transaction_id is None:
            event.transaction_id = txn.id
            db.commit()
    lab.record(db, sender, recipient, txn, behavior)   # the Risk Lab keeps every real transfer; it can never change this payment
    return txn


def cash_out(db: Session, customer: User, agent_phone: str, amount: int, pin: str,
             idempotency_key: str | None = None) -> Transaction:
    """The customer hands over e-money; the agent hands over physical cash (outside the system)."""
    _check_phone(agent_phone)
    _check_amount(amount, MAX_SEND)
    again = _existing(db, customer, idempotency_key)
    if again:
        return again
    verify_user_pin(db, customer, pin)
    agent = db.scalar(select(User).where(User.phone == agent_phone))
    if agent is None or agent.role != "agent":
        raise WalletError("agent_not_found", "No agent found with this number", 404)
    return _move(db, "cash_out", customer, agent, amount, idempotency_key)


# ------------------------------------------------------------------ reports and inbox
def report_number(db: Session, reporter: User, phone: str, reason: str | None = None) -> Report:
    """A customer flags a number as suspicious. Reports feed the recipient-risk signals for future senders."""
    _check_phone(phone)
    target = db.scalar(select(User).where(User.phone == phone))
    if target is None:
        raise WalletError("recipient_not_found", "No wallet found with this number", 404)
    if target.id == reporter.id:
        raise WalletError("self_report", "You cannot report your own number")
    report = Report(reporter_id=reporter.id, reported_id=target.id, reason=(reason or "")[:200] or None)
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise WalletError("already_reported", "You have already reported this number", 409)
    return report


def inbox(db: Session, user: User, limit: int = 30) -> list[dict]:
    rows = db.scalars(select(SmsMessage).where(SmsMessage.user_id == user.id)
                      .order_by(SmsMessage.id.desc()).limit(max(1, min(limit, 100)))).all()
    return [{"id": m.id, "from": m.sender_label, "text": m.text, "official": m.official,
             "created_at": m.created_at.isoformat()} for m in rows]


def drop_fake_sms(db: Session, user: User, amount: int, claimed_number: str) -> SmsMessage:
    """DEMO ONLY: put a fake 'money received' message into a customer's inbox, like a scammer's SMS would."""
    _check_phone(claimed_number)
    _check_amount(amount, MAX_SEND)
    msg = SmsMessage(user_id=user.id, sender_label=claimed_number, kind="credit_claim", official=False,
                     claimed_amount=amount, claimed_number=claimed_number,
                     text=f"You have received Tk {amount:,} from {claimed_number}. Please return it, it was sent by mistake.")
    db.add(msg)
    db.commit()
    return msg


# ------------------------------------------------------------------ views
def user_public(user: User) -> dict:
    return {"id": user.id, "phone": user.phone, "name": user.name, "role": user.role, "balance": user.balance}


def history(db: Session, user: User, limit: int = 20) -> list[dict]:
    limit = max(1, min(limit, 100))
    rows = db.scalars(select(Transaction)
                      .where(or_(Transaction.sender_id == user.id, Transaction.receiver_id == user.id))
                      .order_by(Transaction.id.desc()).limit(limit)).all()
    out = []
    for t in rows:
        outgoing = t.sender_id == user.id
        other_id = t.receiver_id if outgoing else t.sender_id
        other = db.get(User, other_id) if other_id else None
        out.append({"id": t.id, "kind": t.kind, "direction": "out" if outgoing else "in", "amount": t.amount,
                    "status": t.status, "created_at": t.created_at.isoformat(),
                    "release_at": t.release_at.isoformat() if t.release_at and t.status == "held" else None,
                    "counterparty_name": other.name if other else None,
                    "counterparty_phone": other.phone if other else None})
    return out


def release_holds_now(db: Session, user: User) -> int:
    """DEMO ONLY: make this customer's holds end right now, so the 30-minute wait can be shown in seconds."""
    mine = db.scalars(select(Transaction).where(Transaction.sender_id == user.id, Transaction.status == "held")).all()
    for t in mine:
        t.release_at = utcnow() - timedelta(seconds=1)
    db.commit()
    return settle_due_holds(db)


def reset_demo(engine, session_factory, users: int = 1500, days: int = 60, log=lambda *_: None) -> dict:
    """DEMO ONLY: wipe the wallet database and build the demo world again (about 5 seconds)."""
    import pathlib
    import sys
    root = pathlib.Path(__file__).resolve().parents[1]
    for sub in ("simulator",):
        if str(root / sub) not in sys.path:
            sys.path.insert(0, str(root / sub))
    import seed_wallet                                     # the same script that is run from the command line
    from database import Base
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = session_factory()
    try:
        info = seed_wallet.seed(db, n_users=users, days=days, log=log)
    finally:
        db.close()
    return {"users": info["users"], "transactions": info["transactions"]}
