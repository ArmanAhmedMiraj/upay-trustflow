"""No single signal may raise an alert on its own. Only the overall score decides."""
import pytest

pytest.importorskip("lightgbm")
import scorer  # noqa: E402

ART = scorer.ARTIFACT_DIR
pytestmark = pytest.mark.skipif(not (ART / "model.txt").exists(), reason="run train.py first")

BASE = dict(amount_zscore=0.0, balance_share=0.15, is_first_time_recipient=0, is_round_amount=0, hour_unusual=0.8,
            log_mins_since_incoming=8.0, hesitation_secs=7.0, amount_edits=0, on_call=0, sender_history_count=40,
            recipient_age_days=400.0, first_time_senders_24h=0, recipient_inflow_count_24h=0,
            recipient_outflow_ratio_24h=0.0, recipient_prior_txns=20, report_count=0, report_rate=0.0,
            sms_claims_credit=0, sms_mentions_recipient=0, ledger_confirms_credit=0, claim_ledger_mismatch=0,
            claim_mismatch_on_recipient=0, sms_official_sender=0)

SINGLE_SIGNAL_ON = dict(amount_zscore=4.0, balance_share=0.9, is_first_time_recipient=1, is_round_amount=1,
                        hour_unusual=0.97, log_mins_since_incoming=1.4, hesitation_secs=45.0, amount_edits=4,
                        on_call=1, recipient_age_days=2.0, first_time_senders_24h=14, recipient_inflow_count_24h=15,
                        recipient_outflow_ratio_24h=1.5, recipient_prior_txns=2, report_count=3, report_rate=0.4,
                        sms_claims_credit=1, sms_mentions_recipient=1, claim_ledger_mismatch=1,
                        claim_mismatch_on_recipient=1)


@pytest.fixture(scope="module")
def art():
    return scorer.load_artifacts()


@pytest.mark.parametrize("feature", sorted(SINGLE_SIGNAL_ON))
def test_one_signal_alone_never_triggers_a_safety_check(art, feature):
    row = dict(BASE)
    row[feature] = SINGLE_SIGNAL_ON[feature]
    out = scorer.score_transfer(row, art)
    assert out["tier"] in ("low", "note"), f"{feature} alone gave {out['risk_pct']}%"


def test_ordinary_transfer_is_low_risk(art):
    assert scorer.score_transfer(BASE, art)["tier"] == "low"


def test_stacked_signals_do_trigger_a_hold(art):
    row = dict(BASE, is_first_time_recipient=1, amount_zscore=4.0, balance_share=0.9, on_call=1,
               recipient_age_days=2.0, first_time_senders_24h=14, recipient_outflow_ratio_24h=1.5,
               recipient_prior_txns=2)
    assert scorer.score_transfer(row, art)["tier"] == "very_high"


def test_fake_credit_sms_to_new_number_is_always_held_and_explained(art):
    row = dict(BASE, is_first_time_recipient=1, sms_claims_credit=1, sms_mentions_recipient=1,
               claim_ledger_mismatch=1, claim_mismatch_on_recipient=1)
    out = scorer.score_transfer(row, art)
    assert out["tier"] == "very_high" and out["action"] == "hold_30min"
    assert out["reasons"][0]["source"] == "rule"       # the verified fact comes first, labelled as a rule
