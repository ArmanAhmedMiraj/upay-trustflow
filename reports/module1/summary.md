# Module 1 results: Coached-Transfer Interrupter

All numbers come from a synthetic test period that the model never saw during training or calibration.
They show that the method works in our simulated world; they are not claims about real upay data.

Test period: 50,960 transfers, 943 fraudulent (1.9%).

## Does AI beat simple rules?

| System | PR-AUC | ROC-AUC | Fraud caught at 2% friction |
|---|---|---|---|
| Rules only | 0.323 | 0.885 | 33.5% |
| Logistic regression | 0.826 | 0.986 | 84.0% |
| LightGBM | 0.830 | 0.987 | 84.2% |
| Full system (LightGBM + calibration + rule) | 0.819 | 0.986 | 83.9% |

LightGBM and logistic regression perform almost the same here. The simulated signals mostly add up, so a linear model captures most of the value. The big gain over rules comes from combining signals; the advantage of tree models should grow when real data contains more interactions.

## Is the risk % trustworthy? (calibration)

Expected calibration error: 0.0036 before calibration, 0.0019 after.

| Predicted risk band | Mean predicted | Actual fraud rate | Transfers |
|---|---|---|---|
| 0%-2% | 0.1% | 0.2% | 48,333 |
| 2%-5% | 3.2% | 4.2% | 860 |
| 5%-10% | 6.3% | 5.3% | 599 |
| 10%-20% | 14.1% | 18.0% | 250 |
| 20%-40% | 26.1% | 29.2% | 154 |
| 40%-60% | 45.2% | 35.8% | 53 |
| 60%-80% | 65.4% | 68.5% | 130 |
| 80%-100% | 96.1% | 96.6% | 581 |

## What customers experience (tiers)

Thresholds: note at 10.0%, safety check at 30.0%, 30-minute hold at 60.0%.

| Tier | Genuine transfers disturbed | Fraud caught (count) | Fraud caught (BDT) | Precision |
|---|---|---|---|---|
| Note or above | 0.8% | 80.5% | 89.9% | 65.0% |
| Safety check or above | 0.2% | 72.0% | 82.1% | 86.9% |
| Hold | 0.1% | 68.9% | 77.9% | 91.4% |

## Fraud caught per scam type (safety check or above)

| Scam type | Caught |
|---|---|
| advance_payment | 68.8% |
| emergency_relative | 74.5% |
| fake_officer | 70.5% |
| prize_fee | 64.3% |
| return_by_mistake | 78.0% |

Scam-type classifier accuracy on fraud transfers: 54.4%.

## Business impact (assumed heeding rates)

We do not know how many customers will stop after a warning, so we show several rates. Friction cost is assumed to be 15 BDT per interrupted genuine transfer.

| Customers who heed a warning | Fraud BDT stopped | Genuine transfers interrupted | Net benefit (BDT) |
|---|---|---|---|
| 30% | 974,087 of 3,956,627 | 102 | 972,557 |
| 50% | 1,623,478 of 3,956,627 | 102 | 1,621,948 |
| 70% | 2,272,869 of 3,956,627 | 102 | 2,271,339 |

## Network learning

Average risk shown for fraud transfers, by how many reports the recipient had already:

- 0 reports: 34.6%
- 1-2 reports: 53.2%
- 3+ reports: 95.6%

## Fairness (does the system treat groups differently?)

| Group | Genuine disturbed | Fraud caught | Genuine n | Fraud n |
|---|---|---|---|---|
| newer_sender_(<35_transfers) | 0.4% | 71.2% | 8,439 | 292 |
| established_sender_(35+) | 0.2% | 72.4% | 41,578 | 651 |
| low_balance_(below_median) | 0.3% | 71.7% | 24,985 | 494 |
| high_balance_(above_median) | 0.1% | 72.4% | 25,032 | 449 |
| night_(22:00-05:00) | 0.3% | 77.8% | 4,801 | 117 |
| daytime | 0.2% | 71.2% | 45,216 | 826 |

## Robustness: what if fraudsters adapt? (fraud caught at safety check or above)

- none: 72.0%
- split_amount: 65.5%
- normal_hour: 71.6%
- aged_wallet: 24.6%
- no_sms_story: 67.9%
- combined: 0.0%

Using an old, quiet mule account removes most of the recipient-side evidence. That is a real weakness, and the reason Shield should be combined with account-level controls.

## Generalisation to a scam type the model never saw (fraud caught at 2% friction)

| Held-out scam type | When unseen | When trained on all |
|---|---|---|
| advance_payment | 83.4% | 84.4% |
| emergency_relative | 86.2% | 84.8% |
| fake_officer | 80.2% | 83.1% |
| prize_fee | 78.6% | 80.4% |
| return_by_mistake | 62.4% | 86.4% |

## Speed

Average scoring time: 4.1 ms per transfer (single CPU core).
