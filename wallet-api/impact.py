"""Business and customer impact, measured from what really happened in the wallet.

For every transfer that Shield flagged (high or very-high risk when the customer first previewed it) we follow what the
customer did next:
    walked_away          saw the warning and never sent the money
    cancelled            confirmed, was held, then cancelled and got every taka back
    rejected             held, then stopped by a fraud analyst (refunded)
    released_after_hold  held, nobody stopped it, the money was released after the hold
    sent_after_warning   saw the warning and sent the money anyway
    on_hold              still waiting

Honest limit: the wallet cannot know for certain which flagged transfers were scams, so the money that did not reach a
flagged recipient is called "kept back", not "scam stopped". Offline, on synthetic data where the truth is known, the
model report shows how many of the flagged transfers were really fraud.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Report, RiskEvent, Transaction, User, utcnow

MATCH_WINDOW = timedelta(minutes=30)       # a send counts as the follow-up to a preview if it happens within 30 minutes
FLAGGED = ("high", "very_high")
KEPT_BACK = ("walked_away", "cancelled", "rejected")
METRICS_FILE = pathlib.Path(__file__).resolve().parents[1] / "reports" / "module1" / "metrics.json"


def _outcome(db: Session, event: RiskEvent) -> tuple[str, int]:
    txn = db.scalar(select(Transaction).where(
        Transaction.sender_id == event.sender_id, Transaction.receiver_id == event.recipient_id,
        Transaction.kind == "send_money", Transaction.amount == event.amount,
        Transaction.created_at >= event.created_at, Transaction.created_at <= event.created_at + MATCH_WINDOW,
    ).order_by(Transaction.id))
    if txn is None:
        return "walked_away", event.amount
    if txn.status == "held":
        return "on_hold", txn.amount
    if txn.status == "cancelled":
        return "cancelled", txn.amount
    if txn.status == "rejected":
        return "rejected", txn.amount
    return ("released_after_hold" if txn.release_at is not None else "sent_after_warning"), txn.amount


def impact(db: Session, hours: int = 168, now: datetime | None = None) -> dict:
    now = now or utcnow()
    since = now - timedelta(hours=max(1, hours))
    previews = db.scalars(select(RiskEvent).where(RiskEvent.source == "preview", RiskEvent.created_at >= since)).all()

    tiers = {"low": 0, "note": 0, "high": 0, "very_high": 0}
    outcomes = {k: {"count": 0, "bdt": 0} for k in
                ("walked_away", "cancelled", "rejected", "on_hold", "released_after_hold", "sent_after_warning")}
    for e in previews:
        tiers[e.tier] = tiers.get(e.tier, 0) + 1
        if e.tier in FLAGGED:
            name, amount = _outcome(db, e)
            outcomes[name]["count"] += 1
            outcomes[name]["bdt"] += amount

    flagged = sum(tiers[t] for t in FLAGGED)
    heeded = sum(outcomes[k]["count"] for k in KEPT_BACK)
    kept_back = sum(outcomes[k]["bdt"] for k in KEPT_BACK)
    total_events = db.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.created_at >= since)) or 0
    shield_ok = db.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.created_at >= since, RiskEvent.shield_available.is_(True))) or 0
    return {
        "window_hours": hours,
        "checks": len(previews),
        "tiers": tiers,
        "flagged": flagged,
        "friction_rate": round(flagged / len(previews), 4) if previews else 0.0,
        "outcomes": outcomes,
        "heeded": heeded,
        "heeded_rate": round(heeded / flagged, 4) if flagged else 0.0,
        "kept_back_bdt": kept_back,
        "released_bdt": outcomes["released_after_hold"]["bdt"] + outcomes["sent_after_warning"]["bdt"],
        "on_hold_bdt": outcomes["on_hold"]["bdt"],
        "open_cases": db.scalar(select(func.count()).select_from(Transaction).where(Transaction.status == "held")) or 0,
        "reports": db.scalar(select(func.count()).select_from(Report).where(Report.created_at >= since)) or 0,
        "reported_wallets": db.scalar(select(func.count(func.distinct(Report.reported_id))).where(Report.created_at >= since)) or 0,
        "shield_available_rate": round(shield_ok / total_events, 4) if total_events else 1.0,
    }


def model_report(path: pathlib.Path = METRICS_FILE) -> dict | None:
    """The offline test results (synthetic test period, truth known), trimmed for the dashboard."""
    try:
        m = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    op = m["operating_points"]["high"]
    return {
        "test_transfers": m["data"]["test_rows"], "test_fraud": m["data"]["test_fraud"],
        "fraud_caught_pct": op["fraud_recall_count"], "fraud_value_caught_pct": op["fraud_recall_value"],
        "genuine_disturbed_pct": op["genuine_friction_rate"], "precision": op["precision"],
        "ranking": {k: {"pr_auc": v["pr_auc"], "recall_at_2pct_friction": v["recall_at_2pct_friction"]} for k, v in m["ranking"].items()},
        "by_scam_type": m["recall_by_scam_type_at_high_tier"],
        "calibration_error": m["calibration"]["ece_calibrated"],
        "impact_by_heeding_rate": m["impact_by_heeding_rate"],
        "evasion": m["evasion_fraud_recall_at_high_tier"],
        "latency_ms": m["latency_ms_per_transfer"],
    }
