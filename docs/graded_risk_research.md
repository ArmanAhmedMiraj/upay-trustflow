# Graded-risk model: what a collector account looks like, and how the model uses it

Written on 7 October 2026, during the final, so that the model does not lean on a few sender signals (for example "the sender is on a call")
but weighs the **recipient** and the **combination** too.

## 1. What we researched

We looked for the traits of accounts that receive and collect scam money ("mule" or collector accounts). Sources were
industry write-ups on mule detection and Bangladeshi press reports on mobile-wallet fraud. None of this is upay data.

| What the sources say | Source | Signal(s) we built from it |
|---|---|---|
| Frequent large deposits followed by immediate withdrawal or transfer; rapid movement of funds | [Fraudio](https://www.fraudio.com/blog/money-mules) | `r_outflow_ratio_24h`, `r_median_hold_mins` |
| Sudden activity in newly opened or previously dormant accounts | Fraudio, [Bureau](https://bureau.id/resources/blog/money-mule-detection) | `r_age_days`, `r_dormant_days` |
| Multiple distinct senders paying into one account | Fraudio | `r_first_time_senders_24h`, `r_inflow_count_24h` |
| Frequent changes in account details such as the phone number | Fraudio | `r_sim_swap_recent` |
| Weak KYC; new accounts receiving large inflows | Bureau | `r_kyc_level`, `i_amount_vs_recipient_typical` |
| Shared devices, reused phone numbers and linked beneficiaries across accounts | Bureau | `r_shared_device_wallets`, `r_wallets_per_nid` |
| Pass-through movement: money enters and leaves quickly | Bureau | `r_median_hold_mins`, `r_outflow_ratio_24h`, `r_cashout_agents_7d` |
| Bangladesh: syndicate members bought registered SIMs opened with fake IDs for about Tk 1,000 each and moved victims' balances into wallets opened on those SIMs | [Asia News Network](https://asianews.network/scam-syndicate-found-operating-from-a-quiet-bangladesh-village/) | `r_sim_age_days`, `r_kyc_level`, `r_wallets_per_nid` |
| Bangladesh: Nagad suspended about 13,000 accounts after patterns such as 50 payments in a day, payments from one account with refunds going to different accounts, and many phone numbers switched off | [The Financial Express](https://thefinancialexpress.com.bd/home/nagad-suspends-13000-accounts-initiates-probe-1630809948) | `r_inflow_count_24h`, `r_report_rate`, `i_same_amount_inflows_24h` |

Signals the sources mention that we could not use, because a prototype wallet has no such data: login geography and VPN use,
typing rhythm, and whether a phone number is switched off (that needs the telecom operator).

## 2. The 31 signals, in three groups

The model reads three groups together: how the **sender** behaves right now, what the **recipient account** looks like, and
the **link** between them. Every signal has a direction it is allowed to push (the model is trained with that limit), so a
signal can never behave in a way we cannot explain to a judge. 31 signals: 10 sender behaviour, 15 recipient account, 6 sender-recipient link.

### Sender behaviour (10 signals)

| Signal | Can push risk | Why it is in the model |
|---|---|---|
| `s_amount_zscore` (Amount vs sender's usual) | up only | Scam payments are usually far bigger than what the victim normally sends. |
| `s_balance_share` (Share of balance sent) | up only | Victims are pushed to empty the wallet. |
| `s_hour_unusual` (Unusual hour) | up only | Coached transfers often happen at hours the sender never uses. |
| `s_log_mins_since_credit` (Minutes since money arrived) | down only | Money is often sent on straight after a credit arrives (salary, loan, refund). |
| `s_hesitation_secs` (Hesitation on confirm screen) | up only | A person being coached stalls, re-reads and hesitates before confirming. |
| `s_amount_edits` (Amount changed before sending) | up only | Callers often make the victim change the amount several times. |
| `s_on_call` (Sender is on a phone call) | up only | Officer and relative scams run over a live phone call. Genuine callers exist too, so it is only one signal of 31. |
| `s_history_count` (Sender's transfer history) | down only | Customers with little history are easier targets and harder to judge. |
| `s_new_device` (Sender on a new device) | up only | A new device right before a large payment can mean an account takeover. |
| `s_round_amount` (Round amount) | up only | Scammers ask for round figures (৳5,000, ৳10,000). |

### Recipient account (15 signals)

| Signal | Can push risk | Why it is in the model |
|---|---|---|
| `r_age_days` (Recipient wallet age) | down only | Collector accounts are opened shortly before the scam wave. |
| `r_sim_age_days` (Recipient SIM age) | down only | Bangladesh cases: SIMs registered with fake IDs are bought cheaply and used within weeks. |
| `r_kyc_level` (Recipient KYC level (0 weak, 2 full)) | down only | Weak identity checks make an account easy to rent or fake. |
| `r_wallets_per_nid` (Wallets under the same ID) | up only | One person running several wallets is a classic collector pattern. |
| `r_shared_device_wallets` (Other wallets on the same device) | up only | Mule rings log into many wallets from the same phone. |
| `r_first_time_senders_24h` (New senders in 24 hours) | up only | A scam wave sends many first-time payers to one account. |
| `r_inflow_count_24h` (Payments received in 24 hours) | either way | A burst of payments. Busy shops are normal, so this is judged together with age, KYC and cash-out speed. |
| `r_outflow_ratio_24h` (Share already cashed out) | up only | Collector accounts pass the money on within hours. |
| `r_median_hold_mins` (Minutes money stays in the wallet) | down only | Pass-through speed: normal users keep money for hours or days. |
| `r_cashout_agents_7d` (Different cash-out agents in 7 days) | either way | Cashing out at many agents spreads the money and hides the trail. |
| `r_dormant_days` (Days dormant before this burst) | up only | A long-quiet account that suddenly fills up is often a rented account. |
| `r_report_count` (Times reported by customers) | up only | Customer reports are direct evidence. |
| `r_report_rate` (Reports per payment received) | up only | Busy honest shops collect a few reports, so reports are judged against volume. |
| `r_prior_txns` (Recipient's transaction history) | down only | A long, steady history is hard to fake. |
| `r_sim_swap_recent` (SIM swapped recently) | up only | A SIM swap on an old wallet can mean the account was taken over or rented out. |

### Sender-recipient link (6 signals)

| Signal | Can push risk | Why it is in the model |
|---|---|---|
| `i_first_time_recipient` (First payment to this number) | up only | Almost every scam payment goes to a number the victim has never paid. |
| `i_amount_vs_recipient_typical` (Amount vs what recipient usually gets) | up only | A collector receives far more per payment than a normal wallet of its kind. |
| `i_same_amount_inflows_24h` (Others paid the same amount) | up only | A fixed 'fee' or 'refund' asked from many victims shows as repeated equal amounts. |
| `i_mutual_contacts` (Contacts in common) | down only | Genuine payments usually go to someone in the sender's own circle. |
| `i_geo_mismatch` (Different districts) | up only | Sender and recipient far apart, with no family link, fits remote scams (weak signal on its own). |
| `i_sms_claim_mismatch` (SMS says paid, ledger says no) | up only | The 'sent by mistake' scam uses a fake credit SMS; the ledger shows nothing arrived. |

## 3. How the percentage is made

1. All 31 signals go into one gradient-boosted model (LightGBM, small trees, strong regularisation, monotone limits).
2. The model's raw output is mapped to a probability with a one-step calibration, so that "60%" means roughly 60 in 100 on the test data.
3. Each signal's contribution comes from the model itself (TreeSHAP) and is converted to percentage points, so
   **baseline + all signals = final risk**. The Risk Lab shows these points, grouped by sender, recipient and link.
4. The score is shown between 0.1% and 99.9%. The model never claims certainty.
5. Tiers: note at 9.8%, safety check at 27.8%, hold at 61.9%. Each threshold was chosen so that
   it disturbs no more than a stated share of genuine transfers (note 5%, high 1.5%, very_high 0.3%).

## 4. What we tested (all on synthetic data)

Test set: 40,000 transfers the model never saw, 2,000 of them scams (a 5% scam rate, far above real life).

| The model looks at | Signals | PR-AUC | Scams caught at the hold tier |
|---|---|---|---|
| sender signals only | 10 | 0.24 | 6% |
| recipient signals only | 15 | 0.57 | 31% |
| sender + recipient (no link signals) | 25 | 0.70 | 42% |
| all three sides | 31 | 0.80 | 54% |

- Headline (all three groups): PR-AUC 0.796, 54% of scams reach the hold tier, 0.27% of genuine transfers are disturbed at that tier, precision 91%, calibration error 0.0045.
- Hiding a whole group hurts: without the recipient group PR-AUC falls to 0.49; without the sender group to 0.69; without the link group to 0.69.
- Scores are graded: 10.6% of scams score 99% or more; the middle half of scams score between 23.5% and 94.3%.
- No single signal carries the model. Switching off the most important one costs 0.068 PR-AUC. One result is worth stating plainly: switching off `i_first_time_recipient` lowers the share of scams reaching the hold tier by 20% (many scams sit just above the hold line, so a small change tips them under it).

## 5. Limits we state openly

- The data is **synthetic and written by us**. The scam stories (fake officer, "sent by mistake", relative emergency, prize or fee,
  a rented old account, a clean-looking recipient, faint signals) and the honest hard cases (busy shop, new honest wallet, real
  emergency) are our own assumptions. The test numbers show the method works on this data; they are not a forecast for real upay traffic.
- The scam rate in the data is 5%. Real rates are far lower, so the percentages describe this mix, and a real deployment must be recalibrated on real data.
- The demo accounts in the Risk Lab are invented. Seed values were tuned so the demo covers easy, hard and in-between cases, and some of them (for example the unclear account) sit near a tier boundary on purpose.
- The first step of any pilot is to replace the synthetic data with real, labelled upay history and to measure the same tests again.
