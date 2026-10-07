"""The graded-risk model must use both sides, give graded scores, explain honestly, and stay inside its API."""
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from graded_risk import accounts, catalogue as cat, engine

ART = pathlib.Path(__file__).resolve().parents[1] / "shield-api" / "graded_risk" / "artifacts"
pytestmark = pytest.mark.skipif(not (ART / "model.txt").exists(), reason="run shield-api/graded_risk/train.py first")


@pytest.fixture(scope="module")
def eng():
    return engine.get_engine()


def run(eng, scenario_id, **kw):
    sc = next(s for s in accounts.SCENARIOS if s["id"] == scenario_id)
    f = accounts.build_features(accounts.SENDERS[sc["sender"]], accounts.RECIPIENTS[sc["recipient"]], sc["tx"])
    return eng.explain(f, **kw)


def test_catalogue_has_31_signals_on_three_sides_and_every_one_is_explained():
    assert len(cat.FEATURE_NAMES) == 31
    assert {s: len(cat.names_of(s)) for s in cat.SIDES} == {"sender": 10, "recipient": 15, "pair": 6}
    for f in cat.FEATURES_LIST:
        assert f.why and f.label and f.text(f.typical)


def test_every_demo_story_builds_all_signals_and_scores():
    for sc in accounts.SCENARIOS:
        f = accounts.build_features(accounts.SENDERS[sc["sender"]], accounts.RECIPIENTS[sc["recipient"]], sc["tx"])
        assert set(f) == set(cat.FEATURE_NAMES)


def test_points_add_up_exactly_to_the_final_risk(eng):
    for sc in accounts.SCENARIOS:
        out = run(eng, sc["id"])
        total = out["baseline_pct"] + sum(r["points"] for r in out["contributions"])
        assert abs(total - 100 * min(max(out["risk_pct"] / 100, 0.001), 0.999)) < 0.6, sc["id"]


def test_scores_are_graded_not_all_100(eng):
    scores = {sc["id"]: run(eng, sc["id"])["risk_pct"] for sc in accounts.SCENARIOS}
    assert len(set(scores.values())) >= 9
    assert scores["family"] < 2 and scores["shop"] < 5 and scores["bazaar"] < 5      # honest recipients stay low
    assert 10 < scores["grey"] < 60 and 10 < scores["hijack"] < 70                    # middle cases land in the middle
    assert scores["officer"] > 90 and scores["quiet_mule"] > 50 and 40 < scores["calm_fee"] < 90
    assert max(scores.values()) <= 99.9                                               # the model never claims certainty


def test_recipient_signals_alone_can_raise_the_alarm_when_the_sender_is_calm(eng):
    out = run(eng, "calm_fee")
    assert out["tier"] in ("high", "very_high")
    assert out["sides"]["recipient"] > out["sides"]["sender"]
    assert not next(r for r in out["contributions"] if r["signal"] == "s_on_call")["present"]


def test_sender_stress_alone_does_not_condemn_a_verified_recipient(eng):
    out = run(eng, "rent")      # on a call, round amount, first time, but a solid recipient
    assert out["risk_pct"] < 5 and out["tier"] == "low"


def test_no_single_signal_decides_the_outcome(eng):
    # switch each of the 31 signals off in turn (set to harmless) on every demo story and look at the biggest swing
    worst = {}
    for sc in accounts.SCENARIOS:
        full = run(eng, sc["id"])["risk_pct"]
        worst[sc["id"]] = max(full - run(eng, sc["id"], mute_signals=[n])["risk_pct"] for n in cat.FEATURE_NAMES)
    assert max(worst.values()) < 40, worst                 # the most any one signal can move any story (points)
    assert worst["officer"] < 5                            # a textbook scam is caught on many grounds at once
    assert run(eng, "quiet_mule", mute_signals=["s_on_call"])["tier"] in ("high", "very_high")


def test_muting_a_whole_side_shows_why_the_model_needs_both(eng):
    full = run(eng, "calm_fee")["risk_pct"]
    assert run(eng, "calm_fee", mute_sides=["recipient"])["risk_pct"] < full - 40
    assert run(eng, "calm_fee", mute_sides=["sender"])["risk_pct"] > 30     # the recipient side is strong on its own
    assert run(eng, "quiet_mule", mute_sides=["sender"])["risk_pct"] < run(eng, "quiet_mule")["risk_pct"] - 30   # and a sender can tip a doubtful case


def test_combination_summary_is_consistent(eng):
    c = run(eng, "officer")["combination"]
    assert c["all_signals_pct"] >= max(c["sender_signals_only_pct"], c["recipient_signals_only_pct"]) - 0.5
    assert c["typical_transfer_pct"] < 1


def test_monotone_rules_hold(eng):
    base = {n: cat.TYPICAL[n] for n in cat.FEATURE_NAMES}
    for f in cat.FEATURES_LIST:
        if f.direction == 0:
            continue
        lo, hi = (f.typical, f.typical + 3 * abs(f.typical or 1)) if f.direction > 0 else (f.typical * 4 or 4, f.typical)
        a, b = dict(base, **{f.name: lo}), dict(base, **{f.name: hi})
        a.update(r_report_rate=0.0), b.update(r_report_rate=0.0)
        assert eng.risk(b) >= eng.risk(a) - 1e-9, f.name


def test_unknown_side_or_signal_is_refused(eng):
    f = {n: cat.TYPICAL[n] for n in cat.FEATURE_NAMES}
    with pytest.raises(ValueError):
        eng.explain(f, mute_sides=["bank"])
    with pytest.raises(ValueError):
        eng.explain(f, mute_signals=["nope"])
    with pytest.raises(ValueError):
        eng.explain({"s_on_call": 1})


def test_report_proves_both_sides_help():
    rep = json.loads((ART / "report.json").read_text())
    sides = rep["which_sides_are_needed"]
    assert sides["all three sides"]["pr_auc"] > sides["sender + recipient (no link signals)"]["pr_auc"] > sides["recipient signals only"]["pr_auc"] > sides["sender signals only"]["pr_auc"]
    assert rep["score_spread"]["scams_scoring_99_or_more_pct"] < 15
    assert rep["headline"]["calibration_error"] < 0.02


# ------------------------------------------------------------------ HTTP
@pytest.fixture(scope="module")
def client():
    import shield_api
    with TestClient(shield_api.app) as c:
        yield c


def _typical():
    return {n: cat.TYPICAL[n] for n in cat.FEATURE_NAMES}


def test_score_features_returns_sides_and_a_contribution_for_every_signal(client):
    f = _typical() | {"r_report_count": 3, "r_age_days": 2, "r_sim_age_days": 5, "r_kyc_level": 0, "r_first_time_senders_24h": 10,
                         "r_outflow_ratio_24h": 0.95, "i_first_time_recipient": 1}
    out = client.post("/risk/graded/score-features", json={"features": f}).json()
    assert len(out["contributions"]) == 31 and set(out["sides"]) == {"sender", "recipient", "pair"}
    assert out["model_version"] == "graded-1" and out["risk_pct"] > client.post(
        "/risk/graded/score-features", json={"features": _typical()}).json()["risk_pct"]


def test_score_features_rejects_bad_input(client):
    post = lambda **kw: client.post("/risk/graded/score-features", json=kw).status_code   # noqa: E731
    assert post(features={"s_on_call": 1}) == 422                                  # not all 31 signals
    assert post(features=_typical() | {"made_up": 1}) == 422                        # an unknown signal
    assert post(features=_typical(), mute_sides=["bank"]) == 422                    # an unknown side
    assert post(features=_typical() | {"s_on_call": 1e12}) == 422                   # absurd number


def test_the_old_account_based_routes_are_gone(client):
    assert client.get("/risk/graded/accounts").status_code == 404
    assert client.post("/risk/graded", json={}).status_code == 404


def test_catalogue_and_report_endpoints(client):
    assert len(client.get("/risk/graded/catalogue").json()["signals"]) == 31
    assert "which_sides_are_needed" in client.get("/risk/graded/report").json()
