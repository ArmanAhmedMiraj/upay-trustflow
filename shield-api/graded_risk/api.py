"""Web routes for the graded-risk model (mounted inside Shield).

    GET  /risk/graded/catalogue   the 31 signals and why each one is in the model
    GET  /risk/graded/report      what the model was tested on and how it did
    POST /risk/graded/score-features   score one real transfer from its 31 signals and explain every signal

Advice only, like the rest of Shield: nothing here moves money.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from graded_risk import catalogue as cat
from graded_risk import engine

router = APIRouter(prefix="/risk/graded", tags=["graded risk"])


class FeaturesRequest(BaseModel):
    """The 31 signals of one real transfer, built by the wallet from its own records."""
    features: dict[str, float]
    mute_sides: list[str] = Field(default_factory=list, description="Treat a whole side as normal: sender, recipient, pair")
    mute_signals: list[str] = Field(default_factory=list, description="Treat individual signals as normal")


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


@router.post("/score-features")
def score_features(body: FeaturesRequest):
    """Score one transfer from its 31 signals and explain every signal."""
    names = set(cat.FEATURE_NAMES)
    got = set(body.features)
    if got != names:
        raise HTTPException(status_code=422, detail=f"expected exactly the 31 signals; missing {sorted(names - got)[:3]}, unknown {sorted(got - names)[:3]}")
    if any(v != v or abs(v) > 1e9 for v in body.features.values()):
        raise HTTPException(status_code=422, detail="signals must be finite numbers")
    try:
        out = engine.get_engine().explain(body.features, body.mute_sides, body.mute_signals)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    out["model_version"] = "graded-1"
    return out
