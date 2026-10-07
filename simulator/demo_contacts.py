"""The demo contacts: people a demo customer can pick in the send-money screen, each with a past that makes the model
land at a known level.

Nothing here scores anything. A contact is an ordinary wallet with (a) a profile (SIM age, ID checks, district ...) and
(b) real, dated payments in the ledger. When a demo customer sends money to it, the models read that history exactly as
they would for any account, so the level you see is earned, not scripted. Tests send money to every contact from every
demo account and check that the level shown here is what the models really say.

`group` is the level the contact is built to reach for an ordinary payment of about Tk 3,000:
    low    goes straight through          note   goes through with a short note
    check  the safety check is asked       hold   the payment is held for 30 minutes
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

# --------------------------------------------------------------------------------------------- who they are
# (key, name, phone, group, why)   - phones use 8 digits starting with 1 after the operator digit, so they never clash
CONTACTS = [
    ("mum", "Rahima Begum (Mum)", "01711000002", "low",
     "Family: years of history, same district, shared family contacts. Nothing unusual on either side."),
    ("landlord", "Karim Mia (Landlord)", "01711000003", "low",
     "An established receiver of rent: old account, full ID checks, steady payments from many tenants."),
    ("shop", "Shahin Grocery", "01711000004", "low",
     "A busy neighbourhood shop: hundreds of ordinary payments, full ID checks, no reports."),
    ("tania", "Tania Rahman", "01713894502", "note",
     "A friend you have never paid before. The account is normal, but a first payment to anyone adds a little."),
    ("rubel", "Rubel Electronics", "01715620817", "check",
     "A 45-day-old shop in another district with basic ID checks and only five earlier buyers. Looks like a business, but unproven."),
    ("sadia", "Sadia Enterprise", "01816209345", "check",
     "A 3-week-old account with a newish SIM, two wallets under one ID and a burst of similar payments from strangers."),
    ("nabil", "Nabil Hasan", "01911527063", "hold",
     "An old account that was silent for months, had its SIM swapped two days ago, and is suddenly collecting from "
     "strangers and cashing out. The classic taken-over account."),
    ("rina", "Rina Sultana", "01613308841", "hold",
     "A 6-day-old wallet on a 5-day-old SIM, minimal ID, four wallets under one ID, one phone shared with three others, "
     "taking many similar payments and cashing out through three agents within minutes."),
    ("fraudster", "Jamal Hossain", "01711999999", "hold",
     "Three days old, collecting from many first-time senders, cashing out fast, and already reported twice."),
    ("fraudster2", "Mitu Akter", "01711999998", "hold",
     "Two days old and doing the same thing, but nobody has reported it yet. Shows the model does not need a report."),
]
EXISTING = {"mum", "landlord", "shop", "fraudster", "fraudster2"}   # already created by the main seed
LABEL = {"low": "Goes through", "note": "Goes through with a note", "check": "Safety check", "hold": "Held 30 minutes"}

# What upay knows about each account beyond its ledger (SIM age in days, ID level 0-2, wallets under one ID ...).
PROFILES = {
    "rahim":       dict(district="Dhaka", sim_age_days=2400, kyc_level=2, wallets_per_nid=1, shared_device_wallets=0, circles=["family", "work", "neighbours"]),
    "nusrat":      dict(district="Dhaka", sim_age_days=1900, kyc_level=2, wallets_per_nid=1, shared_device_wallets=0, circles=["family", "university", "neighbours"]),
    "sumon":       dict(district="Dhaka", sim_age_days=1500, kyc_level=2, wallets_per_nid=1, shared_device_wallets=0, circles=["work", "family", "cricket club"]),
    "mum":         dict(district="Dhaka", sim_age_days=3000, kyc_level=2, wallets_per_nid=1, shared_device_wallets=0, circles=["family", "neighbours"]),
    "landlord":    dict(district="Dhaka", sim_age_days=2900, kyc_level=2, wallets_per_nid=1, shared_device_wallets=0, circles=["neighbours"]),
    "shop":        dict(district="Dhaka", sim_age_days=2100, kyc_level=2, wallets_per_nid=1, shared_device_wallets=0, circles=["neighbours"]),
    "tania":       dict(district="Barishal", sim_age_days=10, kyc_level=0, wallets_per_nid=3, shared_device_wallets=0, circles=[]),
    "fashion_hub": dict(district="Chattogram", sim_age_days=10, kyc_level=0, wallets_per_nid=3, shared_device_wallets=0, circles=[]),
    "rubel":       dict(district="Chattogram", sim_age_days=45, kyc_level=1, wallets_per_nid=2, shared_device_wallets=2, circles=[]),
    "sadia":       dict(district="Sylhet", sim_age_days=38, kyc_level=1, wallets_per_nid=2, shared_device_wallets=0, circles=[]),
    "nabil":       dict(district="Sylhet", sim_age_days=2, kyc_level=1, wallets_per_nid=1, shared_device_wallets=0, sim_swap_recent=True, circles=[]),
    "rina":        dict(district="Rangpur", sim_age_days=5, kyc_level=0, wallets_per_nid=4, shared_device_wallets=3, circles=[]),
    "fraudster":   dict(district="Khulna", sim_age_days=12, kyc_level=0, wallets_per_nid=3, shared_device_wallets=2, circles=[]),
    "fraudster2":  dict(district="Khulna", sim_age_days=9, kyc_level=0, wallets_per_nid=3, shared_device_wallets=2, circles=[]),
}
BLURB = {"rahim": "Pays family and shops", "nusrat": "Student, pays friends", "sumon": "Works in an office"}


def contact_list(db, User) -> list[dict]:
    """The contacts as the send screen shows them: name, number, level and the reason."""
    out = []
    for key, name, phone, group, why in CONTACTS:
        u = db.query(User).filter(User.phone == phone).first()
        if u is not None:
            out.append({"key": key, "name": u.name, "phone": phone, "level": group, "level_label": LABEL[group], "why": why})
    return out


# --------------------------------------------------------------------------------------------- their past
def build(now: datetime, rng: random.Random, customers: list[int], agent_ids: list[int], first_id: int, existing: dict | None = None) -> dict:
    """New wallets + dated payments for the contacts that do not exist yet. Returns users, events, reports."""
    ids = {}
    nxt = first_id
    for key, *_ in CONTACTS:
        if key not in EXISTING:
            ids[key] = nxt
            nxt += 1
    ago = lambda **kw: now - timedelta(**kw)                                        # noqa: E731
    users, events, reports = [], [], []
    spec = {
        "tania": 40, "rubel": 45, "sadia": 20, "nabil": 300, "rina": 6,
    }
    for key, name, phone, *_ in CONTACTS:
        if key in ids:
            users.append(dict(id=ids[key], phone=phone, name=name, role="customer", balance=0, failed_pin_attempts=0,
                              created_at=ago(days=spec[key])))
    pool = list(customers)
    ids.update(existing or {})

    def pay(key, payers, amounts, start_min, end_min):
        """`payers` payments into the contact, spread between `start_min` and `end_min` minutes ago."""
        for p in rng.sample(pool, payers):
            amt = rng.choice(amounts)
            events.append((ago(minutes=rng.uniform(end_min, start_min)), "send_money", p, ids[key], amt))

    def cash(key, share, agent_cycle, minutes_after=(4, 14), only_recent_hours=None):
        """Cash out `share` of every payment already added for this contact, soon after it arrived."""
        mine = [e for e in events if e[3] == ids[key] and e[1] == "send_money"]
        for i, (t, _, _, _, amt) in enumerate(mine):
            if only_recent_hours and t < now - timedelta(hours=only_recent_hours):
                continue
            events.append((t + timedelta(minutes=rng.uniform(*minutes_after)), "cash_out", ids[key],
                           agent_ids[agent_cycle[i % len(agent_cycle)]], int(amt * share)))

    # Tania: an ordinary person - steady payments in from friends over a year and a half, a normal share cashed out slowly
    pay("tania", 4, [500, 800, 1000, 1500, 2000], 60 * 24 * 60, 60 * 24 * 5)
    cash("tania", 0.35, [0, 1], minutes_after=(600, 2400))
    # Rubel Electronics: five buyers over six weeks, goods-sized amounts, one last week
    pay("rubel", 5, [3500, 4500, 6000, 9500], 60 * 24 * 40, 60 * 24 * 6)
    pay("rubel", 2, [3500, 4500], 60 * 20, 60 * 3)
    cash("rubel", 0.6, [1], minutes_after=(300, 1500))
    # Sadia Enterprise: eight similar payments from strangers in the last 10 days, three in the last day, half cashed out
    pay("sadia", 5, [2200, 3400, 4100, 5200], 60 * 24 * 10, 60 * 30)
    pay("sadia", 3, [2200, 3400, 4100, 5200], 60 * 20, 60 * 2)
    cash("sadia", 0.5, [0, 2], minutes_after=(60, 600))
    # Nabil Hasan: old account, a little activity long ago, then silence, then a burst of strangers' money cashed out at once
    for p in rng.sample(pool, 3):
        events.append((ago(days=rng.uniform(170, 260)), "send_money", p, ids["nabil"], rng.choice([500, 1000, 1500])))
    pay("nabil", 5, [4000, 5000, 6000], 60 * 6, 60 * 1)
    cash("nabil", 0.9, [0, 1, 2], minutes_after=(3, 9), only_recent_hours=8)
    # Rina Sultana: ten similar payments in 20 hours, nearly all cashed out within minutes through three agents
    pay("rina", 10, [2000, 2500, 3000], 60 * 20, 60 * 1)
    cash("rina", 0.92, [0, 1, 2], minutes_after=(2, 8))
    return {"users": users, "events": events, "reports": reports, "ids": ids}
