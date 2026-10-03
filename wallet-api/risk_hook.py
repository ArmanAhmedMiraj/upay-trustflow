"""The place where Shield plugs into the wallet.

Every transfer passes through `check_transfer` BEFORE any money moves. For now it always allows.
The next commits replace the body with a call to the Shield API; nothing else in the wallet changes.
If Shield is ever unavailable, the wallet must keep working, so the fallback is to allow.
"""
from dataclasses import dataclass


@dataclass
class RiskDecision:
    action: str = "allow"      # allow, allow_with_note, safety_check, hold_30min
    risk_pct: int = 0
    tier: str = "low"


def check_transfer(db, sender, recipient, amount: int, behavior: dict | None = None) -> RiskDecision:
    return RiskDecision()
