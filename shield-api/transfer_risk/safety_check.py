"""Safety-check questions: the customer's answers refine the risk score.

When a transfer lands in the "high" tier, Shield asks two short questions in Bangla:
one general question and one matched to the likely scam type. The answers move the
risk by FIXED, DOCUMENTED amounts. An LLM never decides anything here.

Design rules (each has a reason)
 1. The risk is adjusted in log-odds ("how many times more likely"), the standard way to
    update a probability with new evidence, so the result is always between 0% and 100%.
 2. A risky answer ("yes, someone told me to send this") moves the score up strongly.
 3. A reassuring answer moves it down only a LITTLE, and the total drop is capped.
    Fraudsters coach victims to answer "no", so a "no" must never switch protection off.
 4. Rules are never lowered: a verified fact (for example a fake credit SMS) keeps its
    minimum risk whatever the customer answers.
 5. Every adjustment is returned to the caller, so the final % can be traced step by step.
 6. "Not sure" changes nothing.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import scorer
from features import FEATURES

RISKY_YES = 1.5        # log-odds added when the customer gives the risky answer
REASSURING = -0.3      # log-odds added for the opposite answer (kept small on purpose)
MAX_TOTAL_DROP = -0.6  # the answers can never lower the odds by more than this in total
MAX_TOTAL_RISE = 3.0

# risky_answer: which answer is the worrying one for that question
GENERAL = {
    "id": "g1", "risky_answer": "yes",
    "bn": "কেউ কি ফোন বা মেসেজে আপনাকে এই টাকা পাঠাতে বলেছে?",
    "en": "Has anyone asked you, by phone or message, to send this money?",
}

BY_TYPE = {
    "return_by_mistake": {
        "id": "s_return", "risky_answer": "yes",
        "bn": "কেউ কি বলেছে যে তারা ভুল করে আপনাকে টাকা পাঠিয়েছে এবং ফেরত দিতে বলেছে?",
        "en": "Did someone say they sent you money by mistake and ask you to send it back?",
    },
    "fake_officer": {
        "id": "s_officer", "risky_answer": "yes",
        "bn": "কেউ কি নিজেকে upay, ব্যাংক বা পুলিশের লোক পরিচয় দিয়ে টাকা পাঠাতে বলেছে?",
        "en": "Did someone claiming to be from upay, a bank or the police ask you to send money?",
    },
    "prize_fee": {
        "id": "s_prize", "risky_answer": "yes",
        "bn": "আপনাকে কি বলা হয়েছে যে আপনি পুরস্কার বা ঋণ পাবেন, তবে আগে কিছু টাকা দিতে হবে?",
        "en": "Were you told you won a prize or a loan, but must pay a fee first?",
    },
    "emergency_relative": {
        "id": "s_relative", "risky_answer": "no",
        "bn": "কোনো আত্মীয় বা বন্ধু নতুন নম্বর থেকে জরুরি টাকা চেয়েছে। আপনি কি তার পুরোনো, পরিচিত নম্বরে ফোন করে নিশ্চিত হয়েছেন?",
        "en": "A relative or friend asked for urgent money from a new number. Have you confirmed by calling their old, known number?",
    },
    "advance_payment": {
        "id": "s_advance", "risky_answer": "yes",
        "bn": "পণ্য বা সেবা পাওয়ার আগেই কি আপনাকে পুরো টাকা দিতে বলা হয়েছে, এমন কাউকে যাকে আপনি সামনাসামনি দেখেননি?",
        "en": "Are you being asked to pay in full before getting the item or service, to someone you have not met?",
    },
}

# used when the likely scam type is unknown (the scam-type guess is only about 54% accurate)
FALLBACK = {
    "id": "s_rush", "risky_answer": "yes",
    "bn": "এই টাকা পাঠানোর জন্য কি আপনাকে তাড়া দেওয়া হচ্ছে?",
    "en": "Are you being rushed to send this money?",
}

ANSWERS = ("yes", "no", "not_sure")

# what happens after the customer has answered
ACTION_AFTER_CHECK = {
    "low": "allow",
    "note": "allow_with_note",
    "high": "warn_and_confirm",   # a clear warning; the customer can still choose to continue
    "very_high": "hold_30min",    # cancellable hold plus an analyst case
}


def questions_for(scam_type: str | None) -> list[dict]:
    """Two questions: the general one, and one matched to the likely scam type."""
    specific = BY_TYPE.get(scam_type or "", FALLBACK)
    return [GENERAL, specific]


def _delta(question: dict, answer: str) -> float:
    if answer == "not_sure":
        return 0.0
    return RISKY_YES if answer == question["risky_answer"] else REASSURING


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def refine(features: dict, answers: dict[str, str], art: scorer.Artifacts | None = None) -> dict:
    """Re-score a transfer using the customer's safety-check answers.

    `answers` maps question id -> "yes" | "no" | "not_sure". The base score is recomputed from the
    features, so nobody can tamper with it by sending a made-up starting risk.
    """
    art = art or scorer.load_artifacts()
    row = pd.DataFrame([{f: features[f] for f in FEATURES}])
    base = scorer.score_frame(art, row).iloc[0]
    first = scorer.score_transfer(features, art)
    asked = questions_for(first["scam_type"])
    by_id = {q["id"]: q for q in asked}

    unknown = set(answers) - set(by_id)
    if unknown:
        raise ValueError(f"unknown question ids: {sorted(unknown)}")
    bad = {k: v for k, v in answers.items() if v not in ANSWERS}
    if bad:
        raise ValueError(f"answers must be one of {ANSWERS}: {bad}")

    steps = [{"question_id": qid, "answer": ans, "log_odds_change": _delta(by_id[qid], ans)}
             for qid, ans in answers.items()]
    total = float(np.clip(sum(s["log_odds_change"] for s in steps), MAX_TOTAL_DROP, MAX_TOTAL_RISE))
    model_after = _sigmoid(_logit(float(base["model_risk"])) + total)
    risk_after = max(model_after, float(base["rule_floor"]))   # a rule's minimum is never lowered
    tier_after = str(scorer.tier_of(np.array([risk_after]), art.tiers)[0])
    return {
        "risk_before_pct": first["risk_pct"],
        "risk_after_pct": int(round(100 * risk_after)),
        "tier_before": first["tier"],
        "tier_after": tier_after,
        "action_after": ACTION_AFTER_CHECK[tier_after],
        "total_log_odds_change": round(total, 3),
        "steps": steps,
        "scam_type": first["scam_type"],
    }
