"""The 31 signals of the graded-risk model, in one place.

Every signal belongs to one side:
    sender     how the person sending the money is behaving right now
    recipient  what the receiving account looks like (age, KYC, cash-out speed, reports ...)
    pair       how the two relate (first payment, shared contacts, amount against what the recipient usually gets ...)

Each signal says which way it may push the risk (`direction`): +1 only up, -1 only down, 0 either way.
The model is trained with these limits, so no signal can ever behave in a way a judge cannot explain.
`typical` is the value of an ordinary, harmless transfer; it is the "what if this signal were normal" reference
used by the explanation screen. `why` is the reason the signal is in the model (see docs/graded_risk_research.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class Feature:
    name: str
    side: str
    label: str
    direction: int
    typical: float
    why: str
    text: Callable[[float], str]
    present: Callable[[float], bool]


def _f(name, side, label, direction, typical, why, text, present) -> Feature:
    return Feature(name, side, label, direction, float(typical), why, text, present)


FEATURES_LIST: list[Feature] = [
    # ------------------------------------------------------------ sender
    _f("s_amount_zscore", "sender", "Amount vs sender's usual", 1, 0.0,
       "Scam payments are usually far bigger than what the victim normally sends.",
       lambda v: f"Amount is {v:.1f} typical-steps above this sender's usual" if v > 0.5 else "Amount is in line with this sender's usual",
       lambda v: v > 1.5),
    _f("s_balance_share", "sender", "Share of balance sent", 1, 0.15,
       "Victims are pushed to empty the wallet.",
       lambda v: f"Sending {v:.0%} of the wallet balance", lambda v: v > 0.5),
    _f("s_hour_unusual", "sender", "Unusual hour", 1, 0.40,
       "Coached transfers often happen at hours the sender never uses.",
       lambda v: "Sent at an hour this sender rarely uses" if v > 0.7 else "Sent at a normal hour for this sender",
       lambda v: v > 0.75),
    _f("s_log_mins_since_credit", "sender", "Minutes since money arrived", -1, 7.6,
       "Money is often sent on straight after a credit arrives (salary, loan, refund).",
       lambda v: f"Sending {np.expm1(v):.0f} minutes after receiving money", lambda v: np.expm1(v) < 60),
    _f("s_hesitation_secs", "sender", "Hesitation on confirm screen", 1, 6.0,
       "A person being coached stalls, re-reads and hesitates before confirming.",
       lambda v: f"{v:.0f} seconds on the confirm screen", lambda v: v > 20),
    _f("s_amount_edits", "sender", "Amount changed before sending", 1, 0.0,
       "Callers often make the victim change the amount several times.",
       lambda v: f"Amount edited {int(v)} times", lambda v: v >= 2),
    _f("s_on_call", "sender", "Sender is on a phone call", 1, 0.0,
       "Officer and relative scams run over a live phone call. Genuine callers exist too, so it is only one signal of 31.",
       lambda v: "Sender is on a phone call while sending" if v >= 1 else "Sender is not on a call",
       lambda v: v >= 1),
    _f("s_history_count", "sender", "Sender's transfer history", -1, 40.0,
       "Customers with little history are easier targets and harder to judge.",
       lambda v: f"Only {int(v)} earlier transfers on record" if v < 20 else f"{int(v)} earlier transfers on record",
       lambda v: v < 8),
    _f("s_new_device", "sender", "Sender on a new device", 1, 0.0,
       "A new device right before a large payment can mean an account takeover.",
       lambda v: "Logged in from a new device", lambda v: v >= 1),
    _f("s_round_amount", "sender", "Round amount", 1, 0.0,
       "Scammers ask for round figures (৳5,000, ৳10,000).",
       lambda v: "Round amount", lambda v: v >= 1),
    # ------------------------------------------------------------ recipient
    _f("r_age_days", "recipient", "Recipient wallet age", -1, 400.0,
       "Collector accounts are opened shortly before the scam wave.",
       lambda v: f"Recipient wallet is {v:.0f} days old", lambda v: v < 30),
    _f("r_sim_age_days", "recipient", "Recipient SIM age", -1, 900.0,
       "Bangladesh cases: SIMs registered with fake IDs are bought cheaply and used within weeks.",
       lambda v: f"Recipient SIM is {v:.0f} days old", lambda v: v < 90),
    _f("r_kyc_level", "recipient", "Recipient KYC level (0 weak, 2 full)", -1, 2.0,
       "Weak identity checks make an account easy to rent or fake.",
       lambda v: ["Minimal identity checks", "Basic identity checks", "Full identity verification"][int(round(v))],
       lambda v: v < 1),
    _f("r_wallets_per_nid", "recipient", "Wallets under the same ID", 1, 1.0,
       "One person running several wallets is a classic collector pattern.",
       lambda v: f"{int(v)} wallets registered under the same ID", lambda v: v >= 2),
    _f("r_shared_device_wallets", "recipient", "Other wallets on the same device", 1, 0.0,
       "Mule rings log into many wallets from the same phone.",
       lambda v: f"{int(v)} other wallets used on the same device", lambda v: v >= 1),
    _f("r_first_time_senders_24h", "recipient", "New senders in 24 hours", 1, 0.4,
       "A scam wave sends many first-time payers to one account.",
       lambda v: f"First payments from {int(v)} different people in 24 hours", lambda v: v >= 3),
    _f("r_inflow_count_24h", "recipient", "Payments received in 24 hours", 0, 1.5,
       "A burst of payments. Busy shops are normal, so this is judged together with age, KYC and cash-out speed.",
       lambda v: f"{int(v)} payments received in the last 24 hours", lambda v: v >= 8),
    _f("r_outflow_ratio_24h", "recipient", "Share already cashed out", 1, 0.3,
       "Collector accounts pass the money on within hours.",
       lambda v: f"{min(v, 3):.0%} of what arrived in 24 hours has already left", lambda v: v >= 0.7),
    _f("r_median_hold_mins", "recipient", "Minutes money stays in the wallet", -1, 600.0,
       "Pass-through speed: normal users keep money for hours or days.",
       lambda v: f"Money typically stays only {v:.0f} minutes" if v < 120 else f"Money typically stays {v / 60:.0f} hours",
       lambda v: v < 60),
    _f("r_cashout_agents_7d", "recipient", "Different cash-out agents in 7 days", 0, 0.6,
       "Cashing out at many agents spreads the money and hides the trail.",
       lambda v: f"Cashed out at {int(v)} different agents this week", lambda v: v >= 3),
    _f("r_dormant_days", "recipient", "Days dormant before this burst", 1, 0.0,
       "A long-quiet account that suddenly fills up is often a rented account.",
       lambda v: f"Wallet was dormant for {v:.0f} days before this activity", lambda v: v >= 20),
    _f("r_report_count", "recipient", "Times reported by customers", 1, 0.0,
       "Customer reports are direct evidence.",
       lambda v: f"Reported {int(v)} times by customers", lambda v: v >= 1),
    _f("r_report_rate", "recipient", "Reports per payment received", 1, 0.0,
       "Busy honest shops collect a few reports, so reports are judged against volume.",
       lambda v: f"{v:.1%} of payments received led to a report", lambda v: v > 0.05),
    _f("r_prior_txns", "recipient", "Recipient's transaction history", -1, 60.0,
       "A long, steady history is hard to fake.",
       lambda v: f"Only {int(v)} earlier transactions" if v < 25 else f"{int(v)} earlier transactions",
       lambda v: v < 15),
    _f("r_sim_swap_recent", "recipient", "SIM swapped recently", 1, 0.0,
       "A SIM swap on an old wallet can mean the account was taken over or rented out.",
       lambda v: "SIM was swapped in the last 7 days", lambda v: v >= 1),
    # ------------------------------------------------------------ pair
    _f("i_first_time_recipient", "pair", "First payment to this number", 1, 0.0,
       "Almost every scam payment goes to a number the victim has never paid.",
       lambda v: "First payment to this number" if v >= 1 else "Sender has paid this number before",
       lambda v: v >= 1),
    _f("i_amount_vs_recipient_typical", "pair", "Amount vs what recipient usually gets", 1, 0.0,
       "A collector receives far more per payment than a normal wallet of its kind.",
       lambda v: f"Amount is {np.exp(v):.1f}x what this recipient usually receives" if v > 0.3 else "Amount is in line with what this recipient usually receives",
       lambda v: v > 0.9),
    _f("i_same_amount_inflows_24h", "pair", "Others paid the same amount", 1, 0.0,
       "A fixed 'fee' or 'refund' asked from many victims shows as repeated equal amounts.",
       lambda v: f"{int(v)} other payments of almost the same amount in 24 hours", lambda v: v >= 2),
    _f("i_mutual_contacts", "pair", "Contacts in common", -1, 2.0,
       "Genuine payments usually go to someone in the sender's own circle.",
       lambda v: f"{int(v)} contacts in common" if v >= 1 else "No contacts in common",
       lambda v: v < 1),
    _f("i_geo_mismatch", "pair", "Different districts", 1, 0.0,
       "Sender and recipient far apart, with no family link, fits remote scams (weak signal on its own).",
       lambda v: "Sender and recipient are registered in different districts" if v >= 1 else "Same district",
       lambda v: v >= 1),
    _f("i_sms_claim_mismatch", "pair", "SMS says paid, ledger says no", 1, 0.0,
       "The 'sent by mistake' scam uses a fake credit SMS; the ledger shows nothing arrived.",
       lambda v: "An SMS claims money arrived, but the ledger shows no such credit", lambda v: v >= 1),
]

FEATURES = {f.name: f for f in FEATURES_LIST}
FEATURE_NAMES = [f.name for f in FEATURES_LIST]
SIDES = ("sender", "recipient", "pair")
SIDE_LABEL = {"sender": "Sender behaviour", "recipient": "Recipient account", "pair": "Sender-recipient link"}
MONOTONE = [f.direction for f in FEATURES_LIST]
TYPICAL = {f.name: f.typical for f in FEATURES_LIST}


def names_of(side: str) -> list[str]:
    return [f.name for f in FEATURES_LIST if f.side == side]
