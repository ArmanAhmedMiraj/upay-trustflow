"""The Risk Lab's record of REAL transfers: written when a transfer happens, never pre-filled.

`record` runs right after a transfer is created. It builds the 31 signals from the wallet's own records, asks
Shield's graded-risk model for the score, and saves both. It can never stop or change a payment: any failure is
logged and the payment goes on exactly as before.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

import lab_features
import shield_client
from models import LabEntry, Transaction, User

log = logging.getLogger("wallet.lab")
DHAKA = timedelta(hours=6)


def record(db: Session, sender: User, recipient: User, txn: Transaction, behavior: dict | None) -> LabEntry | None:
    try:
        features = lab_features.build_graded_features(db, sender, recipient, txn.amount, behavior, now=txn.created_at,
                                                      balance_before=sender.balance + txn.amount)
        result = None
        try:
            result = shield_client.lab_call("POST", "/risk/graded/score-features", {"features": features})
        except Exception as exc:    # Shield off or slow: keep the signals, score later when the analyst opens it
            log.info("Risk Lab: graded score unavailable for transaction %s (%s)", txn.id, exc)
        entry = LabEntry(transaction_id=txn.id, sender_id=sender.id, recipient_id=recipient.id, amount=txn.amount,
                         status=txn.status, created_at=txn.created_at, features_json=json.dumps(features),
                         risk_pct=result["risk_pct"] if result else None, tier=result["tier"] if result else None)
        db.add(entry)
        db.commit()
        return entry
    except Exception:
        db.rollback()
        log.exception("Risk Lab could not record transaction %s; the payment is not affected", getattr(txn, "id", None))
        return None


def _dhaka_to_utc(text: str | None) -> datetime | None:
    """The analyst types Bangladesh time (UTC+6); the database holds UTC."""
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "")[:19]) - DHAKA


def list_entries(db: Session, sender_phone: str | None = None, recipient_phone: str | None = None, name: str | None = None,
                 since: str | None = None, until: str | None = None, limit: int = 100) -> list[dict]:
    S, R = aliased(User), aliased(User)
    q = select(LabEntry, S, R).join(S, S.id == LabEntry.sender_id).join(R, R.id == LabEntry.recipient_id)
    if sender_phone:
        q = q.where(S.phone == sender_phone)
    if recipient_phone:
        q = q.where(R.phone == recipient_phone)
    if name and name.strip():
        like = f"%{name.strip()}%"
        q = q.where(or_(S.name.like(like), R.name.like(like)))
    lo, hi = _dhaka_to_utc(since), _dhaka_to_utc(until)
    if lo:
        q = q.where(LabEntry.created_at >= lo)
    if hi:
        q = q.where(LabEntry.created_at <= hi)
    rows = db.execute(q.order_by(LabEntry.created_at.desc(), LabEntry.id.desc()).limit(max(1, min(limit, 500)))).all()
    return [entry_out(e, s, r) for e, s, r in rows]


def entry_out(e: LabEntry, s: User, r: User) -> dict:
    return {"id": e.id, "transaction_id": e.transaction_id, "created_at": e.created_at.isoformat(), "amount": e.amount,
            "status": e.status, "risk_pct": e.risk_pct, "tier": e.tier,
            "sender": {"name": s.name, "phone": s.phone}, "recipient": {"name": r.name, "phone": r.phone}}


def filter_options(db: Session) -> dict:
    """The numbers and names that actually appear in recorded transfers (for the dropdowns)."""
    S, R = aliased(User), aliased(User)
    rows = db.execute(select(S.name, S.phone, R.name, R.phone).select_from(LabEntry)
                      .join(S, S.id == LabEntry.sender_id).join(R, R.id == LabEntry.recipient_id)).all()
    senders = {p: n for n, p, _, _ in rows}
    recips = {p: n for _, _, n, p in rows}
    pack = lambda d: [{"phone": p, "name": n} for p, n in sorted(d.items(), key=lambda kv: kv[1])]   # noqa: E731
    return {"senders": pack(senders), "recipients": pack(recips), "total": len(rows)}


def get_entry(db: Session, entry_id: int) -> tuple[LabEntry, User, User] | None:
    e = db.get(LabEntry, entry_id)
    if e is None:
        return None
    return e, db.get(User, e.sender_id), db.get(User, e.recipient_id)
