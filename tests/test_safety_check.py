"""Safety-check answers must refine the score in a fixed, traceable, safe way."""
import pytest

import safety_check
import scorer
from test_single_signal import BASE

pytestmark = pytest.mark.skipif(not (scorer.ARTIFACT_DIR / "model.txt").exists(), reason="run train.py first")

# a transfer that lands in the "high" tier: stacked sender signals, ordinary recipient
HIGH = dict(BASE, is_first_time_recipient=1, is_round_amount=1, amount_zscore=2.5, balance_share=0.4, on_call=1,
            hesitation_secs=24.0)
# the fake-credit-SMS case: a rule sets a minimum risk
RULED = dict(BASE, is_first_time_recipient=1, sms_claims_credit=1, sms_mentions_recipient=1,
             claim_ledger_mismatch=1, claim_mismatch_on_recipient=1)


@pytest.fixture(scope="module")
def art():
    return scorer.load_artifacts()


def qids(features, art):
    return [q["id"] for q in safety_check.questions_for(scorer.score_transfer(features, art)["scam_type"])]


def test_every_scam_type_has_a_bangla_and_english_question():
    for q in [safety_check.GENERAL, safety_check.FALLBACK, *safety_check.BY_TYPE.values()]:
        assert q["bn"] and q["en"] and q["risky_answer"] in ("yes", "no")


def test_two_questions_are_always_asked():
    assert len(safety_check.questions_for("fake_officer")) == 2
    assert len(safety_check.questions_for(None)) == 2


def test_no_answers_changes_nothing(art):
    out = safety_check.refine(HIGH, {}, art)
    assert out["risk_after_pct"] == out["risk_before_pct"] and out["total_log_odds_change"] == 0


def test_a_risky_answer_raises_risk_and_can_trigger_a_hold(art):
    g = qids(HIGH, art)[0]
    out = safety_check.refine(HIGH, {g: "yes"}, art)
    assert out["risk_after_pct"] > out["risk_before_pct"]
    assert out["tier_before"] == "high" and out["tier_after"] == "very_high"
    assert out["action_after"] == "hold_30min"


def test_not_sure_changes_nothing(art):
    g = qids(HIGH, art)[0]
    assert safety_check.refine(HIGH, {g: "not_sure"}, art)["risk_after_pct"] == safety_check.refine(HIGH, {}, art)["risk_before_pct"]


def test_reassuring_answers_lower_risk_only_a_little_because_victims_are_coached(art):
    ids = qids(HIGH, art)
    reassuring = {ids[0]: "no"}
    spec = safety_check.questions_for(scorer.score_transfer(HIGH, art)["scam_type"])[1]
    reassuring[ids[1]] = "no" if spec["risky_answer"] == "yes" else "yes"
    out = safety_check.refine(HIGH, reassuring, art)
    assert out["risk_after_pct"] <= out["risk_before_pct"]
    assert out["total_log_odds_change"] >= safety_check.MAX_TOTAL_DROP
    assert out["tier_after"] in ("high", "note")           # protection is never switched off by "no, no"
    assert out["risk_after_pct"] > out["risk_before_pct"] * 0.6


def test_answers_never_lower_a_rule_floor(art):
    out = safety_check.refine(RULED, {qids(RULED, art)[0]: "no"}, art)
    assert out["risk_after_pct"] >= 90 and out["tier_after"] == "very_high"


def test_every_adjustment_is_reported_so_the_result_can_be_traced(art):
    ids = qids(HIGH, art)
    out = safety_check.refine(HIGH, {ids[0]: "yes", ids[1]: "not_sure"}, art)
    assert [s["question_id"] for s in out["steps"]] == ids
    assert out["steps"][0]["log_odds_change"] == safety_check.RISKY_YES and out["steps"][1]["log_odds_change"] == 0


def test_risk_rises_with_more_risky_answers(art):
    ids = qids(HIGH, art)
    spec = safety_check.questions_for(scorer.score_transfer(HIGH, art)["scam_type"])[1]
    one = safety_check.refine(HIGH, {ids[0]: "yes"}, art)["risk_after_pct"]
    two = safety_check.refine(HIGH, {ids[0]: "yes", ids[1]: spec["risky_answer"]}, art)["risk_after_pct"]
    assert two >= one


def test_unknown_question_or_answer_is_rejected(art):
    with pytest.raises(ValueError):
        safety_check.refine(HIGH, {"made_up": "yes"}, art)
    with pytest.raises(ValueError):
        safety_check.refine(HIGH, {qids(HIGH, art)[0]: "maybe"}, art)
