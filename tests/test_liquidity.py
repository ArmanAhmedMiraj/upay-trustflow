"""Module 2: agent cash forecasting. The simulated world, the point-in-time features, the model, the policy and the service."""
import json

import numpy as np
import pytest

import liq_coverage as cov
import liq_features as F
import liq_model as M
import liq_policy as P
import liq_service as S
import liq_simulate as sim

pytestmark = pytest.mark.skipif(not M.exists(), reason="run shield-api/liquidity/liq_train.py first")


@pytest.fixture(scope="module")
def world():
    return S.get_world()


@pytest.fixture(scope="module")
def report():
    return json.loads((M.ART / "liquidity_report.json").read_text())


# ---------------------------------------------------------------- the simulated agents
def test_the_simulated_world_has_the_expected_shape_and_is_repeatable():
    a1, o1, i1 = sim.simulate_agents(n_agents=30, days=40, seed=3)
    a2, o2, i2 = sim.simulate_agents(n_agents=30, days=40, seed=3)
    assert o1.shape == (30, 40, 24) and (o1 >= 0).all() and (i1 >= 0).all()
    assert np.array_equal(o1, o2) and a1.equals(a2)
    assert set(a1.area_type) <= set(sim.AREA_TYPES) and a1.lat.between(23.6, 24.0).all()


def test_rush_days_really_are_busier():
    _, out, _ = sim.simulate_agents(n_agents=60, days=90, seed=1)
    daily = out.sum(2).mean(0)
    normal = np.mean([daily[d] for d in range(54, 57)])
    assert np.mean([daily[d] for d in range(72, 78)]) > 1.5 * normal              # the festival rush
    assert np.mean([daily[d] for d in (58, 59, 60, 61)]) > 1.2 * normal           # payday


def test_there_is_almost_no_demand_in_the_small_hours():
    _, out, _ = sim.simulate_agents(n_agents=20, days=20, seed=1)
    assert out[:, :, :6].sum() < 0.05 * out.sum()


# ---------------------------------------------------------------- point-in-time features
def test_features_use_only_what_was_known_before_the_morning():
    agents, out, inn = sim.simulate_agents(n_agents=15, days=60, seed=2)
    before = F.day_features(agents, out, inn, 50)
    out2, inn2 = out.copy(), inn.copy()
    out2[:, 50:, :] *= 99                                   # change everything from day 50 onwards
    inn2[:, 50:, :] *= 99
    after = F.day_features(agents, out2, inn2, 50)
    cols = F.FEATURES
    assert np.allclose(before[cols].to_numpy(), after[cols].to_numpy())


def test_a_day_without_four_weeks_of_history_is_refused():
    agents, out, inn = sim.simulate_agents(n_agents=5, days=40, seed=2)
    with pytest.raises(ValueError):
        F.day_features(agents, out, inn, 10)


def test_forecasting_tomorrow_uses_only_data_up_to_this_morning():
    agents, out, inn = sim.simulate_agents(n_agents=10, days=60, seed=2)
    a = F.day_features(agents, out, inn, 51, origin=50)
    out2 = out.copy()
    out2[:, 50:, :] *= 50
    b = F.day_features(agents, out2, inn, 51, origin=50)
    assert np.allclose(a[F.FEATURES].to_numpy(), b[F.FEATURES].to_numpy())


# ---------------------------------------------------------------- policy arithmetic
def test_cash_needed_is_the_deepest_point_of_the_running_balance():
    drain = np.array([[100.0, 100.0, 100.0, 100.0]])
    supply = np.array([[0.0, 50.0, 0.0, 200.0]])
    assert P.requirement(drain, supply)[0] == 250.0               # running net: 100, 150, 250, 150
    assert P.requirement(np.array([[10.0, 10.0]]), np.array([[50.0, 50.0]]))[0] == 0.0


def test_the_run_out_hour_is_found_correctly():
    drain = np.array([[100.0, 100.0, 100.0]])
    supply = np.zeros((1, 3))
    assert P.first_shortfall(np.array([250.0]), drain, supply)[0] == 2
    assert P.first_shortfall(np.array([300.0]), drain, supply)[0] == -1
    assert P.first_shortfall(np.array([50.0]), drain, supply)[0] == 0


def test_the_simulation_turns_customers_away_when_cash_runs_out():
    days = 3
    drain = np.zeros((1, days, 24)); supply = np.zeros((1, days, 24))
    drain[0, 1, 10] = 500                                           # a 500 taka withdrawal on day 1 at 10 am
    target = np.full((1, days + 1), 300.0)                          # but only 300 is on hand after the 8 am refill
    r = P.simulate(drain, supply, target, 1, 1)
    assert r["unmet_bdt"] == 200 and r["runout_hours"] == 1 and r["runout_agent_days"] == 1
    target[:] = 600.0
    assert P.simulate(drain, supply, target, 1, 1)["unmet_bdt"] == 0


def test_the_plan_sits_between_a_normal_and_a_busy_day():
    p50, p90 = np.array([100.0]), np.array([200.0])
    assert P.plan(p50, p90, 0.0)[0] == 100 and P.plan(p50, p90, 1.0)[0] == 200 and 100 < P.plan(p50, p90)[0] < 200


# ---------------------------------------------------------------- is the model any good? (days it never saw)
def test_the_forecast_beats_copying_last_week(report):
    q = report["quality"]
    assert q["pinball_p50_model"] < 0.6 * q["pinball_p50_same_hour_last_week"]
    assert q["pinball_p90_model"] < 0.6 * q["pinball_p90_same_hour_last_week"]


def test_the_busy_day_forecast_covers_about_nine_hours_in_ten(report):
    q = report["quality"]
    assert 0.86 <= q["p90_coverage_cash_out"] <= 0.97 and 0.85 <= q["p90_coverage_cash_in"] <= 0.97
    assert q["p90_coverage_festival_hours"] > 0.8


def test_refilling_from_the_forecast_serves_far_more_customers_than_copying_last_week(report):
    p = report["policy"]
    miss = lambda k: p[k]["unmet_bdt"] / p[k]["demand_bdt"]  # noqa: E731
    assert miss("forecast_driven") < 0.01
    assert miss("guess_with_same_average_cash") > 0.15                              # same cash on hand, far more customers turned away
    assert miss("forecast_driven") < 0.05 * miss("guess_with_same_average_cash")
    festival = lambda k: p[k]["by_day_type"]["festival"]["missed_share"]  # noqa: E731
    assert festival("guess_with_same_average_cash") > 0.3 and festival("forecast_driven") < 0.02


def test_the_cost_of_the_forecast_policy_is_reported_honestly(report):
    p = report["policy"]
    assert p["forecast_driven"]["topups_bdt"] > p["guess_from_last_week_plus_20pct"]["topups_bdt"]     # it moves more cash
    cash = [t["avg_cash_held"] for t in p["tradeoff"]]
    missed = [t["missed_share"] for t in p["tradeoff"]]
    assert cash == sorted(cash) and missed == sorted(missed, reverse=True)                          # more cash on hand, fewer turned away


# ---------------------------------------------------------------- where to add agents
def test_a_busy_area_with_too_few_agents_is_recommended_first():
    import pandas as pd
    agents = pd.DataFrame({"agent_id": range(6), "lat": [23.71, 23.71, 23.71, 23.87, 23.87, 23.87], "lng": [90.43] * 3 + [90.40] * 3,
                           "area": ["Jatrabari"] * 3 + ["Uttara"] * 3})
    demand = np.array([300000.0, 300000, 300000, 50000, 50000, 50000])        # Jatrabari agents carry six times the load
    recs = cov.recommend(agents, demand, np.zeros(6), top=3)
    assert recs and recs[0]["area"] == "Jatrabari" and recs[0]["times_city_median"] > 1.5
    assert all(r["area"] != "Uttara" for r in recs)                             # quiet, well-served areas are not suggested


def test_recommendations_name_distinct_areas(report):
    areas = [c["area"] for c in report["coverage"]]
    assert len(areas) >= 3 and len(areas) == len(set(areas))
    assert all(c["new_agent_would_take_per_day"] > 0 and c["times_city_median"] >= 1.15 for c in report["coverage"])


# ---------------------------------------------------------------- the service
def test_a_normal_day_is_calm_and_the_rush_days_are_not(world):
    normal = world.overview(S.SCENARIOS["normal"])["counts"]
    payday = world.overview(S.SCENARIOS["payday"])["counts"]
    festival = world.overview(S.SCENARIOS["festival"])["counts"]
    assert normal["green"] >= 100 and normal["red"] <= 5
    assert payday["red"] >= 90 and festival["red"] >= 110


def test_the_refill_is_what_is_missing_and_never_negative(world):
    for a in world.overview(S.SCENARIOS["festival"])["agents"]:
        assert a["refill_cash"] == max(0, a["need_cash_24h"] - a["cash_now"]) or abs(a["refill_cash"] - max(0, a["need_cash_24h"] - a["cash_now"])) <= 1
        assert a["refill_cash"] >= 0 and a["refill_float"] >= 0
    calm = world.overview(S.SCENARIOS["normal"])
    assert calm["total_refill_cash"] == 0 or calm["total_refill_cash"] < 0.1 * world.overview(S.SCENARIOS["festival"])["total_refill_cash"]


def test_a_red_agent_gets_a_run_out_time_and_a_briefing_in_both_languages(world):
    d = world.detail(world.demo_agents[0], S.SCENARIOS["festival"])
    assert d["status"] == "red" and d["runout_label"] and d["refill_cash"] > 0
    assert S.group_lakh(d["refill_cash"]) in d["briefing_en"] and "run out" in d["briefing_en"]
    assert any("\u0980" <= c <= "\u09ff" for c in d["briefing_bn"]) and "৳" in d["briefing_bn"] and "নগদ" in d["briefing_bn"]
    assert not any(c in d["briefing_bn"] for c in "0123456789")                # Bangla digits only
    assert d["runout_label"].startswith("Today") and d["runout_label_bn"].startswith("আজ") and d["runout_label_bn"] in d["briefing_bn"]


def test_a_green_agent_is_told_they_are_fine(world):
    d = world.detail(world.demo_agents[0], S.SCENARIOS["normal"])
    assert d["status"] == "green" and d["refill_cash"] == 0 and d["runout_label"] is None
    assert "enough cash" in d["briefing_en"]


def test_the_detail_view_has_two_days_of_hourly_forecasts(world):
    d = world.detail(5, S.SCENARIOS["festival"])
    for key in ("hours", "p50_out", "p90_out", "p50_in", "p90_in", "cash_path_plan", "float_path_plan"):
        assert len(d[key]) == 48
    assert all(b >= a for a, b in zip(d["p50_out"], d["p90_out"]))               # the busy-day line is never below the normal-day line
    assert d["hours"][0] == 8 and d["hours"][16] == 0


def test_days_outside_the_supported_range_are_refused(world):
    for bad in (0, 20, 89, 200):
        with pytest.raises(ValueError):
            world.overview(bad)


def test_only_the_demo_agents_can_log_in_to_the_agent_view(world):
    assert world.agent_for_phone("01811000001") == world.demo_agents[0]
    assert world.agent_for_phone("01711000001") is None
    assert len(set(world.demo_agents)) == 3


def test_time_labels_read_naturally():
    assert S.clock_en(13) == "Today 1:00 pm" and S.clock_en(24 + 2) == "Tomorrow 2:00 am" and S.clock_en(8) == "Today 8:00 am"
    assert S.clock_bn(13) == "আজ দুপুর ১টা" and S.clock_bn(24 + 20) == "আগামীকাল রাত ৮টা"
    assert S.bn_num(1234567) == "১২,৩৪,৫৬৭" and S.bn_num(999) == "৯৯৯" and S.group_lakh(100000) == "1,00,000"
