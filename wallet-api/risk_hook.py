"""The place where Shield plugs into the wallet.

Every transfer passes through `check_transfer` BEFORE any money moves:
    wallet database -> 23 signals (risk_features) -> Shield API -> decision

If Shield is switched off or unreachable the decision is "allow" and `shield_available` is False,
so the wallet never stops working because of the AI layer.
Every assessment is saved in the risk_events table for the analyst console and the impact numbers.
"""
import json
from dataclasses import dataclass, field

import risk_features
import shield_client
from models import RiskEvent


@dataclass
class RiskDecision:
    action: str = "allow"      # allow, allow_with_note, safety_check, hold_30min
    risk_pct: int = 0
    tier: str = "low"
    scam_type: str | None = None
    reasons: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    message_bn: str | None = None
    message_en: str | None = None
    shield_available: bool = False
    event_id: int | None = None

    def as_dict(self) -> dict:
        return {"action": self.action, "risk_pct": self.risk_pct, "tier": self.tier, "scam_type": self.scam_type,
                "reasons": self.reasons, "questions": self.questions, "message_bn": self.message_bn,
                "message_en": self.message_en, "shield_available": self.shield_available}


def check_transfer(db, sender, recipient, amount: int, behavior: dict | None = None, source: str = "send") -> RiskDecision:
    features = risk_features.build_live_features(db, sender, recipient, amount, behavior)
    result = shield_client.assess(features)
    if result is None:
        decision = RiskDecision()
    else:
        decision = RiskDecision(
            action=result["action"], risk_pct=result["risk_pct"], tier=result["tier"], scam_type=result.get("scam_type"),
            reasons=result.get("reasons", []), questions=result.get("questions", []),
            message_bn=result.get("message_bn"), message_en=result.get("message_en"), shield_available=True)
    event = RiskEvent(sender_id=sender.id, recipient_id=recipient.id, amount=amount, risk_pct=decision.risk_pct,
                      tier=decision.tier, action=decision.action, scam_type=decision.scam_type,
                      reasons_json=json.dumps(decision.reasons), source=source, shield_available=decision.shield_available)
    db.add(event)
    db.commit()
    decision.event_id = event.id
    return decision
