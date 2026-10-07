"""Web routes for the graded-risk model (mounted inside Shield).

    GET  /risk/graded/accounts    demo senders, recipients and ready-made stories
    GET  /risk/graded/catalogue   the 31 signals and why each one is in the model
    GET  /risk/graded/report      what the model was tested on and how it did
    POST /risk/graded             score one transfer and explain every signal

Advice only, like the rest of Shield: nothing here moves money.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from graded_risk import accounts
from graded_risk import catalogue as cat
from graded_risk import engine

router = APIRouter(prefix="/risk/graded", tags=["graded risk"])


class Live(BaseModel):
    """The live details of one payment (the rest comes from the two accounts)."""
    amount: float = Field(default=2000, ge=1, le=1_000_000)
    hour: float = Field(default=14, ge=0, lt=24, description="Hour of day, 0-23")
    on_call: int = Field(default=0, ge=0, le=1)
    hesitation_secs: float = Field(default=6, ge=0, le=3600)
    amount_edits: int = Field(default=0, ge=0, le=50)
    mins_since_credit: float = Field(default=2000, ge=0, le=100_000)
    new_device: int = Field(default=0, ge=0, le=1)
    sms_claim_mismatch: int = Field(default=0, ge=0, le=1)


class GradedRequest(BaseModel):
    sender_id: str
    recipient_id: str
    tx: Live = Live()
    mute_sides: list[str] = Field(default_factory=list, description="Treat a whole side as normal: sender, recipient, pair")
    mute_signals: list[str] = Field(default_factory=list, description="Treat individual signals as normal")


@router.get("/accounts")
def list_accounts():
    return {"senders": [accounts.public_sender(s) for s in accounts.SENDERS.values()],
            "recipients": [accounts.public_recipient(r) for r in accounts.RECIPIENTS.values()],
            "scenarios": accounts.SCENARIOS, "default_tx": accounts.DEFAULT_TX}


@router.get("/catalogue")
def catalogue():
    return {"sides": cat.SIDE_LABEL,
            "signals": [{"signal": f.name, "side": f.side, "label": f.label, "direction": f.direction, "why": f.why}
                        for f in cat.FEATURES_LIST]}


@router.get("/report")
def report():
    rep = engine.get_engine().report
    if rep is None:
        raise HTTPException(status_code=503, detail="No model report found; run shield-api/graded_risk/train.py")
    return rep


@router.post("")
def score(body: GradedRequest):
    sender = accounts.SENDERS.get(body.sender_id)
    recipient = accounts.RECIPIENTS.get(body.recipient_id)
    if sender is None or recipient is None:
        raise HTTPException(status_code=404, detail="Unknown demo account")
    features = accounts.build_features(sender, recipient, body.tx.model_dump())
    try:
        out = engine.get_engine().explain(features, body.mute_sides, body.mute_signals)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    out["sender"] = accounts.public_sender(sender)
    out["recipient"] = accounts.public_recipient(recipient)
    out["model_version"] = "graded-1"
    return out
