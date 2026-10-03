import pytest
from fastapi.testclient import TestClient

import scorer
import shield_api
from test_single_signal import BASE

pytestmark = pytest.mark.skipif(not (scorer.ARTIFACT_DIR / "model.txt").exists(), reason="run train.py first")
HIGH = dict(BASE, is_first_time_recipient=1, is_round_amount=1, amount_zscore=2.5, balance_share=0.4, on_call=1,
            hesitation_secs=24.0)


@pytest.fixture(scope="module")
def client():
    with TestClient(shield_api.app) as c:
        yield c


def test_a_high_tier_response_includes_the_questions(client):
    out = client.post("/risk/score", json=HIGH).json()
    assert out["action"] == "safety_check" and len(out["questions"]) == 2
    assert all(q["bn"] and q["en"] for q in out["questions"])


def test_low_risk_responses_ask_no_questions(client):
    assert client.post("/risk/score", json=BASE).json()["questions"] == []


def test_questions_endpoint_returns_a_pair_for_any_scam_type(client):
    assert len(client.get("/risk/questions", params={"scam_type": "prize_fee"}).json()) == 2
    assert len(client.get("/risk/questions").json()) == 2


def test_refine_over_http_raises_risk_after_a_risky_answer(client):
    first = client.post("/risk/score", json=HIGH).json()
    qid = first["questions"][0]["id"]
    out = client.post("/risk/refine", json={"features": HIGH, "answers": [{"question_id": qid, "answer": "yes"}]}).json()
    assert out["risk_after_pct"] > first["risk_pct"] and out["action_after"] == "hold_30min"
    assert out["steps"][0]["log_odds_change"] == 1.5


def test_refine_rejects_unknown_questions_and_answers(client):
    qid = client.post("/risk/score", json=HIGH).json()["questions"][0]["id"]
    assert client.post("/risk/refine", json={"features": HIGH, "answers": [{"question_id": "zzz", "answer": "yes"}]}).status_code == 422
    assert client.post("/risk/refine", json={"features": HIGH, "answers": [{"question_id": qid, "answer": "maybe"}]}).status_code == 422
