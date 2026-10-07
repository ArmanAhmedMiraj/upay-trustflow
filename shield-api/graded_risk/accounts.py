"""Demo accounts for the Risk Lab. Everything here is invented; no real person or number is used.

A transfer is described by a SENDER account, a RECIPIENT account and the live details of the payment (amount, hour,
phone call ...). `build_features` turns those three into the 31 signals, so changing the sender or the recipient
changes the signals of both sides and of the link between them, exactly as it would in a live wallet.
"""
from __future__ import annotations

import math

from graded_risk import catalogue as cat

DEFAULT_TX = dict(amount=2000, hour=14, on_call=0, hesitation_secs=6, amount_edits=0, mins_since_credit=2000,
                  new_device=0, sms_claim_mismatch=0)


def _amts(*pairs):
    out = []
    for amount, count in pairs:
        out += [amount] * count
    return out


def _shop_amounts(median, n):
    mult = [.4, .6, .8, 1, 1, 1.2, 1.5, 2.1]
    return [int(round(median * mult[i % len(mult)] / 10) * 10) for i in range(n)]


SENDERS = {
    "rahim": dict(id="rahim", name="Rahim Uddin", bio="Garments office worker, sends about ৳700 a time, 80 earlier transfers",
                  district="Dhaka", usual_amount=700, history=80, balance=25000, usual_hour=19,
                  contacts={"mother", "landlord", "colleague"}, circles={"family-dhaka", "office", "neighbourhood"}),
    "sumaiya": dict(id="sumaiya", name="Sumaiya Akter", bio="University student, small transfers, 15 earlier transfers",
                    district="Chattogram", usual_amount=300, history=15, balance=3500, usual_hour=21,
                    contacts={"sister", "hostel"}, circles={"family-ctg", "campus"}),
    "karim": dict(id="karim", name="Abdul Karim", bio="Retired teacher, rarely sends money, 12 earlier transfers, ৳90,000 saved",
                  district="Khulna", usual_amount=1500, history=12, balance=90000, usual_hour=11,
                  contacts={"son", "pharmacy"}, circles={"family-khulna", "mosque"}),
    "tania": dict(id="tania", name="Tania Rahman", bio="Runs a boutique, large frequent payments to suppliers, 300 earlier transfers",
                  district="Sylhet", usual_amount=8000, history=300, balance=200000, usual_hour=13,
                  contacts={"supplier-a", "supplier-b", "tailor"}, circles={"traders-sylhet", "family-sylhet", "market"}),
    "jamal": dict(id="jamal", name="Jamal Hossain", bio="Night-shift driver, active late at night, 150 earlier transfers",
                  district="Dhaka", usual_hour=1, usual_amount=1200, history=150, balance=12000,
                  contacts={"wife", "garage"}, circles={"family-dhaka", "drivers"}),
}

RECIPIENTS = {
    "mother": dict(id="mother", name="Fatema Begum", kind="personal", story="Rahim's mother. Old wallet, full KYC, shared family circle.",
                   district="Dhaka", age=1900, sim_age=2400, kyc=2, wallets_per_nid=1, shared_device=0, first_time_senders=0,
                   inflows=[500, 1000, 700], outflow_ratio=.2, hold=2200, cashout_agents=1, dormant=0, reports=0, prior=220,
                   sim_swap=0, circles={"family-dhaka"}, typical_inflow=800),
    "landlord": dict(id="landlord", name="Mr. Alam (landlord)", kind="personal", story="An established wallet that receives rent from several tenants.",
                     district="Dhaka", age=1100, sim_age=2000, kyc=2, wallets_per_nid=1, shared_device=0, first_time_senders=1,
                     inflows=[8000, 6500, 9000], outflow_ratio=.4, hold=900, cashout_agents=1, dormant=0, reports=0, prior=140,
                     sim_swap=0, circles={"neighbourhood"}, typical_inflow=8000),
    "shop": dict(id="shop", name="Rahman Store", kind="merchant", story="A busy corner shop. Lots of payments, lots of new payers, fast cash-out, but full KYC and a long history.",
                 district="Dhaka", age=900, sim_age=1500, kyc=2, wallets_per_nid=1, shared_device=0, first_time_senders=9,
                 inflows=_shop_amounts(450, 32), outflow_ratio=.8, hold=130, cashout_agents=2, dormant=0, reports=1, prior=1600,
                 sim_swap=0, circles={"neighbourhood", "market"}, typical_inflow=450),
    "newhire": dict(id="newhire", name="Sabbir Hasan", kind="personal", story="An honest new wallet: 12 days old, but full KYC and normal behaviour. A fair test for false alarms.",
                    district="Dhaka", age=12, sim_age=620, kyc=2, wallets_per_nid=1, shared_device=0, first_time_senders=1,
                    inflows=[3000], outflow_ratio=.3, hold=900, cashout_agents=0, dormant=0, reports=0, prior=4,
                    sim_swap=0, circles={"office"}, typical_inflow=3000),
    "cousin": dict(id="cousin", name="Nila Chowdhury", kind="personal", story="A student cousin: basic KYC, young SIM, small history, same family circle.",
                   district="Chattogram", age=130, sim_age=140, kyc=1, wallets_per_nid=1, shared_device=0, first_time_senders=0,
                   inflows=[500, 300], outflow_ratio=.5, hold=400, cashout_agents=1, dormant=0, reports=0, prior=30,
                   sim_swap=0, circles={"family-ctg", "campus"}, typical_inflow=400),
    "clinic": dict(id="clinic", name="City Clinic (merchant)", kind="merchant", story="A clinic: large payments are normal here, long history, fully verified.",
                   district="Khulna", age=1500, sim_age=2200, kyc=2, wallets_per_nid=1, shared_device=0, first_time_senders=4,
                   inflows=_shop_amounts(3500, 14), outflow_ratio=.5, hold=600, cashout_agents=1, dormant=0, reports=0, prior=900,
                   sim_swap=0, circles={"family-khulna", "mosque"}, typical_inflow=3500),
    "marketplace": dict(id="marketplace", name="Sylhet Bazaar Seller", kind="merchant", story="A busy online seller with 4 customer reports in 2,000 payments. Reports are judged against volume.",
                        district="Sylhet", age=700, sim_age=1100, kyc=2, wallets_per_nid=1, shared_device=0, first_time_senders=12,
                        inflows=_shop_amounts(1800, 40), outflow_ratio=.7, hold=200, cashout_agents=2, dormant=0, reports=4, prior=2000,
                        sim_swap=0, circles={"traders-sylhet", "market"}, typical_inflow=1800),
    "mule_officer": dict(id="mule_officer", name="'Officer Rafiq' account", kind="personal", story="Collector for the fake-officer scam: 5 days old, minimal KYC, 2 wallets under one ID, one shared phone, money gone within the hour.",
                         district="Rajshahi", age=5, sim_age=60, kyc=0, wallets_per_nid=2, shared_device=1, first_time_senders=4,
                         inflows=_amts((20000, 2), (15000, 2), (30000, 1), (9000, 1)), outflow_ratio=.8, hold=90, cashout_agents=2,
                         dormant=0, reports=0, prior=18, sim_swap=0, circles=set(), typical_inflow=20000),
    "mule_refund": dict(id="mule_refund", name="'Sent by mistake' account", kind="personal", story="Collector for the refund scam: 28 days old, several people sent almost the same amount, 1 report.",
                        district="Barishal", age=28, sim_age=150, kyc=1, wallets_per_nid=1, shared_device=0, first_time_senders=3,
                        inflows=_amts((5000, 3), (4800, 1), (5200, 1), (1200, 1)), outflow_ratio=.6, hold=150, cashout_agents=1,
                        dormant=0, reports=1, prior=30, sim_swap=0, circles=set(), typical_inflow=5000),
    "mule_quiet": dict(id="mule_quiet", name="Rented old account", kind="personal", story="Looks respectable (280 days old, full KYC) but: 2 wallets under one ID, one shared phone, dormant 30 days then a burst, cashes out fast.",
                       district="Dhaka", age=280, sim_age=300, kyc=2, wallets_per_nid=2, shared_device=1, first_time_senders=2,
                       inflows=_amts((10000, 2), (12000, 1), (9500, 1)), outflow_ratio=.7, hold=200, cashout_agents=2,
                       dormant=30, reports=0, prior=60, sim_swap=0, circles=set(), typical_inflow=8000),
    "mule_fee": dict(id="mule_fee", name="'Prize / loan fee' account", kind="personal", story="Collector for the advance-fee scam: 60 days old, one report, several new payers, most of it cashed out, many payments of the same size.",
                     district="Mymensingh", age=60, sim_age=150, kyc=1, wallets_per_nid=1, shared_device=0, first_time_senders=4,
                     inflows=_amts((2500, 3), (3000, 2), (2000, 1)), outflow_ratio=.7, hold=120, cashout_agents=2,
                     dormant=0, reports=1, prior=34, sim_swap=0, circles=set(), typical_inflow=2500),
    "grey": dict(id="grey", name="Unclear new account", kind="personal", story="A middle case: 25 days old, basic KYC, two reports, a few new payers, but one wallet per ID and normal speed. Should land in the middle.",
                 district="Dhaka", age=25, sim_age=210, kyc=1, wallets_per_nid=1, shared_device=0, first_time_senders=4,
                 inflows=[1500, 2000, 800, 1200, 3000, 1000], outflow_ratio=.6, hold=240, cashout_agents=1, dormant=0, reports=2, prior=22,
                 sim_swap=0, circles={"market"}, typical_inflow=1500),
    "hijacked": dict(id="hijacked", name="Hijacked genuine wallet", kind="personal", story="An old honest wallet whose SIM was swapped 2 days ago and which now forwards money fast: possibly taken over.",
                     district="Dhaka", age=800, sim_age=2, kyc=2, wallets_per_nid=1, shared_device=0, first_time_senders=3,
                     inflows=[2000, 2500, 1800, 3000], outflow_ratio=.8, hold=60, cashout_agents=2, dormant=40, reports=0, prior=300,
                     sim_swap=1, circles={"family-dhaka"}, typical_inflow=1500),
}


def build_features(sender: dict, recipient: dict, tx: dict) -> dict:
    """The 31 signals for this sender paying this recipient with these live details."""
    t = {**DEFAULT_TX, **tx}
    amount = max(1.0, float(t["amount"]))
    d = abs(float(t["hour"]) - sender["usual_hour"]) % 24
    d = min(d, 24 - d)
    inflows = recipient["inflows"]
    typical = recipient.get("typical_inflow") or (sorted(inflows)[len(inflows) // 2] if inflows else amount)
    f = {
        "s_amount_zscore": min(6.0, max(-3.0, math.log(amount / sender["usual_amount"]) / 0.7)),
        "s_balance_share": min(1.0, amount / sender["balance"]),
        "s_hour_unusual": min(1.0, 0.1 + d / 9 * 0.9),
        "s_log_mins_since_credit": math.log1p(min(10080.0, max(0.0, float(t["mins_since_credit"])))),
        "s_hesitation_secs": min(300.0, max(1.0, float(t["hesitation_secs"]))),
        "s_amount_edits": float(t["amount_edits"]),
        "s_on_call": float(bool(t["on_call"])),
        "s_history_count": float(sender["history"]),
        "s_new_device": float(bool(t["new_device"])),
        "s_round_amount": float(amount % 500 == 0 and amount >= 500),
        "r_age_days": float(recipient["age"]),
        "r_sim_age_days": float(recipient["sim_age"]),
        "r_kyc_level": float(recipient["kyc"]),
        "r_wallets_per_nid": float(recipient["wallets_per_nid"]),
        "r_shared_device_wallets": float(recipient["shared_device"]),
        "r_first_time_senders_24h": float(recipient["first_time_senders"]),
        "r_inflow_count_24h": float(len(inflows)),
        "r_outflow_ratio_24h": float(recipient["outflow_ratio"]),
        "r_median_hold_mins": float(recipient["hold"]),
        "r_cashout_agents_7d": float(recipient["cashout_agents"]),
        "r_dormant_days": float(recipient["dormant"]),
        "r_report_count": float(recipient["reports"]),
        "r_report_rate": recipient["reports"] / (recipient["prior"] + 5.0),
        "r_prior_txns": float(recipient["prior"]),
        "r_sim_swap_recent": float(recipient["sim_swap"]),
        "i_first_time_recipient": float(recipient["id"] not in sender["contacts"]),
        "i_amount_vs_recipient_typical": min(4.0, max(-1.0, math.log(amount / typical))),
        "i_same_amount_inflows_24h": float(sum(1 for a in inflows if abs(a - amount) <= 0.08 * amount)),
        "i_mutual_contacts": float(len(sender["circles"] & recipient["circles"])),
        "i_geo_mismatch": float(sender["district"] != recipient["district"]),
        "i_sms_claim_mismatch": float(bool(t["sms_claim_mismatch"])),
    }
    assert set(f) == set(cat.FEATURE_NAMES)
    return f


def public_sender(s: dict) -> dict:
    return {k: s[k] for k in ("id", "name", "bio", "district", "usual_amount", "history", "balance")}


def public_recipient(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "kind": r["kind"], "story": r["story"], "district": r["district"],
            "facts": {"wallet age (days)": r["age"], "SIM age (days)": r["sim_age"], "KYC level (0-2)": r["kyc"],
                      "wallets under same ID": r["wallets_per_nid"], "other wallets on same device": r["shared_device"],
                      "payments in 24h": len(r["inflows"]), "new payers in 24h": r["first_time_senders"],
                      "share cashed out": f"{r['outflow_ratio']:.0%}", "money stays (minutes)": r["hold"],
                      "cash-out agents (7d)": r["cashout_agents"], "dormant days before burst": r["dormant"],
                      "customer reports": r["reports"], "earlier transactions": r["prior"], "SIM swapped recently": bool(r["sim_swap"])}}


# Ready-made stories for the demo: (title, what it shows, sender, recipient, live details)
SCENARIOS = [
    dict(id="family", title="Rahim sends ৳1,000 to his mother", shows="Everything normal on both sides: near zero.",
         sender="rahim", recipient="mother", tx=dict(amount=1000, hour=19)),
    dict(id="rent", title="Rahim pays rent ৳8,000, first time, on a call", shows="Sender looks a little odd (round, first time, on a call) but the recipient is solid: stays low.",
         sender="rahim", recipient="landlord", tx=dict(amount=8000, hour=18, on_call=1, hesitation_secs=14, mins_since_credit=60)),
    dict(id="shop", title="Rahim pays a busy shop ৳450", shows="A recipient with many payments and fast cash-out, but full KYC and a long history: not a mule.",
         sender="rahim", recipient="shop", tx=dict(amount=450, hour=17)),
    dict(id="newhire", title="Rahim pays a brand-new honest wallet ৳3,000", shows="Young wallet alone is not enough to raise an alarm.",
         sender="rahim", recipient="newhire", tx=dict(amount=3000, hour=15)),
    dict(id="emergency", title="Karim sends ৳15,000 to the clinic, at night, on a call", shows="A genuine emergency: the sender looks stressed, the recipient is verified.",
         sender="karim", recipient="clinic", tx=dict(amount=15000, hour=3, on_call=1, hesitation_secs=22, amount_edits=1)),
    dict(id="officer", title="Fake officer: Karim sends ৳45,000 to a 3-day-old wallet", shows="Both sides agree: coached sender plus a classic collector account.",
         sender="karim", recipient="mule_officer", tx=dict(amount=45000, hour=15, on_call=1, hesitation_secs=34, amount_edits=2, new_device=0)),
    dict(id="refund", title="'Sent by mistake': Rahim returns ৳5,000", shows="A fake credit SMS plus a recipient many others paid the same amount.",
         sender="rahim", recipient="mule_refund", tx=dict(amount=5000, hour=16, hesitation_secs=12, sms_claim_mismatch=1)),
    dict(id="calm_fee", title="Calm victim: Tania pays a ৳2,500 'prize fee'", shows="The sender behaves normally: usual amount, usual hour, no call. The recipient's traits carry the score.",
         sender="tania", recipient="mule_fee", tx=dict(amount=2500, hour=13, hesitation_secs=8)),
    dict(id="quiet_mule", title="Rented old account: Tania sends ৳10,000", shows="The recipient looks respectable by age and KYC, but 7 other signals give it away.",
         sender="tania", recipient="mule_quiet", tx=dict(amount=10000, hour=13, on_call=1, hesitation_secs=14)),
    dict(id="grey", title="Rahim pays ৳1,500 to an unclear new account", shows="A middle case: a note or a safety check, not a hold.",
         sender="rahim", recipient="grey", tx=dict(amount=1500, hour=19, hesitation_secs=10)),
    dict(id="bazaar", title="Tania pays the Sylhet seller ৳1,800", shows="Four reports sound alarming, but against 2,000 payments the rate is tiny.",
         sender="tania", recipient="marketplace", tx=dict(amount=1800, hour=14)),
    dict(id="hijack", title="Jamal pays a wallet whose SIM was just swapped", shows="An old honest wallet that looks taken over: the model leans on the SIM swap and the fast forwarding.",
         sender="jamal", recipient="hijacked", tx=dict(amount=2200, hour=1, hesitation_secs=9)),
]
