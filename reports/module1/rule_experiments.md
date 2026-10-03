# Rule experiments

A hard rule must be almost always right, otherwise it hurts honest customers. We measured each rule on the
test period before keeping it.

| Rule | Times it fired | Share that were real fraud | Decision |
|---|---|---|---|
| story_mismatch: an SMS claims a credit from the recipient's number, the ledger shows none, and the recipient is new | 137 | 100% | Kept |
| reported_wallet: recipient reported 3 or more times and is new to the sender | 1,243 | 33% (830 honest transfers hit) | Removed |

Why reported_wallet failed: popular honest shops slowly collect a few false reports, so an absolute report count
punishes busy businesses. The model now receives a report RATE (reports relative to payments received) instead,
and decides how much weight to give it.

Note: story_mismatch scored 100% because in our simulation only fraud produces that pattern. In real data an
honest but unusual case could exist (for example a delayed ledger entry), which is one reason the rule only
sets a minimum risk and a human analyst can review the hold.
