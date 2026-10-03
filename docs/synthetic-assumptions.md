# Synthetic data assumptions (Module 1: Coached-Transfer Interrupter)

All data is invented. No real customer data, no real phone numbers, no personal information.
The generator is `simulator/generate_transfers.py`; the random seed is fixed (42) so results repeat.

## Why synthetic data
The hackathon provides no production upay data. The model shows that the METHOD works.
Real upay data would be used to retrain and recalibrate (see "Path to real data" below).

## The world
- 6,000 customers, 120 days. Days 0-29 are warm-up so every customer already has a history.
  Training uses days 30-75, calibration 75-100, testing 100-120. Splits are by time, never random.
- Wallet types: customers, sellers/landlords (1,500), merchants (300), collectors (120), fraud wallets (150).
- About 318,600 transfers in total (238,700 after the warm-up); about 5,700 are fraud (1.8%).

## Genuine behaviour (about 98% of transfers)
- Each customer has their own typical amount, usual hours, balance, regular contacts, favourite shops.
- Transfer types: family and friends (most), shop payments, payments to sellers, occasional emergencies,
  one-off payments to acquaintances, monthly rent and tuition, and returning money a friend just sent.
- 20% of customer wallets are recent joiners, so young wallets are NOT automatically suspicious.
- **Hard negatives (genuine transfers that look suspicious)**: first payments to new sellers,
  large round tuition or rent payments, family emergencies at night, people on calls with relatives,
  nervous customers who hesitate, and "collector" wallets (events, group funds, online shops) that are young,
  receive payments from many first-time senders and pass the money on quickly.
- Customers sometimes receive stray fake "money received" SMS messages and ignore them.
- Some genuine wallets receive false reports (0.6%, and 3% for collectors).

## Fraud behaviour (five scripts, noisy on purpose)
| Script | Pattern |
|---|---|
| return_by_mistake | Fake "money received" SMS naming the recipient, ledger shows nothing, a round amount sent back |
| fake_officer | Large share of balance (55-100%), mostly on a call |
| prize_fee | Small or round "fee" |
| emergency_relative | Large amount, often at night |
| advance_payment | Moderate amount to a wallet taking first payments from many people |

Deliberate difficulty:
- 40% of fraud looks ordinary on the sender side (normal amount, hour and behaviour).
- 45% of fraud wallets are old "mule" wallets reused for fraud, and 30% of victims pay a "quiet mule":
  an ordinary-looking old customer wallet, so the recipient side shows nothing for the first victims.
- Only 15-25% of victims report, with a median delay of 12 hours.
- Money paid to fraudsters is cashed out quickly (80% within about an hour).

## Features
Every feature is computed from information available BEFORE the transfer. `tests/test_features_leakage.py`
rebuilds features from truncated history and fails if any value changes. We confirmed the test catches a
deliberately injected leak.

## Simplifications (stated honestly)
- Sender balance is a stable base times a random daily factor, not a full running ledger.
- Recent-joiner wallets may show transfers before their "created" date; wallet age is clipped at zero.
- SMS content is represented by three fields (claimed amount, claimed number, official sender or not),
  not by free text. Production would extract these with fixed patterns, never with an LLM.
- "On a call" is a simulated toggle. A production app could read the call state.
- The assumed cost of interrupting a genuine transfer (15 BDT) and the assumed share of customers who heed a
  warning (30%, 50%, 70%) are assumptions, not measurements.

## Path to real data
1. Replay a controlled, anonymised sample of upay transfers through `features.py` (same code).
2. Retrain and recalibrate; re-check the tier thresholds against the friction budget.
3. Run in "shadow mode" (score but do not show) before showing warnings to customers.
