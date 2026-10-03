"""Score a few hand-made transfers so you can SEE what Shield decides and why.

Run from the repository root:
    python shield-api/transfer_risk/demo_cases.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scorer  # noqa: E402

# an ordinary transfer: everything normal. Each case below changes only what the story needs.
BASE = dict(amount_zscore=0.0, balance_share=0.15, is_first_time_recipient=0, is_round_amount=0, hour_unusual=0.8,
            log_mins_since_incoming=8.0, hesitation_secs=7.0, amount_edits=0, on_call=0, sender_history_count=40,
            recipient_age_days=400.0, first_time_senders_24h=0, recipient_inflow_count_24h=0,
            recipient_outflow_ratio_24h=0.0, recipient_prior_txns=20, report_count=0, report_rate=0.0,
            sms_claims_credit=0, sms_mentions_recipient=0, ledger_confirms_credit=0, claim_ledger_mismatch=0,
            claim_mismatch_on_recipient=0, sms_official_sender=0)

CASES = {
    "1. Rahim sends 500 to his mother": dict(),
    "2. Rahim pays his landlord 8,000 for the first time (established wallet, round amount)": dict(
        is_first_time_recipient=1, is_round_amount=1, amount_zscore=2.0, balance_share=0.35),
    "2b. Same payment, but he is also on a call and hesitating (a hard genuine case)": dict(
        is_first_time_recipient=1, is_round_amount=1, amount_zscore=2.5, balance_share=0.4, on_call=1,
        hesitation_secs=24.0),
    "3. Genuine family emergency at 3am (large amount, known relative)": dict(
        amount_zscore=3.5, balance_share=0.6, hour_unusual=0.97, hesitation_secs=25.0, on_call=1),
    "4. Rahim 'returns' 5,000 that a caller says was sent by mistake (fake SMS, ledger shows nothing)": dict(
        is_first_time_recipient=1, is_round_amount=1, amount_zscore=3.0, balance_share=0.3, on_call=1,
        hesitation_secs=22.0, amount_edits=1, recipient_age_days=3.0, first_time_senders_24h=11,
        recipient_inflow_count_24h=12, recipient_outflow_ratio_24h=1.2, recipient_prior_txns=14, report_count=1,
        report_rate=0.05, sms_claims_credit=1, sms_mentions_recipient=1, claim_ledger_mismatch=1,
        claim_mismatch_on_recipient=1),
    "5. Fake 'upay officer' call: Rahim sends 90% of his balance to a 3-day-old wallet": dict(
        is_first_time_recipient=1, amount_zscore=3.2, balance_share=0.9, on_call=1, hesitation_secs=35.0,
        amount_edits=2, recipient_age_days=3.0, first_time_senders_24h=9, recipient_inflow_count_24h=10,
        recipient_outflow_ratio_24h=1.0, recipient_prior_txns=10, report_count=0),
    "6. Same fraud, but paid to an old quiet 'mule' account and Rahim acts calmly (a known weak spot)": dict(
        is_first_time_recipient=1, amount_zscore=1.0, balance_share=0.2, hesitation_secs=9.0),
}

if __name__ == "__main__":
    art = scorer.load_artifacts()
    for name, change in CASES.items():
        out = scorer.score_transfer({**BASE, **change}, art)
        print(f"\n{name}")
        print(f"   Security risk: {out['risk_pct']}%   tier: {out['tier']}   action: {out['action']}   "
              f"likely type: {out['scam_type']}")
        for r in out["reasons"]:
            share = f" ({r['share_pct']}%)" if "share_pct" in r else ""
            print(f"     [{r['source']}] {r['text']}{share}")
