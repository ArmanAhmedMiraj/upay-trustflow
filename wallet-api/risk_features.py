"""Builds Shield's 23 signals for ONE transfer, live, from the wallet database.

This mirrors shield-api/transfer_risk/features.py, which builds the same signals in bulk for training.
If the two ever disagree, the model sees different numbers in the demo than it learned from ("train/serve
skew"). tests/test_risk_features.py replays a whole simulation through both and checks they match.

Golden rule, as in training: use ONLY what existed strictly before `now`.

Definitions (kept identical to training)
 - sender history = the sender's earlier send_money transfers (cash-outs to agents are a different habit)
 - "money arrived" = money received by transfer plus add_money top-ups
 - recipient cash-out speed = cash-outs by the recipient (training models outflows as cash-outs)
 - hours are taken in Bangladesh time (UTC+6). Note: the signal compares a transfer's hour with the SAME
   sender's own earlier hours in 3-hour blocks, so a shift of exactly 6 hours changes nothing; a wrong
   offset that is not a multiple of 3 hours would change the signal (the parity test catches that).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Report, SmsMessage, Transaction, User, utcnow

DHAKA = timedelta(hours=6)
DONE = Transaction.status == "completed"      # held, cancelled and rejected transfers never happened, so they are not history
LINK_KINDS = ("send_money", "cash_out")          # transfers that create a sender -> recipient relationship
LEDGER_WINDOW = timedelta(minutes=360)           # a claimed credit must appear in the ledger within 6 hours
DEFAULT_BEHAVIOR = {"hesitation_secs": 7.0, "amount_edits": 0, "on_call": False}   # typical customer, if the app sends none


def _clip(x: float, lo: float, hi: float) -> float:
    return float(min(max(x, lo), hi))


def build_live_features(db: Session, sender: User, recipient: User, amount: int, behavior: dict | None = None,
                        now: datetime | None = None, balance_before: int | None = None,
                        sms_window_minutes: int = 360) -> dict:
    now = now or utcnow()
    b = {**DEFAULT_BEHAVIOR, **(behavior or {})}
    balance = sender.balance if balance_before is None else balance_before

    # ------------------------------------------------ Group A: the sender's own habits
    prior = db.execute(select(Transaction.amount, Transaction.created_at)
                       .where(Transaction.sender_id == sender.id, Transaction.kind == "send_money", DONE,
                              Transaction.created_at < now)).all()
    n = len(prior)
    logs = [math.log(a) for a, _ in prior]
    cs, css = sum(logs), sum(v * v for v in logs)
    mu0, sd0, k0 = math.log(700.0), 0.7, 3.0                        # shrink towards a typical sender while history is short
    mean = (cs + k0 * mu0) / (n + k0)
    var = (css + k0 * (sd0 ** 2 + mu0 ** 2)) / (n + k0) - mean ** 2
    zscore = (math.log(amount) - mean) / math.sqrt(max(var, 0.12))

    local_hour = ((now + DHAKA).hour * 60 + (now + DHAKA).minute + (now + DHAKA).second / 60) / 60
    bucket = int(local_hour // 3)
    same_bucket = sum(1 for _, t in prior if int(((t + DHAKA).hour * 60 + (t + DHAKA).minute + (t + DHAKA).second / 60) / 60 // 3) == bucket)
    hour_unusual = 1.0 - (same_bucket + 1.0) / (n + 8.0)

    seen_before = db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.sender_id == sender.id, Transaction.receiver_id == recipient.id,
        Transaction.kind.in_(LINK_KINDS), DONE, Transaction.created_at < now))

    last_in = db.scalar(select(func.max(Transaction.created_at)).where(
        Transaction.receiver_id == sender.id, Transaction.kind.in_(("send_money", "add_money")), DONE,
        Transaction.created_at < now))
    mins_since_in = 10080.0 if last_in is None else min((now - last_in).total_seconds() / 60.0, 10080.0)

    # ------------------------------------------------ Group B: the recipient wallet
    day_ago = now - timedelta(days=1)
    to_recipient = (Transaction.receiver_id == recipient.id, Transaction.kind.in_(LINK_KINDS), DONE, Transaction.created_at < now)
    first_seen = (select(Transaction.sender_id, func.min(Transaction.created_at).label("first"))
                  .where(*to_recipient).group_by(Transaction.sender_id).subquery())
    first_time_senders = db.scalar(select(func.count()).select_from(first_seen).where(first_seen.c.first >= day_ago))
    inflow_count = db.scalar(select(func.count()).select_from(Transaction).where(*to_recipient, Transaction.created_at >= day_ago))
    inflow_amount = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(*to_recipient, Transaction.created_at >= day_ago))
    prior_txns = min(db.scalar(select(func.count()).select_from(Transaction).where(*to_recipient)), 5000)
    outflow_amount = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.sender_id == recipient.id, Transaction.kind == "cash_out", DONE,
        Transaction.created_at >= day_ago, Transaction.created_at < now))
    outflow_ratio = min(outflow_amount / max(inflow_amount, 1), 3.0) if inflow_amount > 0 else 0.0
    reports = db.scalar(select(func.count()).select_from(Report).where(Report.reported_id == recipient.id, Report.created_at < now))

    # ------------------------------------------------ Group C: the story check (SMS claim against the ledger)
    claim = _pick_claim(db, sender, recipient, now, timedelta(minutes=sms_window_minutes))
    claims = claim is not None
    mentions = claims and claim.claimed_number == recipient.phone
    confirms = False
    if claims:
        confirms = db.scalar(select(func.count()).select_from(Transaction).join(User, User.id == Transaction.sender_id).where(
            Transaction.receiver_id == sender.id, User.phone == claim.claimed_number,
            Transaction.amount == claim.claimed_amount, Transaction.kind.in_(("send_money", "add_money")), DONE,
            Transaction.created_at >= now - LEDGER_WINDOW, Transaction.created_at < now)) > 0
    mismatch = claims and not confirms

    return {
        "amount_zscore": _clip(zscore, -10, 30),
        "balance_share": _clip(amount / max(balance, 1), 0, 1),
        "is_first_time_recipient": int(seen_before == 0),
        "is_round_amount": int(amount % 500 == 0 and amount >= 500),
        "hour_unusual": _clip(hour_unusual, 0, 1),
        "log_mins_since_incoming": _clip(math.log1p(mins_since_in), 0, 12),
        "hesitation_secs": _clip(float(b["hesitation_secs"]), 0, 3600),
        "amount_edits": int(_clip(b["amount_edits"], 0, 50)),
        "on_call": int(bool(b["on_call"])),
        "sender_history_count": n,
        "recipient_age_days": _clip((now - recipient.created_at).total_seconds() / 86400, 0, 400),
        "first_time_senders_24h": int(first_time_senders),
        "recipient_inflow_count_24h": int(inflow_count),
        "recipient_outflow_ratio_24h": _clip(outflow_ratio, 0, 3),
        "recipient_prior_txns": int(prior_txns),
        "report_count": int(reports),
        "report_rate": float(reports / (prior_txns + 5.0)),
        "sms_claims_credit": int(claims),
        "sms_mentions_recipient": int(mentions),
        "ledger_confirms_credit": int(confirms),
        "claim_ledger_mismatch": int(mismatch),
        "claim_mismatch_on_recipient": int(mismatch and mentions),
        "sms_official_sender": int(claims and bool(claim.official)),
    }


def _pick_claim(db: Session, sender: User, recipient: User, now: datetime, window: timedelta) -> SmsMessage | None:
    """The 'money received' SMS that matters for this transfer, or None.

    Official upay credit messages are written by the ledger itself, so they cannot be false. They only
    count when they name the person being paid (the 'please send it back' situation). Any other
    'money received' message is an unverified claim and is checked against the ledger.
    """
    rows = db.scalars(select(SmsMessage).where(
        SmsMessage.user_id == sender.id, SmsMessage.kind == "credit_claim",
        SmsMessage.created_at < now, SmsMessage.created_at >= now - window).order_by(SmsMessage.created_at.desc())).all()
    candidates = [m for m in rows if (not m.official) or m.claimed_number == recipient.phone]
    about_recipient = [m for m in candidates if m.claimed_number == recipient.phone]
    return (about_recipient or candidates or [None])[0]
