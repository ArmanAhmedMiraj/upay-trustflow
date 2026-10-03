"""Synthetic upay-style transfer data for the Coached-Transfer Interrupter.

Everything here is invented. No real customer data is used. Every assumption
is documented in docs/synthetic-assumptions.md.

The simulator writes RAW events only (who sent what to whom, when, plus the
confirm-screen behaviour and any SMS claim). It does NOT compute model
features. Features are built later by shield-api/transfer_risk/features.py,
using only information that existed before each transfer.

Time is measured in minutes from day 0. Days 0-29 are a warm-up period so that
every sender already has a history when the model starts to learn.
"""
from __future__ import annotations

import argparse
import pathlib

import numpy as np
import pandas as pd

DAY = 1440  # minutes in a day

SCRIPTS = ["return_by_mistake", "fake_officer", "prize_fee", "emergency_relative", "advance_payment"]
SCRIPT_PROBS = [0.28, 0.24, 0.14, 0.14, 0.20]


def _round_amount(x, step):
    return np.maximum(step, np.round(x / step) * step)


def simulate(n_users: int = 6000, days: int = 120, seed: int = 42, fraud_rate: float = 0.018) -> dict:
    rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------ wallets
    # the wallet population scales with the number of customers (these are the original numbers at 6,000 customers)
    n_sellers, n_merchants = max(100, n_users // 4), max(30, n_users // 20)
    n_collectors, n_fraud = max(10, n_users // 50), max(15, n_users // 40)
    seller0 = n_users
    merch0 = seller0 + n_sellers
    coll0 = merch0 + n_merchants
    fraud0 = coll0 + n_collectors
    n_wallets = fraud0 + n_fraud

    kind = np.array(["user"] * n_users + ["seller"] * n_sellers + ["merchant"] * n_merchants
                    + ["collector"] * n_collectors + ["fraud"] * n_fraud)
    created_day = np.zeros(n_wallets)
    created_day[:n_users] = -rng.uniform(30, 1500, n_users)
    recent = rng.random(n_users) < 0.20  # recently joined customers (their wallets look young too)
    created_day[:n_users] = np.where(recent, rng.uniform(-120, days - 10, n_users), created_day[:n_users])
    # sellers: most are old, 12% are brand new shops opening during the period
    s_new = rng.random(n_sellers) < 0.12
    created_day[seller0:merch0] = np.where(s_new, rng.uniform(0, days - 10, n_sellers), -rng.uniform(60, 1500, n_sellers))
    created_day[merch0:coll0] = -rng.uniform(200, 2000, n_merchants)
    # collectors: genuine wallets that gather money from many people (events, group funds, online shops)
    c_recent = rng.random(n_collectors) < 0.6
    c_created = np.where(c_recent, rng.uniform(-5, days - 8, n_collectors), -rng.uniform(40, 800, n_collectors))
    created_day[coll0:fraud0] = c_created
    c_start = np.where(c_recent, c_created + rng.uniform(0, 2, n_collectors), rng.uniform(0, days - 8, n_collectors))
    c_end = c_start + rng.uniform(3, 10, n_collectors)
    c_pop = rng.lognormal(0, 0.8, n_collectors)
    # fraud wallets: mostly fresh; 45% are old "mule" wallets reused for fraud
    old_mule = rng.random(n_fraud) < 0.45
    f_created = np.where(old_mule, -rng.uniform(60, 400, n_fraud), rng.uniform(-3, days - 6, n_fraud))
    created_day[fraud0:] = f_created
    f_start = np.where(old_mule, rng.uniform(0, days - 10, n_fraud), f_created + rng.uniform(0, 2, n_fraud))
    f_len = rng.uniform(4, 18, n_fraud)
    f_end = f_start + f_len
    f_pop = rng.lognormal(0, 0.8, n_fraud)

    # ------------------------------------------------------------------ users
    u_median = np.clip(rng.lognormal(np.log(700), 0.6, n_users), 150, 6000)
    u_sigma = rng.uniform(0.45, 0.9, n_users)
    u_balance = np.clip(rng.lognormal(np.log(9000), 0.8, n_users), 1500, 200000)
    u_hour = np.clip(rng.normal(15, 3.5, n_users), 8, 21)
    u_rate = 0.35 * rng.lognormal(0, 0.5, n_users)
    contacts = np.array([rng.choice(n_users, 6, replace=False) for _ in range(n_users)])
    contacts = np.where(contacts == np.arange(n_users)[:, None], (contacts + 1) % n_users, contacts)
    ext_contacts = rng.integers(0, n_users, (n_users, 10))  # acquaintances, paid less often
    pref_merch = merch0 + rng.integers(0, n_merchants, (n_users, 4))
    old_sellers = np.where(created_day[seller0:merch0] < 0)[0]
    pref_sell = seller0 + rng.choice(old_sellers, (n_users, 3))
    has_salary = rng.random(n_users) < 0.5
    salary_day = rng.integers(1, 29, n_users)
    salary_amt = _round_amount(rng.lognormal(np.log(18000), 0.4, n_users), 500)
    landlord = seller0 + rng.integers(0, n_sellers, n_users)
    has_rent = rng.random(n_users) < 0.6
    rent_day = rng.integers(1, 11, n_users)
    rent_amt = _round_amount(u_median * 8, 500).clip(3000, 40000)
    has_tuition = rng.random(n_users) < 0.12
    tuition_target = seller0 + rng.integers(0, n_sellers, n_users)
    tuition_amt = _round_amount(rng.lognormal(np.log(8000), 0.5, n_users), 500)

    # seller popularity (new shops get a popularity boost while they are young)
    s_pop = rng.lognormal(0, 0.9, n_sellers)

    rows = []  # list of dict-of-arrays chunks

    def add(ts, sender, recipient, amount, label, script, hes, edits, call, c_amt, c_num, c_off, kind_tag):
        n = len(ts)
        rows.append(pd.DataFrame({
            "ts": ts, "sender": sender, "recipient": recipient, "amount": amount,
            "label": np.full(n, label), "script": np.full(n, script, dtype=object),
            "hesitation_secs": hes, "amount_edits": edits, "on_call": call,
            "claim_amount": c_amt, "claim_number": c_num, "claim_official": c_off,
            "tag": np.full(n, kind_tag, dtype=object),
        }))

    def hours_for(users, odd_prob=0.06):
        h = rng.normal(u_hour[users], 3.0)
        odd = rng.random(len(users)) < odd_prob
        h = np.where(odd, rng.uniform(0, 24, len(users)), h) % 24
        return h

    def genuine_behaviour(n, call_p=0.14, nervous_p=0.15):
        hes = rng.lognormal(np.log(7), 0.5, n) * np.where(rng.random(n) < nervous_p, 4.0, 1.0)
        edits = rng.poisson(0.15, n)
        call = (rng.random(n) < call_p).astype(int)
        return hes, edits, call

    def make_ts(day, hour):
        return day * DAY + hour * 60 + rng.uniform(0, 1, len(day))

    # ------------------------------------------------------------ genuine P2P etc.
    counts = rng.poisson(u_rate * days)
    g_user = np.repeat(np.arange(n_users), counts)
    n_g = len(g_user)
    g_day = rng.uniform(0, days, n_g)
    g_type = rng.choice(["contact", "merchant", "seller", "emergency", "other_user", "collector"], n_g,
                        p=[0.54, 0.16, 0.10, 0.03, 0.13, 0.04])

    recip = np.zeros(n_g, dtype=int)
    amount = np.zeros(n_g)
    m = g_type == "contact"
    recip[m] = contacts[g_user[m], rng.integers(0, 6, m.sum())]
    amount[m] = rng.lognormal(np.log(u_median[g_user[m]]), u_sigma[g_user[m]])
    m = g_type == "merchant"
    mi = np.where(m)[0]
    pick_pref = rng.random(len(mi)) < 0.8
    recip[mi] = np.where(pick_pref, pref_merch[g_user[mi], rng.integers(0, 4, len(mi))],
                         merch0 + rng.integers(0, n_merchants, len(mi)))
    amount[m] = rng.lognormal(np.log(250), 0.7, m.sum())
    m = g_type == "seller"
    idx = np.where(m)[0]
    # 70% repeat a regular seller; the rest are chosen by popularity (new shops attract first-time buyers)
    use_pref = rng.random(len(idx)) < 0.7
    recip[idx[use_pref]] = pref_sell[g_user[idx[use_pref]], rng.integers(0, 3, use_pref.sum())]
    for i in idx[~use_pref]:
        open_mask = created_day[seller0:merch0] <= g_day[i]
        w = s_pop * open_mask * np.where((created_day[seller0:merch0] > g_day[i] - 20), 3.0, 1.0)
        recip[i] = seller0 + rng.choice(n_sellers, p=w / w.sum())
    amount[idx] = rng.lognormal(np.log(1800), 1.0, len(idx))
    m = g_type == "collector"
    for i in np.where(m)[0]:
        act = (c_start <= g_day[i]) & (c_end >= g_day[i])
        w = c_pop * (act if act.any() else 1)
        recip[i] = coll0 + rng.choice(n_collectors, p=w / w.sum())
    amount[m] = rng.lognormal(np.log(1200), 0.7, m.sum())
    m = g_type == "emergency"
    recip[m] = contacts[g_user[m], rng.integers(0, 6, m.sum())]
    amount[m] = rng.lognormal(np.log(u_median[g_user[m]] * 6), 0.5, m.sum())
    m = g_type == "other_user"
    oi = np.where(m)[0]
    use_ext = rng.random(len(oi)) < 0.55
    recip[oi] = np.where(use_ext, ext_contacts[g_user[oi], rng.integers(0, 10, len(oi))],
                         rng.integers(0, n_users, len(oi)))
    recip = np.where((recip == g_user) & (g_type == "other_user"), (recip + 7) % n_users, recip)
    amount[m] = rng.lognormal(np.log(u_median[g_user[m]]), u_sigma[g_user[m]])

    # round some amounts the way people do (to 50 or 100); a share land on 500s naturally
    r50 = rng.random(n_g) < 0.55
    amount = np.where(r50, _round_amount(amount, 50), np.round(amount))
    amount = np.maximum(amount, 20)
    hour = hours_for(g_user, odd_prob=0.06)
    emerg = g_type == "emergency"
    hour = np.where(emerg & (rng.random(n_g) < 0.5), rng.uniform(0, 5, n_g), hour)
    hes, edits, call = genuine_behaviour(n_g)
    call = np.where(emerg | (g_type == "contact"), (rng.random(n_g) < 0.22).astype(int), call)
    first_pay = (g_type == "seller") | (g_type == "other_user") | (g_type == "collector")
    hes = hes * np.where(first_pay, 1.8, 1.0)
    edits = edits + (first_pay & (rng.random(n_g) < 0.15)).astype(int)
    # stray fake "money received" SMS that the user ignores (about someone else)
    stray = rng.random(n_g) < 0.03
    c_amt = np.where(stray, _round_amount(rng.lognormal(np.log(3000), 0.7, n_g), 500), np.nan)
    c_num = np.where(stray, rng.integers(0, n_users, n_g), -1)
    c_num = np.where(stray & (c_num == recip), (c_num + 11) % n_users, c_num)
    add(make_ts(np.floor(g_day), hour), g_user, recip, amount, 0, "genuine", hes, edits, call,
        c_amt, c_num, np.zeros(n_g, dtype=int), "genuine_p2p")

    # ---------------------------------------------------- scheduled rent / tuition
    sched = []
    months = int(days // 30)
    for mth in range(months):
        for who, has, day_col, tgt, amt in ((0, has_rent, rent_day, landlord, rent_amt),
                                            (1, has_tuition, rent_day + 10, tuition_target, tuition_amt)):
            u = np.where(has)[0]
            d = mth * 30 + day_col[u]
            keep = d < days
            u, d = u[keep], d[keep]
            sched.append((u, d, tgt[u], amt[u]))
    for u, d, t, a in sched:
        h = hours_for(u, 0.03)
        hes_, ed_, call_ = genuine_behaviour(len(u), call_p=0.08)
        add(make_ts(d.astype(float), h), u, t, a, 0, "genuine", hes_ * 1.3, ed_, call_,
            np.full(len(u), np.nan), np.full(len(u), -1), np.zeros(len(u), dtype=int), "genuine_scheduled")

    # ----------------------------------------------- genuine "returning" transfers
    all_g = pd.concat(rows, ignore_index=True)
    cand = all_g[(all_g["tag"] == "genuine_p2p") & (all_g["recipient"] < n_users)]
    cand = cand[rng.random(len(cand)) < 0.07]
    rts = cand["ts"].to_numpy() + rng.uniform(5, 180, len(cand))
    keep = rts < days * DAY
    cand, rts = cand[keep], rts[keep]
    n_r = len(cand)
    hes_, ed_, call_ = genuine_behaviour(n_r, call_p=0.15)
    add(rts, cand["recipient"].to_numpy(), cand["sender"].to_numpy(), cand["amount"].to_numpy(), 0, "genuine",
        hes_, ed_, call_, cand["amount"].to_numpy(), cand["sender"].to_numpy(), np.ones(n_r, dtype=int), "genuine_return")

    # -------------------------------------------------------------------- fraud
    n_genuine = sum(len(r) for r in rows)
    n_f = int(fraud_rate * n_genuine / (1 - fraud_rate))
    f_user = rng.integers(0, n_users, n_f)
    f_day = rng.uniform(0, days, n_f)
    f_script = rng.choice(SCRIPTS, n_f, p=SCRIPT_PROBS)
    f_wallet = np.zeros(n_f, dtype=int)
    for i in range(n_f):
        act = (f_start <= f_day[i]) & (f_end >= f_day[i])
        if not act.any():
            act = np.ones(n_fraud, dtype=bool)
        w = f_pop * act
        f_wallet[i] = fraud0 + rng.choice(n_fraud, p=w / w.sum())
    # 30% of victims pay a "quiet mule": an ordinary-looking old customer wallet rented out to fraudsters.
    # Its first victims leave no trace on the recipient side, so only the sender-side signals can help.
    old_users = np.where(created_day[:n_users] < -90)[0]
    mule_pool = rng.choice(old_users, min(400, max(5, len(old_users) // 4)), replace=False)
    quiet = rng.random(n_f) < 0.30
    f_wallet = np.where(quiet, rng.choice(mule_pool, n_f), f_wallet)
    f_wallet = np.where(f_wallet == f_user, fraud0, f_wallet)

    bal = u_balance[f_user] * rng.uniform(0.5, 1.6, n_f)
    stealth = rng.random(n_f) < 0.40  # fraud that looks ordinary on the sender side
    amt = np.zeros(n_f)
    hes = np.zeros(n_f)
    edits = np.zeros(n_f, dtype=int)
    call = np.zeros(n_f, dtype=int)
    hour = hours_for(f_user, 0.03)
    c_amt = np.full(n_f, np.nan)
    c_num = np.full(n_f, -1)
    c_off = np.zeros(n_f, dtype=int)

    def sel(name):
        return f_script == name

    s = sel("return_by_mistake")
    amt[s] = np.where(rng.random(s.sum()) < 0.65, _round_amount(rng.lognormal(np.log(4500), 0.7, s.sum()), 500),
                      np.round(rng.lognormal(np.log(4500), 0.7, s.sum())))
    hes[s] = rng.lognormal(np.log(16), 0.6, s.sum()); edits[s] = rng.poisson(0.7, s.sum()); call[s] = rng.random(s.sum()) < 0.5
    has_claim = s & (rng.random(n_f) < 0.9)
    c_amt[has_claim] = amt[has_claim]
    c_num[has_claim] = f_wallet[has_claim]
    s = sel("fake_officer")
    amt[s] = _round_amount(bal[s] * rng.uniform(0.55, 1.0, s.sum()), 100)
    hes[s] = rng.lognormal(np.log(22), 0.6, s.sum()); edits[s] = rng.poisson(0.9, s.sum()); call[s] = rng.random(s.sum()) < 0.8
    s = sel("prize_fee")
    amt[s] = rng.choice([500, 1000, 1500, 2000, 2500, 3000, 5000], s.sum())
    hes[s] = rng.lognormal(np.log(11), 0.6, s.sum()); edits[s] = rng.poisson(0.4, s.sum()); call[s] = rng.random(s.sum()) < 0.4
    s = sel("emergency_relative")
    amt[s] = np.round(rng.lognormal(np.log(15000), 0.5, s.sum()))
    hes[s] = rng.lognormal(np.log(20), 0.6, s.sum()); edits[s] = rng.poisson(0.9, s.sum()); call[s] = rng.random(s.sum()) < 0.7
    night = s & (rng.random(n_f) < 0.6)
    hour[night] = rng.uniform(0, 5, night.sum())
    s = sel("advance_payment")
    amt[s] = np.where(rng.random(s.sum()) < 0.5, _round_amount(rng.lognormal(np.log(6000), 0.7, s.sum()), 500),
                      np.round(rng.lognormal(np.log(6000), 0.7, s.sum())))
    hes[s] = rng.lognormal(np.log(11), 0.6, s.sum()); edits[s] = rng.poisson(0.4, s.sum()); call[s] = rng.random(s.sum()) < 0.25

    # stealth fraud: sender-side behaviour is ordinary, only the recipient gives it away
    if stealth.any():
        k = stealth.sum()
        amt[stealth] = np.round(u_median[f_user[stealth]] * rng.uniform(0.8, 2.0, k))
        hes[stealth] = rng.lognormal(np.log(9), 0.6, k)
        edits[stealth] = rng.poisson(0.3, k)
        call[stealth] = rng.random(k) < 0.2
        hour[stealth] = hours_for(f_user[stealth], 0.02)
        c_amt[stealth] = np.nan; c_num[stealth] = -1
    amt = np.minimum(amt, np.floor(bal * 0.97))
    amt = np.maximum(amt, 100)
    c_amt = np.where(~np.isnan(c_amt), amt, np.nan)  # claim matches what the victim sends back
    add(make_ts(np.floor(f_day), hour), f_user, f_wallet, amt, 1, f_script, hes, edits, call.astype(int),
        c_amt, c_num, c_off, "fraud")

    transfers = pd.concat(rows, ignore_index=True)
    # sender balance before the transfer (simplified: a stable base times a daily fluctuation)
    transfers["balance_before"] = np.round(u_balance[transfers["sender"].to_numpy()] * rng.uniform(0.5, 1.6, len(transfers)))
    # fraud rows already had balance drawn above; keep amounts payable for everyone
    fraud_mask = transfers["tag"].to_numpy() == "fraud"
    transfers.loc[fraud_mask, "balance_before"] = np.round(bal)
    transfers["balance_before"] = np.maximum(transfers["balance_before"], transfers["amount"] * 1.02).round()
    transfers = transfers.sort_values("ts").reset_index(drop=True)
    transfers["txn_id"] = np.arange(len(transfers))
    transfers["amount"] = transfers["amount"].round().astype(int)

    # ---------------------------------------------------- salary credits (inflows)
    sal = []
    for mth in range(months + 1):
        u = np.where(has_salary)[0]
        d = mth * 30 + salary_day[u]
        keep = d < days
        sal.append(pd.DataFrame({"ts": d[keep] * DAY + rng.uniform(8 * 60, 12 * 60, keep.sum()),
                                 "receiver": u[keep], "payer": -1, "amount": salary_amt[u][keep]}))
    salary = pd.concat(sal, ignore_index=True)

    # ------------------------------------------------- wallet cash-outs (outflows)
    tw = transfers["recipient"].to_numpy()
    k = np.where(transfers["label"].to_numpy() == 1, "fraud", kind[tw])  # money paid to fraudsters leaves fast
    n_t = len(transfers)
    frac = np.where(k == "fraud", rng.uniform(0.8, 1.0, n_t),
            np.where(k == "user", rng.uniform(0.0, 0.8, n_t), rng.uniform(0.6, 1.0, n_t)))
    fast = rng.random(n_t) < 0.8
    delay = np.where(k == "fraud", np.where(fast, rng.lognormal(np.log(35), 1.0, n_t), rng.uniform(120, 1500, n_t)),
             np.where(k == "collector", rng.lognormal(np.log(90), 1.0, n_t),
             np.where(k == "user", rng.exponential(480, n_t), rng.uniform(120, 1440, n_t))))
    outflows = pd.DataFrame({"ts": transfers["ts"].to_numpy() + delay, "wallet": tw,
                             "amount": np.round(transfers["amount"].to_numpy() * frac)})

    # ----------------------------------------------------------------- reports
    fr = transfers[transfers["label"] == 1]
    p_rep = np.where(fr["script"].isin(["return_by_mistake", "fake_officer"]), 0.25, 0.15)
    rep_mask = rng.random(len(fr)) < p_rep
    rep_f = pd.DataFrame({"ts": fr["ts"].to_numpy()[rep_mask] + np.maximum(30, rng.lognormal(np.log(720), 1.0, rep_mask.sum())),
                          "wallet": fr["recipient"].to_numpy()[rep_mask]})
    gn = transfers[(transfers["label"] == 0) & (transfers["recipient"] >= seller0)]
    fp_mask = rng.random(len(gn)) < np.where(kind[gn["recipient"].to_numpy()] == "collector", 0.03, 0.006)
    rep_g = pd.DataFrame({"ts": gn["ts"].to_numpy()[fp_mask] + rng.uniform(300, 1500, fp_mask.sum()),
                          "wallet": gn["recipient"].to_numpy()[fp_mask]})
    reports = pd.concat([rep_f, rep_g], ignore_index=True).sort_values("ts").reset_index(drop=True)

    wallets = pd.DataFrame({"wallet": np.arange(n_wallets), "kind": kind, "created_ts": created_day * DAY})
    return {"transfers": transfers, "salary": salary, "outflows": outflows, "reports": reports, "wallets": wallets}


def save(data: dict, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in data.items():
        df.to_csv(out_dir / f"{name}.csv.gz", index=False)


def load(out_dir: pathlib.Path) -> dict:
    return {n: pd.read_csv(out_dir / f"{n}.csv.gz") for n in ["transfers", "salary", "outflows", "reports", "wallets"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=6000)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()
    d = simulate(a.users, a.days, a.seed)
    save(d, pathlib.Path(a.out))
    t = d["transfers"]
    print(f"transfers: {len(t):,}  fraud: {int(t['label'].sum()):,} ({t['label'].mean():.2%})")
    print(t[t.label == 1]["script"].value_counts().to_string())
