"""Builds the 31 signals of the graded-risk model for ONE real transfer, from the wallet's own records.

Twelve signals reuse the first model's builder (risk_features.py); the rest are built here. Golden rule as
everywhere: use only what existed strictly before `now`.

Where each signal comes from
 - ledger (computed live): amounts, hours, history, new payers, cash-out speed, how long money stays,
   cash-out agents, dormancy before a burst, equal-amount payments, amount against the recipient's usual
 - account profile (what upay knows about the account): SIM age, KYC level, wallets under one ID, shared
   device, SIM swap, district, contact circles
 - the request: hesitation, amount edits, phone call, new device
Accounts without a profile are treated as ordinary: nothing unusual is assumed.
"""
from __future__ import annotations

import bisect
import json
import math
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import risk_features
from models import AccountProfile, Transaction, User, utcnow

DONE = Transaction.status == "completed"
DHAKA = timedelta(hours=6)
IN_KINDS = ("send_money", "add_money")


def _profile(db: Session, user: User) -> dict:
    p = db.get(AccountProfile, user.id)
    age = (utcnow() - user.created_at).total_seconds() / 86400
    if p is None:
        return dict(district=None, sim_age_days=age + 365, kyc_level=2, wallets_per_nid=1, shared_device_wallets=0,
                    sim_swap_recent=False, circles=set())
    return dict(district=p.district, sim_age_days=p.sim_age_days if p.sim_age_days is not None else age + 365,
                kyc_level=p.kyc_level, wallets_per_nid=p.wallets_per_nid, shared_device_wallets=p.shared_device_wallets,
                sim_swap_recent=bool(p.sim_swap_recent), circles=set(json.loads(p.circles_json or "[]")))


def _usual_hour_distance(hours: list[float], hour_now: float) -> float | None:
    """Circular distance (0-12 hours) between now and the sender's usual hour, or None with too little history."""
    if len(hours) < 3:
        return None
    ang = [h / 24 * 2 * math.pi for h in hours]
    mean = math.atan2(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang)) % (2 * math.pi) / (2 * math.pi) * 24
    d = abs(hour_now - mean) % 24
    return min(d, 24 - d)


def _median_hold_minutes(db: Session, recipient: User, now: datetime) -> float:
    """How long money typically stays: minutes from each recent payment in to the next payment out of the wallet."""
    week = now - timedelta(days=7)
    ins = db.execute(select(Transaction.created_at).where(
        Transaction.receiver_id == recipient.id, Transaction.kind == "send_money", DONE,
        Transaction.created_at >= week, Transaction.created_at < now).order_by(Transaction.created_at.desc()).limit(30)).scalars().all()
    if not ins:
        return 600.0                                              # nothing recent: the typical value
    outs = sorted(db.execute(select(Transaction.created_at).where(
        Transaction.sender_id == recipient.id, Transaction.kind.in_(("send_money", "cash_out")), DONE,
        Transaction.created_at >= week, Transaction.created_at < now)).scalars().all())
    waits = []
    for t in ins:
        i = bisect.bisect_right(outs, t)
        waits.append(min((outs[i] - t).total_seconds() / 60.0, 10080.0) if i < len(outs) else 10080.0)
    waits.sort()
    return float(waits[len(waits) // 2])


def build_graded_features(db: Session, sender: User, recipient: User, amount: int, behavior: dict | None = None,
                          now: datetime | None = None, balance_before: int | None = None, v1: dict | None = None) -> dict:
    now = now or utcnow()
    b = behavior or {}
    if v1 is None:
        v1 = risk_features.build_live_features(db, sender, recipient, amount, b, now=now, balance_before=balance_before)
    sp, rp = _profile(db, sender), _profile(db, recipient)
    day_ago = now - timedelta(days=1)

    # sender: how unusual is this hour for this person?
    past = db.execute(select(Transaction.created_at).where(
        Transaction.sender_id == sender.id, Transaction.kind == "send_money", DONE, Transaction.created_at < now)
        .order_by(Transaction.created_at.desc()).limit(60)).scalars().all()
    local = lambda t: ((t + DHAKA).hour * 60 + (t + DHAKA).minute) / 60.0   # noqa: E731
    dist = _usual_hour_distance([local(t) for t in past], local(now))
    hour_unusual = 0.4 if dist is None else min(1.0, 0.1 + dist / 9 * 0.9)

    # recipient: dormancy before this burst, cash-out agents, how long money stays
    first_recent = db.scalar(select(func.min(Transaction.created_at)).where(
        Transaction.receiver_id == recipient.id, Transaction.kind == "send_money", DONE,
        Transaction.created_at >= day_ago, Transaction.created_at < now))
    dormant = 0.0
    if first_recent is not None:
        last_before = db.scalar(select(func.max(Transaction.created_at)).where(
            (Transaction.receiver_id == recipient.id) | (Transaction.sender_id == recipient.id), DONE,
            Transaction.created_at < day_ago))
        if last_before is not None:
            dormant = max(0.0, (first_recent - last_before).total_seconds() / 86400)
    agents = db.scalar(select(func.count(func.distinct(Transaction.receiver_id))).where(
        Transaction.sender_id == recipient.id, Transaction.kind == "cash_out", DONE,
        Transaction.created_at >= now - timedelta(days=7), Transaction.created_at < now)) or 0

    # the pair: amount against what the recipient usually receives, equal-amount payments
    prior_in = db.execute(select(Transaction.amount).where(
        Transaction.receiver_id == recipient.id, Transaction.kind == "send_money", DONE,
        Transaction.created_at < now).order_by(Transaction.created_at.desc()).limit(60)).scalars().all()
    if len(prior_in) >= 3:
        s = sorted(prior_in)
        typical = s[len(s) // 2]
        vs_typical = max(-1.0, min(4.0, math.log(max(amount, 1) / max(typical, 1))))
    else:
        vs_typical = 0.0
    recent_amounts = db.execute(select(Transaction.amount).where(
        Transaction.receiver_id == recipient.id, Transaction.kind == "send_money", DONE,
        Transaction.created_at >= day_ago, Transaction.created_at < now)).scalars().all()
    same_amount = sum(1 for a in recent_amounts if abs(a - amount) <= 0.08 * amount)

    districts_differ = bool(sp["district"] and rp["district"] and sp["district"] != rp["district"])
    age_days = max(1.0, min(2000.0, (now - recipient.created_at).total_seconds() / 86400))
    return {
        "s_amount_zscore": float(max(-3.0, min(6.0, v1["amount_zscore"]))),
        "s_balance_share": float(v1["balance_share"]),
        "s_hour_unusual": float(hour_unusual),
        "s_log_mins_since_credit": float(min(9.3, v1["log_mins_since_incoming"])),
        "s_hesitation_secs": float(max(1.0, min(300.0, v1["hesitation_secs"]))),
        "s_amount_edits": float(v1["amount_edits"]),
        "s_on_call": float(v1["on_call"]),
        "s_history_count": float(v1["sender_history_count"]),
        "s_new_device": float(bool(b.get("new_device", False))),
        "s_round_amount": float(v1["is_round_amount"]),
        "r_age_days": float(age_days),
        "r_sim_age_days": float(max(1.0, min(4000.0, rp["sim_age_days"]))),
        "r_kyc_level": float(rp["kyc_level"]),
        "r_wallets_per_nid": float(rp["wallets_per_nid"]),
        "r_shared_device_wallets": float(rp["shared_device_wallets"]),
        "r_first_time_senders_24h": float(v1["first_time_senders_24h"]),
        "r_inflow_count_24h": float(v1["recipient_inflow_count_24h"]),
        "r_outflow_ratio_24h": float(v1["recipient_outflow_ratio_24h"]),
        "r_median_hold_mins": float(max(1.0, _median_hold_minutes(db, recipient, now))),
        "r_cashout_agents_7d": float(agents),
        "r_dormant_days": float(min(400.0, dormant)),
        "r_report_count": float(v1["report_count"]),
        "r_report_rate": float(v1["report_rate"]),
        "r_prior_txns": float(v1["recipient_prior_txns"]),
        "r_sim_swap_recent": float(rp["sim_swap_recent"]),
        "i_first_time_recipient": float(v1["is_first_time_recipient"]),
        "i_amount_vs_recipient_typical": float(vs_typical),
        "i_same_amount_inflows_24h": float(same_amount),
        "i_mutual_contacts": float(len(sp["circles"] & rp["circles"])),
        "i_geo_mismatch": float(districts_differ),
        "i_sms_claim_mismatch": float(v1["claim_ledger_mismatch"]),
    }
