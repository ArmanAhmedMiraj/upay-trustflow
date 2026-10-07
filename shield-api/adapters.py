"""Adapters: let a provider send Shield its OWN field names and units, without changing the model.

Shield's model reads 23 named signals (transfer_risk/features.py). Another provider will not call its fields by our
names. An adapter is a small class that turns that provider's request into the signals and nothing more: it never
changes a score, a tier or a threshold. To add a provider: write one class here, register it, give the provider a tenant
(tenants.py). The model, the explanations and the safety check stay shared.

Included:
 - "upay"     our own format: the signals as they are (a pass-through)
 - "demo-mfs" an invented second provider that names fields differently, sends the sender's pause in milliseconds,
              flags as "Y"/"N", and gives the amount as a share of balance in percent. It exists to prove the idea.
"""
from __future__ import annotations

from typing import Callable

import math


def _yn(v) -> int:
    return 1 if str(v).strip().upper() in ("Y", "YES", "TRUE", "1") else 0


def upay(payload: dict) -> dict:
    return payload


def demo_mfs(p: dict) -> dict:
    """Translate the invented provider "demo-mfs". Unknown or missing fields raise KeyError (the caller answers 422)."""
    return {
        "amount_zscore": float(p["amt_z"]), "balance_share": float(p["pct_of_balance"]) / 100.0,
        "is_first_time_recipient": _yn(p["new_payee"]), "is_round_amount": _yn(p["round_amt"]),
        "hour_unusual": float(p["odd_hour"]), "log_mins_since_incoming": math.log1p(float(p["mins_since_credit"])),
        "hesitation_secs": float(p["pause_ms"]) / 1000.0, "amount_edits": int(p["edits"]), "on_call": _yn(p["on_call"]),
        "sender_history_count": int(p["history"]),
        "recipient_age_days": float(p["payee_age_days"]), "first_time_senders_24h": int(p["payee_new_senders_24h"]),
        "recipient_inflow_count_24h": int(p["payee_inflows_24h"]), "recipient_outflow_ratio_24h": float(p["payee_outflow_ratio"]),
        "recipient_prior_txns": int(p["payee_prior_txns"]), "report_count": int(p["payee_reports"]),
        "report_rate": float(p["payee_report_rate"]),
        "sms_claims_credit": _yn(p.get("sms_claims_credit", 0)), "sms_mentions_recipient": _yn(p.get("sms_mentions_payee", 0)),
        "ledger_confirms_credit": _yn(p.get("ledger_confirms_credit", 0)), "claim_ledger_mismatch": _yn(p.get("claim_mismatch", 0)),
        "claim_mismatch_on_recipient": _yn(p.get("claim_mismatch_on_payee", 0)), "sms_official_sender": _yn(p.get("sms_official", 0)),
    }


ADAPTERS: dict[str, Callable[[dict], dict]] = {"upay": upay, "demo-mfs": demo_mfs}


def translate(name: str, payload: dict) -> dict:
    if name not in ADAPTERS:
        raise KeyError(f"no adapter named {name!r}")
    return ADAPTERS[name](payload)
