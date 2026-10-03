import pytest
from fastapi.testclient import TestClient

import scorer
import shield_api
from test_single_signal import BASE

pytestmark = pytest.mark.skipif(not (scorer.ARTIFACT_DIR / "model.txt").exists(), reason="run train.py first")
HIGH = dict(BASE, is_first_time_recipient=1, is_round_amount=1, amount_zscore=2.5, balance_share=0.4, on_call=1,
            hesitation_secs=24.0)
FAKE_SMS = dict(BASE, is_first_time_recipient=1, sms_claims_credit=1, sms_mentions_recipient=1,
                claim_ledger_mismatch=1, claim_mismatch_on_recipient=1, recipient_age_days=3.0, first_time_senders_24h=11)
GOOD_BN_HOLD = "নিরাপত্তার জন্য লেনদেনটি ৩০ মিনিট ধরে রাখা হয়েছে। আপনি যেকোনো সময় বাতিল করতে পারেন।"


@pytest.fixture()
def client():
    with TestClient(shield_api.app) as c:
        yield c


def test_low_risk_has_no_message(client):
    out = client.post("/risk/score", json=BASE).json()
    assert out["message_bn"] is None and out["message_source"] is None


def test_high_risk_has_bangla_and_english_templates_by_default(client):
    out = client.post("/risk/score", json=HIGH).json()
    assert out["message_source"] == "template" and "বাতিল" in out["message_bn"] and out["message_en"]


def test_fake_sms_hold_message_states_the_ledger_fact(client):
    out = client.post("/risk/score", json=FAKE_SMS).json()
    assert out["action"] == "hold_30min" and "৩০ মিনিট" in out["message_bn"] and "জমা হয়নি" in out["message_bn"]


def test_refine_returns_a_message_for_the_new_tier(client):
    qid = client.post("/risk/score", json=HIGH).json()["questions"][0]["id"]
    out = client.post("/risk/refine", json={"features": HIGH, "answers": [{"question_id": qid, "answer": "yes"}]}).json()
    assert out["action_after"] == "hold_30min" and "৩০ মিনিট" in out["message_bn"] and out["reasons"]


def test_a_working_llm_changes_only_the_words_never_the_decision(client):
    baseline = client.post("/risk/score", json=FAKE_SMS).json()
    shield_api.app.state.llm = lambda prompt: GOOD_BN_HOLD
    out = client.post("/risk/score", json=FAKE_SMS).json()
    assert out["message_source"] == "llm"
    assert (out["risk_pct"], out["tier"], out["action"]) == (baseline["risk_pct"], baseline["tier"], baseline["action"])


def test_a_failing_llm_never_breaks_the_response(client):
    def broken(prompt):
        raise ConnectionError("no internet")
    shield_api.app.state.llm = broken
    out = client.post("/risk/score", json=FAKE_SMS).json()
    assert out["message_source"] == "template" and out["action"] == "hold_30min"
