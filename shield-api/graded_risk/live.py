"""Putting the graded model on the live payment path, next to the first model.

The wallet sends BOTH sets of signals for a real transfer: the 23 of the first model and the 31 of the graded model.
Shield scores both and keeps the one that is MORE worried (higher tier; the higher percentage on a tie). So adding the
graded model can only make Shield more careful, never less: whatever the first model caught, it still catches.

The first model cannot see an account's SIM age, ID checks, wallets under one ID or shared phone, so a rented-SIM
mule account looks ordinary to it. The graded model sees those, which is why the demo contacts reach different levels.
"""
from __future__ import annotations

import math

import numpy as np

from graded_risk import catalogue as cat
from graded_risk import engine

RANK = {"low": 0, "note": 1, "high": 2, "very_high": 3}
MODEL_VERSION = "v1+graded-1"


def check_signals(features: dict) -> None:
    """The graded signals must be exactly the 31 known names with finite numbers."""
    names, got = set(cat.FEATURE_NAMES), set(features)
    if got != names:
        raise ValueError(f"expected exactly the 31 graded signals; missing {sorted(names - got)[:3]}, unknown {sorted(got - names)[:3]}")
    if any((not isinstance(v, (int, float))) or v != v or abs(v) > 1e9 for v in features.values()):
        raise ValueError("graded signals must be finite numbers")


def _reasons(explained: dict, k: int = 4) -> list[dict]:
    up = [r for r in explained["contributions"] if r["present"] and not r["muted"] and r["points"] > 0.3]
    up.sort(key=lambda r: -r["points"])
    total = sum(r["points"] for r in up) or 1.0
    return [{"source": "model", "feature": r["signal"], "text": r["text"], "share_pct": round(100 * r["points"] / total)}
            for r in up[:k]]


def combine(v1: dict, graded_features: dict, v1_features: dict, art) -> dict:
    """`v1` is the first model's result. Returns it unchanged, or replaced by the graded result when that is more worried."""
    check_signals(graded_features)
    g = engine.get_engine().explain(graded_features)
    worse = (RANK[g["tier"]], g["risk_pct"]) > (RANK[v1["tier"]], float(v1["risk_pct"]))
    out = dict(v1)
    out["graded_risk_pct"], out["graded_tier"] = g["risk_pct"], g["tier"]
    if not worse:
        return out
    out.update(risk_pct=int(round(g["risk_pct"])), tier=g["tier"], action=g["action"], model_version=MODEL_VERSION,
               reasons=list(v1["reasons"]) + [r for r in _reasons(g) if r["feature"] not in {x["feature"] for x in v1["reasons"]}])
    if g["tier"] in ("high", "very_high") and out.get("scam_type") is None and art.scam_booster is not None:
        import pandas as pd
        from features import FEATURES
        probs = art.scam_booster.predict(pd.DataFrame([{f: v1_features[f] for f in FEATURES}])[FEATURES])[0]
        out["scam_type"] = art.scam_classes[int(np.argmax(probs))]
    return out


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def refine(first: dict, graded_features: dict, answers: dict[str, str], safety) -> dict:
    """The safety-check answers applied to the graded model's own score (same fixed, capped log-odds steps as before)."""
    asked = {q["id"]: q for q in safety.questions_for(first["scam_type"])}
    unknown = set(answers) - set(asked)
    if unknown:
        raise ValueError(f"unknown question ids: {sorted(unknown)}")
    bad = {k: v for k, v in answers.items() if v not in safety.ANSWERS}
    if bad:
        raise ValueError(f"answers must be one of {safety.ANSWERS}: {bad}")
    steps = [{"question_id": q, "answer": a, "log_odds_change": safety._delta(asked[q], a)} for q, a in answers.items()]
    total = float(np.clip(sum(s["log_odds_change"] for s in steps), safety.MAX_TOTAL_DROP, safety.MAX_TOTAL_RISE))
    eng = engine.get_engine()
    after = 1.0 / (1.0 + math.exp(-(_logit(eng.risk(graded_features)) + total)))
    tier_after = eng.tier(after)
    return {"risk_before_pct": first["risk_pct"], "risk_after_pct": int(round(100 * after)), "tier_before": first["tier"],
            "tier_after": tier_after, "action_after": safety.ACTION_AFTER_CHECK[tier_after], "total_log_odds_change": round(total, 3),
            "steps": steps, "scam_type": first["scam_type"], "reasons": first["reasons"]}
