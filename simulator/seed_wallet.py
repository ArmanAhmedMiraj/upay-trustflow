"""Fill the wallet database with a realistic, fully synthetic world, so the demo has something to protect.

Run from the repository root:
    python simulator/seed_wallet.py --reset

What it creates
 - Thousands of customers, sellers, shops and group-fund wallets with weeks of transfer history
   (the same simulator that trained the model, so the data looks like what Shield learned from).
 - A few named DEMO CHARACTERS with known phone numbers (printed at the end), including a fraud wallet
   that is collecting money from fresh victims right now, and an online seller for the safety-check demo.
 - 3 agents and 1 fraud analyst.
 - Every balance is consistent with the ledger: no taka appears from nowhere.

Everything is invented. All accounts use PIN 12345 except the analyst (99999).
"""
from __future__ import annotations

import argparse
import math
import pathlib
import random
import sys
from datetime import datetime, timedelta

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("wallet-api", "simulator"):
    sys.path.insert(0, str(ROOT / sub))

import generate_transfers as sim  # noqa: E402
import security  # noqa: E402
from database import Base  # noqa: E402
from models import Report, SmsMessage, Transaction, User, utcnow  # noqa: E402

DHAKA = timedelta(hours=6)
DEFAULT_PIN, ANALYST_PIN = "12345", "99999"
MAX_BALANCE = 500_000

FIRST = ["Rahim", "Karim", "Salma", "Nusrat", "Sumon", "Tania", "Faruk", "Mitu", "Jahid", "Rina", "Imran", "Shirin", "Hasan",
         "Lipi", "Kamal", "Runa", "Sohel", "Moni", "Babul", "Papia", "Rubel", "Nazma", "Arif", "Shapla", "Tuhin", "Dola"]
LAST = ["Uddin", "Ahmed", "Begum", "Akter", "Hossain", "Khan", "Islam", "Mia", "Rahman", "Chowdhury", "Sarker", "Das", "Roy"]
SHOP = ["Store", "Traders", "Fashion", "Electronics", "Bakery", "Pharmacy", "Mobile Center", "Grocery"]

# Fixed phone numbers for the demo characters (the 8 digits after the operator code all start with 1)
DEMO = {
    "rahim": "01711000001", "mum": "01711000002", "landlord": "01711000003", "shop": "01711000004",
    "nusrat": "01711000005", "sumon": "01711000006", "fashion_hub": "01711000007", "fraudster": "01711999999", "fraudster2": "01711999998",
    "agent1": "01811000001", "agent2": "01811000002", "agent3": "01811000003", "analyst": "01911000001",
}


def background_phone(wallet_id: int) -> str:
    return f"01{3 + wallet_id % 7}{20_000_000 + wallet_id:08d}"        # 8 digits start with 2: never clashes with DEMO


def seed(db, n_users: int = 1500, days: int = 60, seed_value: int = 42, now: datetime | None = None, log=print) -> dict:
    rng = random.Random(seed_value)
    nprng = np.random.default_rng(seed_value)
    now = now or utcnow()
    local_midnight = (now + DHAKA).replace(hour=0, minute=0, second=0, microsecond=0)
    base = local_midnight - DHAKA - timedelta(days=days)               # simulation clock 0 = local midnight, `days` days ago
    at = lambda minutes: base + timedelta(minutes=float(minutes))      # noqa: E731
    end = local_midnight - DHAKA                                        # the simulated history ends at local midnight today

    log(f"1/6 simulating {n_users:,} customers over {days} days ...")
    data = sim.simulate(n_users=n_users, days=days, seed=seed_value)
    wallets, tr = data["wallets"], data["transfers"].sort_values("txn_id")
    n_wallets = len(wallets)
    uid = lambda w: int(w) + 1                                          # wallet number -> user id  # noqa: E731
    agent_ids = [n_wallets + 1 + i for i in range(3)]
    analyst_id = n_wallets + 4
    scenario_id = n_wallets + 5                                         # first id after the fixed accounts

    # ---------------------------------------------------------------- who plays the demo characters
    sent = tr[tr.sender < n_users].groupby("sender").size().sort_values(ascending=False)
    old = set(wallets[(wallets.wallet < n_users) & (wallets.created_ts < -200 * 1440)].wallet)
    ranked = [w for w in sent.index if w in old]
    rahim = ranked[0]
    mine = tr[tr.sender == rahim]
    seller0, merch0 = n_users, n_users + max(100, n_users // 4)
    coll0 = merch0 + max(30, n_users // 20)
    def top(lo, hi):
        """Rahim's most frequent recipient in a range of wallets (or the busiest one overall in a small world)."""
        pool = mine[(mine.recipient >= lo) & (mine.recipient < hi) & (mine.recipient != rahim)].recipient.value_counts()
        if len(pool) == 0:
            pool = tr[(tr.recipient >= lo) & (tr.recipient < hi) & (tr.recipient != rahim)].recipient.value_counts()
        return pool.index
    mum, landlord, shop = int(top(0, n_users)[0]), int(top(seller0, merch0)[0]), int(top(merch0, coll0)[0])
    others = [w for w in ranked[1:] if w not in (mum, landlord, shop)][:2]
    renamed = {rahim: ("Rahim Uddin", "rahim"), mum: ("Rahima Begum (Mum)", "mum"), landlord: ("Karim Mia (Landlord)", "landlord"),
               shop: ("Shahin Grocery", "shop"), others[0]: ("Nusrat Jahan", "nusrat"), others[1]: ("Sumon Mia", "sumon")}

    # ---------------------------------------------------------------- users
    log("2/6 creating accounts ...")
    shared_hash = security.hash_pin(DEFAULT_PIN)        # seed-only shortcut: thousands of synthetic accounts share one hash
    rows = []
    for w, kind, created in zip(wallets.wallet, wallets.kind, wallets.created_ts):
        w = int(w)
        if w in renamed:
            name, key = renamed[w]
            phone, pin_hash = DEMO[key], security.hash_pin(DEFAULT_PIN)
        else:
            if kind == "user":
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            elif kind == "fraud":
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"          # a fraud wallet looks like any other
            else:
                name = f"{rng.choice(LAST)} {rng.choice(SHOP)}"
            phone, pin_hash = background_phone(w), shared_hash
        rows.append(dict(id=uid(w), phone=phone, name=name, pin_hash=pin_hash, role="customer", balance=0,
                         failed_pin_attempts=0, created_at=at(created)))
    for i, key in enumerate(("agent1", "agent2", "agent3")):
        rows.append(dict(id=agent_ids[i], phone=DEMO[key], name=f"Agent {['Babul', 'Shiuli', 'Monir'][i]}", pin_hash=shared_hash,
                         role="agent", balance=0, failed_pin_attempts=0, created_at=now - timedelta(days=500)))
    rows.append(dict(id=analyst_id, phone=DEMO["analyst"], name="Nadia Rahman (Fraud Analyst)", pin_hash=security.hash_pin(ANALYST_PIN),
                     role="analyst", balance=0, failed_pin_attempts=0, created_at=now - timedelta(days=400)))

    # the two scripted wallets: a fraud wallet collecting from fresh victims, and a young online seller
    fraud_w = scenario_id
    seller_w = scenario_id + 1
    fraud2_w = scenario_id + 2                                          # a second fraud wallet that nobody has reported yet
    rows.append(dict(id=fraud_w, phone=DEMO["fraudster"], name="Jamal Hossain", pin_hash=shared_hash, role="customer", balance=0,
                     failed_pin_attempts=0, created_at=now - timedelta(days=3)))
    rows.append(dict(id=seller_w, phone=DEMO["fashion_hub"], name="Fashion Hub BD", pin_hash=shared_hash, role="customer", balance=0,
                     failed_pin_attempts=0, created_at=now - timedelta(days=60)))
    rows.append(dict(id=fraud2_w, phone=DEMO["fraudster2"], name="Mitu Akter", pin_hash=shared_hash, role="customer", balance=0,
                     failed_pin_attempts=0, created_at=now - timedelta(days=2)))
    db.bulk_insert_mappings(User, rows)
    db.commit()

    # ---------------------------------------------------------------- events, then one chronological replay
    log("3/6 building the ledger ...")
    events = []   # (when, kind, sender_id, receiver_id, amount)
    for r in tr.itertuples():
        events.append((at(r.ts), "send_money", uid(r.sender), uid(r.recipient), int(r.amount)))
    for r in data["salary"].itertuples():
        events.append((at(r.ts), "add_money", None, uid(r.receiver), int(r.amount)))
    for r in data["outflows"].itertuples():
        if r.amount > 0:
            events.append((at(r.ts), "cash_out", uid(r.wallet), agent_ids[int(r.wallet) % 3], int(r.amount)))

    customers = [uid(w) for w in range(n_users) if w not in renamed]
    # scripted: 12 fresh victims paid the fraud wallet in the last 20 hours; it cashed most of it out; two victims reported it
    victims = rng.sample(customers, 12)
    pay_times = sorted(now - timedelta(minutes=rng.uniform(40, 20 * 60)) for _ in victims)
    for v, t in zip(victims, pay_times):
        amount = rng.choice([1500, 2000, 2500, 3000, 4000, 5000, 6000])
        events.append((t, "send_money", v, fraud_w, amount))
        if t + timedelta(minutes=25) < now:
            events.append((t + timedelta(minutes=rng.uniform(10, 25)), "cash_out", fraud_w, agent_ids[0], int(amount * 0.85)))
    report_rows = []
    for v, t in list(zip(victims, pay_times))[:2]:
        report_rows.append(dict(reporter_id=v, reported_id=fraud_w, reason="Asked me to return money sent by mistake",
                                created_at=min(t + timedelta(hours=2), now - timedelta(minutes=20))))
    # scripted: a second fraud wallet, collecting for 14 hours, that no customer has reported yet
    victims2 = rng.sample([c for c in customers if c not in victims], 9)
    for v in victims2:
        t = now - timedelta(minutes=rng.uniform(40, 14 * 60))
        amount = rng.choice([2000, 3000, 4000, 5000])
        events.append((t, "send_money", v, fraud2_w, amount))
        if t + timedelta(minutes=25) < now:
            events.append((t + timedelta(minutes=rng.uniform(10, 25)), "cash_out", fraud2_w, agent_ids[1], int(amount * 0.85)))
    # scripted: an online seller, 60 days old, that has had only two past customers
    for k, payer in enumerate(rng.sample(customers, 2)):
        events.append((now - timedelta(days=30 + k), "send_money", payer, seller_w, 2000))

    events = [e for e in events if e[0] < now - timedelta(seconds=30)]
    events.sort(key=lambda e: e[0])

    balance: dict[int, int] = {}
    ledger = []
    topups = 0
    for when, kind, s, r, amount in events:
        if kind == "add_money":
            balance[r] = balance.get(r, 0) + amount
            ledger.append(dict(kind=kind, sender_id=None, receiver_id=r, amount=amount, status="completed", created_at=when))
            continue
        have = balance.get(s, 0)
        if kind == "cash_out":
            amount = min(amount, have)
            if amount < sim_min():
                continue
        elif have < amount:                                              # fund the payment first, like a real customer would
            top = int(math.ceil((amount - have) / 500.0) * 500 + rng.choice([0, 500, 1000, 2000]))
            ledger.append(dict(kind="add_money", sender_id=None, receiver_id=s, amount=top, status="completed",
                               created_at=when - timedelta(minutes=2)))
            balance[s] = have + top
            topups += 1
        balance[s] = balance.get(s, 0) - amount
        balance[r] = balance.get(r, 0) + amount
        ledger.append(dict(kind=kind, sender_id=s, receiver_id=r, amount=amount, status="completed", created_at=when))
    for who, bal in list(balance.items()):                              # no wallet may hold more than the limit
        if bal > MAX_BALANCE and who not in agent_ids:
            ledger.append(dict(kind="cash_out", sender_id=who, receiver_id=agent_ids[who % 3], amount=bal - 100_000,
                               status="completed", created_at=now - timedelta(minutes=5)))
            balance[agent_ids[who % 3]] = balance.get(agent_ids[who % 3], 0) + bal - 100_000
            balance[who] = 100_000
    db.bulk_insert_mappings(Transaction, ledger)
    db.bulk_update_mappings(User, [dict(id=u, balance=b) for u, b in balance.items()])
    db.commit()

    # ---------------------------------------------------------------- reports and inbox
    log("4/6 adding reports and message inboxes ...")
    seen = set()
    for r in data["reports"].itertuples():
        when = at(r.ts)
        reporter = rng.choice(customers)
        key = (reporter, uid(r.wallet))
        if when < now and key not in seen and reporter != uid(r.wallet):
            seen.add(key)
            report_rows.append(dict(reporter_id=reporter, reported_id=uid(r.wallet), reason=None, created_at=when))
    db.bulk_insert_mappings(Report, report_rows)
    phone_of = {row["id"]: row["phone"] for row in rows}
    cutoff = now - timedelta(days=2)
    sms = [dict(user_id=t["receiver_id"], sender_label="upay", text=f"You have received Tk {t['amount']:,} from {phone_of[t['sender_id']]}.",
                kind="credit_claim", claimed_amount=t["amount"], claimed_number=phone_of[t["sender_id"]], official=True,
                created_at=t["created_at"]) for t in ledger if t["kind"] == "send_money" and t["created_at"] >= cutoff]
    db.bulk_insert_mappings(SmsMessage, sms)
    db.commit()

    log("5/6 checking the ledger ...")
    problems = check_ledger(db)
    if problems:
        raise RuntimeError("Ledger check failed: " + "; ".join(problems[:5]))
    log("6/6 done.")
    return {"users": len(rows), "transactions": len(ledger), "top_ups_added": topups, "reports": len(report_rows),
            "sms": len(sms), "demo": DEMO, "pin": DEFAULT_PIN, "analyst_pin": ANALYST_PIN}


def sim_min() -> int:
    return 10


def check_ledger(db) -> list[str]:
    """Every balance must equal money in minus money out, none negative, none above the wallet limit."""
    from sqlalchemy import func, select
    ins = dict(db.execute(select(Transaction.receiver_id, func.sum(Transaction.amount))
                          .where(Transaction.status == "completed").group_by(Transaction.receiver_id)).all())
    outs = dict(db.execute(select(Transaction.sender_id, func.sum(Transaction.amount))
                           .where(Transaction.status == "completed", Transaction.sender_id.is_not(None))
                           .group_by(Transaction.sender_id)).all())
    problems = []
    for u in db.execute(select(User.id, User.balance, User.role)).all():
        expected = int(ins.get(u.id, 0)) - int(outs.get(u.id, 0))
        if u.balance != expected:
            problems.append(f"user {u.id}: balance {u.balance} but ledger says {expected}")
        if u.balance < 0:
            problems.append(f"user {u.id}: negative balance")
        if u.balance > MAX_BALANCE and u.role == "customer":
            problems.append(f"user {u.id}: above the wallet limit")
    return problems


def cheat_sheet(info: dict) -> str:
    d = info["demo"]
    return f"""
Demo characters (PIN {info['pin']} for everyone except the analyst, PIN {info['analyst_pin']})
  Rahim Uddin      {d['rahim']}   the customer who gets scammed in the demo
  Mum              {d['mum']}   Rahim's mother (everyday payments)
  Landlord         {d['landlord']}   an established seller Rahim pays
  Shahin Grocery   {d['shop']}   a shop Rahim pays
  Nusrat / Sumon   {d['nusrat']} / {d['sumon']}   other customers with history
  Fashion Hub BD   {d['fashion_hub']}   a young online seller (Nusrat paying 4,000 lands in the safety-check tier)
  Jamal Hossain    {d['fraudster']}   FRAUD WALLET 1: 3 days old, collecting from fresh victims, already reported twice
  Mitu Akter       {d['fraudster2']}   FRAUD WALLET 2: 2 days old, collecting from fresh victims, NOT yet reported
  Agents           {d['agent1']}, {d['agent2']}, {d['agent3']}
  Fraud analyst    {d['analyst']}   PIN {info['analyst_pin']}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=1500)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true", help="delete everything in the wallet database first")
    a = ap.parse_args()
    from database import SessionLocal, engine
    import models  # noqa: F401
    if a.reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.query(User).count() and not a.reset:
        sys.exit("The database already has users. Run with --reset to start again.")
    info = seed(db, a.users, a.days, a.seed)
    print(f"\nCreated {info['users']:,} accounts and {info['transactions']:,} transactions "
          f"({info['top_ups_added']:,} automatic top-ups), {info['reports']} reports, {info['sms']:,} inbox messages.")
    print(cheat_sheet(info))


if __name__ == "__main__":
    main()
