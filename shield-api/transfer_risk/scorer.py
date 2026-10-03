"""Scores a transfer: risk %, tier, action, likely scam type and reasons.

Pipeline for every transfer:
    features -> LightGBM -> calibration -> rules (minimum risk) -> tier -> action

Artifacts are stored in portable formats (LightGBM text model + JSON), so the
scorer needs only numpy and lightgbm at run time.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

import rules
from features import FEATURES

ARTIFACT_DIR = pathlib.Path(__file__).parent / "artifacts"

ACTIONS = {
    "low": "allow",
    "note": "allow_with_note",
    "high": "safety_check",
    "very_high": "hold_30min",
}
TIER_ORDER = ["low", "note", "high", "very_high"]


@dataclass
class Artifacts:
    booster: lgb.Booster
    cal_x: np.ndarray
    cal_y: np.ndarray
    tiers: dict
    scam_booster: lgb.Booster | None
    scam_classes: list[str]


def load_artifacts(directory: pathlib.Path = ARTIFACT_DIR) -> Artifacts:
    cal = json.loads((directory / "calibrator.json").read_text())
    tiers = json.loads((directory / "tiers.json").read_text())
    scam_path = directory / "scam_type.txt"
    classes = json.loads((directory / "scam_type_classes.json").read_text()) if scam_path.exists() else []
    return Artifacts(
        booster=lgb.Booster(model_file=str(directory / "model.txt")),
        cal_x=np.array(cal["x"]), cal_y=np.array(cal["y"]), tiers=tiers,
        scam_booster=lgb.Booster(model_file=str(scam_path)) if scam_path.exists() else None,
        scam_classes=classes,
    )


def calibrate(art: Artifacts, raw: np.ndarray) -> np.ndarray:
    return np.interp(raw, art.cal_x, art.cal_y)


def tier_of(risk: np.ndarray, tiers: dict) -> np.ndarray:
    out = np.full(len(risk), "low", dtype=object)
    out[risk >= tiers["note"]] = "note"
    out[risk >= tiers["high"]] = "high"
    out[risk >= tiers["very_high"]] = "very_high"
    return out


def score_frame(art: Artifacts, df: pd.DataFrame) -> pd.DataFrame:
    """Score a table of features. Used for evaluation and for batch scoring."""
    model_risk = calibrate(art, art.booster.predict(df[FEATURES]))
    floor = rules.floor_frame(df, min_floor=art.tiers["very_high"])
    risk = np.maximum(model_risk, floor)
    return pd.DataFrame({"model_risk": model_risk, "rule_floor": floor, "risk": risk,
                         "tier": tier_of(risk, art.tiers)}, index=df.index)


# --------------------------------------------------------------------- reasons
REASON_TEXT = {
    "amount_zscore": lambda v: "Amount is much larger than this customer's usual transfers",
    "balance_share": lambda v: f"Sending {v:.0%} of the wallet balance",
    "is_first_time_recipient": lambda v: "First transfer to this number",
    "is_round_amount": lambda v: "Round amount",
    "hour_unusual": lambda v: "Unusual time of day for this customer",
    "log_mins_since_incoming": lambda v: f"Sending soon after receiving money (about {np.expm1(v):.0f} minutes)",
    "hesitation_secs": lambda v: f"Long hesitation on the confirm screen ({v:.0f} seconds)",
    "amount_edits": lambda v: f"Amount was changed {int(v)} times before sending",
    "on_call": lambda v: "Customer is on a phone call while sending",
    "sender_history_count": lambda v: "Customer has little transfer history",
    "recipient_age_days": lambda v: f"Recipient wallet is only {v:.0f} days old",
    "first_time_senders_24h": lambda v: f"Recipient received first payments from {int(v)} different people in 24 hours",
    "recipient_inflow_count_24h": lambda v: f"Recipient received {int(v)} payments in the last 24 hours",
    "recipient_outflow_ratio_24h": lambda v: f"{v:.0%} of the money this wallet received in 24 hours is already cashed out",
    "recipient_prior_txns": lambda v: "Recipient wallet has very little transaction history",
    "report_count": lambda v: f"Recipient has been reported {int(v)} times",
    "report_rate": lambda v: "Recipient has an unusually high share of reports compared with payments received",
    "sms_claims_credit": lambda v: "An SMS claims that money was received",
    "sms_mentions_recipient": lambda v: "That SMS names the number you are paying",
    "ledger_confirms_credit": lambda v: "The ledger does not confirm the claimed credit",
    "claim_ledger_mismatch": lambda v: "An SMS claim does not match the ledger",
    "claim_mismatch_on_recipient": lambda v: "A false 'money received' SMS names the recipient",
    "sms_official_sender": lambda v: "The credit SMS did not come from the official upay sender",
}


# A reason is shown only when the signal is really present (not just "slightly above average").
PRESENT = {
    "amount_zscore": lambda v: v > 1.5,
    "balance_share": lambda v: v > 0.5,
    "is_first_time_recipient": lambda v: v >= 1,
    "is_round_amount": lambda v: v >= 1,
    "hour_unusual": lambda v: v > 0.93,
    "log_mins_since_incoming": lambda v: np.expm1(v) < 60,
    "hesitation_secs": lambda v: v > 20,
    "amount_edits": lambda v: v >= 2,
    "on_call": lambda v: v >= 1,
    "sender_history_count": lambda v: v < 5,
    "recipient_age_days": lambda v: v < 30,
    "first_time_senders_24h": lambda v: v >= 3,
    "recipient_inflow_count_24h": lambda v: v >= 5,
    "recipient_outflow_ratio_24h": lambda v: v >= 0.5,
    "recipient_prior_txns": lambda v: v < 5,
    "report_count": lambda v: v >= 1,
    "report_rate": lambda v: v > 0.1,
    "sms_claims_credit": lambda v: v >= 1,
    "sms_mentions_recipient": lambda v: v >= 1,
    "ledger_confirms_credit": lambda v: False,
    "claim_ledger_mismatch": lambda v: v >= 1,
    "claim_mismatch_on_recipient": lambda v: v >= 1,
    "sms_official_sender": lambda v: False,
}


def _top_reasons(art: Artifacts, row: pd.DataFrame, k: int = 4) -> list[dict]:
    """The signals that pushed this transfer's risk up the most (model contributions, TreeSHAP)."""
    contrib = art.booster.predict(row[FEATURES], pred_contrib=True)[0][:-1]
    pos = [(f, c) for f, c in zip(FEATURES, contrib) if c > 0.15 and PRESENT[f](float(row[f].iloc[0]))]
    pos.sort(key=lambda x: -x[1])
    total = sum(c for _, c in pos) or 1.0
    return [{"source": "model", "feature": f, "text": REASON_TEXT[f](float(row[f].iloc[0])),
             "share_pct": round(100 * c / total)} for f, c in pos[:k]]


def score_transfer(features: dict, art: Artifacts | None = None) -> dict:
    """Score ONE transfer. `features` holds every name in features.FEATURES."""
    art = art or load_artifacts()
    row = pd.DataFrame([{f: features[f] for f in FEATURES}])
    scored = score_frame(art, row).iloc[0]
    hits = rules.rule_hits(features)
    tier = scored["tier"]
    reasons = [{"source": "rule", "feature": h["id"], "text": h["text"]} for h in hits]
    if tier != "low":  # a low-risk transfer needs no explanation
        reasons += _top_reasons(art, row)
    scam_type = None
    if tier in ("high", "very_high") and art.scam_booster is not None:
        probs = art.scam_booster.predict(row[FEATURES])[0]
        scam_type = art.scam_classes[int(np.argmax(probs))]
    return {
        "risk_pct": int(round(100 * scored["risk"])),
        "tier": tier,
        "action": ACTIONS[tier],
        "scam_type": scam_type,
        "reasons": reasons,
        "model_version": "v1",
    }
