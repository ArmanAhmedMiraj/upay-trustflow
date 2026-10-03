"""Show what Shield decides for each demo situation, on the seeded wallet database.

Run from the repository root (after seeding):
    python simulator/check_demo_scenarios.py
Nothing is changed in the database; this only reads and scores.
"""
import pathlib
import sys
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("wallet-api", "simulator", "shield-api/transfer_risk"):
    sys.path.insert(0, str(ROOT / sub))

import risk_features  # noqa: E402
import scorer  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import Report, SmsMessage, User, utcnow  # noqa: E402
from seed_wallet import DEMO  # noqa: E402

CALM = {}
PRESSURED = {"on_call": True, "hesitation_secs": 25, "amount_edits": 2}

# (title, sender, recipient, amount, behaviour, plant a fake "money received" SMS first?)
SCENARIOS = [
    ("Rahim pays his mother", "rahim", "mum", 1000, CALM, False),
    ("Rahim buys groceries", "rahim", "shop", 600, CALM, False),
    ("Rahim pays his landlord", "rahim", "landlord", 8000, CALM, False),
    ("Nusrat pays a young online seller", "nusrat", "fashion_hub", 4000, CALM, False),
    ("Rahim pays fraud wallet 1 (reported twice), calm", "rahim", "fraudster", 5000, CALM, False),
    ("Rahim pays the fraud wallet while on a call", "rahim", "fraudster", 5000, PRESSURED, False),
    ("Rahim 'returns' money from a fake SMS", "rahim", "fraudster", 5000, PRESSURED, True),
    ("Nusrat 'returns' money from a fake SMS", "nusrat", "fraudster", 3000, PRESSURED, True),
]

# network learning: the same payment to a fraud wallet nobody has reported yet, as reports arrive
REPORTERS = ["nusrat", "sumon", "mum"]


def main() -> None:
    db = SessionLocal()
    art = scorer.load_artifacts()
    by_phone = {u.phone: u for u in db.query(User).filter(User.phone.in_(list(DEMO.values()))).all()}
    if DEMO["rahim"] not in by_phone:
        sys.exit("No demo data found. Run:  python simulator/seed_wallet.py --reset")
    who = lambda key: by_phone[DEMO[key]]  # noqa: E731
    print(f"{'Situation':50s} {'Amount':>7s} {'Risk':>5s}  Action")
    for title, s, r, amount, behavior, fake in SCENARIOS:
        sms = None
        if fake:
            sms = SmsMessage(user_id=who(s).id, sender_label=who(r).phone, kind="credit_claim", official=False,
                             claimed_amount=amount, claimed_number=who(r).phone, text="fake", created_at=utcnow() - timedelta(minutes=10))
            db.add(sms)
            db.flush()
        features = risk_features.build_live_features(db, who(s), who(r), amount, behavior)
        out = scorer.score_transfer(features, art)
        print(f"{title:50s} {amount:>7,d} {out['risk_pct']:>4d}%  {out['action']}")
        if sms is not None:
            db.rollback()                      # the fake message was only for this check

    print("\nNetwork learning: Rahim pays 5,000 to fraud wallet 2, as customers report it")
    print(f"  {'':22s} {'calm':>14s} {'on a call':>16s}")
    for n in range(len(REPORTERS) + 1):
        if n:
            db.add(Report(reporter_id=who(REPORTERS[n - 1]).id, reported_id=who("fraudster2").id, created_at=utcnow() - timedelta(minutes=5)))
            db.flush()
        cells = []
        for behavior in (CALM, PRESSURED):
            out = scorer.score_transfer(risk_features.build_live_features(db, who("rahim"), who("fraudster2"), 5000, behavior), art)
            cells.append(f"{out['risk_pct']:>3d}% {out['action']}")
        print(f"  after {n} report(s):    {cells[0]:>18s} {cells[1]:>22s}")
    db.rollback()
    db.close()


if __name__ == "__main__":
    main()
