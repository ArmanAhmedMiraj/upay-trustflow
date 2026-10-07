"""The place where Shield plugs into the wallet.

Every transfer passes through `check_transfer` BEFORE any money moves:
    wallet database -> 23 signals (risk_features) -> Shield API -> decision

If the customer has answered the safety-check questions, Shield re-scores with those answers.
If Shield is switched off or unreachable the decision is "allow" and `shield_available` is False,
so the wallet never stops working because of the AI layer.
Every assessment is saved in the risk_events table for the analyst console and the impact numbers.
"""
import json
from dataclasses import dataclass, field

import lab_features
import risk_features
import shield_client
from models import RiskEvent


@dataclass
class RiskDecision:
    action: str = "allow"      # allow, allow_with_note, safety_check, warn_and_confirm, hold_30min
    risk_pct: int = 0
    tier: str = "low"
    scam_type: str | None = None
    reasons: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    message_bn: str | None = None
    message_en: str | None = None
    shield_available: bool = False
    risk_before_pct: int | None = None      # set when the customer's answers changed the score
    event_id: int | None = None

    def as_dict(self) -> dict:
        return {"action": self.action, "risk_pct": self.risk_pct, "tier": self.tier, "scam_type": self.scam_type,
                "reasons": self.reasons, "questions": self.questions, "message_bn": self.message_bn,
                "message_en": self.message_en, "shield_available": self.shield_available,
                "risk_before_pct": self.risk_before_pct}


def _from_score(r: dict) -> RiskDecision:
    return RiskDecision(action=r["action"], risk_pct=r["risk_pct"], tier=r["tier"], scam_type=r.get("scam_type"),
                        reasons=r.get("reasons", []), questions=r.get("questions", []),
                        message_bn=r.get("message_bn"), message_en=r.get("message_en"), shield_available=True)


def _from_refine(r: dict) -> RiskDecision:
    return RiskDecision(action=r["action_after"], risk_pct=r["risk_after_pct"], tier=r["tier_after"],
                        scam_type=r.get("scam_type"), reasons=r.get("reasons", []), questions=[],
                        message_bn=r.get("message_bn"), message_en=r.get("message_en"), shield_available=True,
                        risk_before_pct=r["risk_before_pct"])


def check_transfer(db, sender, recipient, amount: int, behavior: dict | None = None, source: str = "send",
                   answers: list[dict] | None = None) -> RiskDecision:
    features = risk_features.build_live_features(db, sender, recipient, amount, behavior)
    try:    # the graded model's 31 signals; if they cannot be built the first model decides alone, as before
        graded = lab_features.build_graded_features(db, sender, recipient, amount, behavior, v1=features)
    except Exception:
        graded = None
    decision = None
    if answers:
        refined = shield_client.refine(features, answers, graded)
        if refined is not None:
            decision = _from_refine(refined)
            source = "refine" if source == "preview" else source
    if decision is None:
        scored = shield_client.assess(features, graded)
        decision = _from_score(scored) if scored is not None else RiskDecision()
    event = RiskEvent(sender_id=sender.id, recipient_id=recipient.id, amount=amount, risk_pct=decision.risk_pct,
                      tier=decision.tier, action=decision.action, scam_type=decision.scam_type,
                      reasons_json=json.dumps(decision.reasons), source=source, shield_available=decision.shield_available)
    db.add(event)
    db.commit()
    decision.event_id = event.id
    return decision
