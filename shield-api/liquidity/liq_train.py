"""Train the cash-forecast models, evaluate them, run the refill-policy comparison and save everything the service needs.

Run from the repository root:
    python shield-api/liquidity/liq_train.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import liq_coverage as cov  # noqa: E402
import liq_features as F  # noqa: E402
import liq_model as M  # noqa: E402
import liq_policy as P  # noqa: E402
import liq_simulate as sim  # noqa: E402

TRAIN_DAYS, TEST_DAYS = range(28, 70), range(70, 90)
FIRST, LAST = 70, 88                    # refill cycles evaluated (day 89's cycle runs past the end of the data)
GUESS_MARGIN = 1.2                      # the "guess from last week" policy with a 20% safety margin


def window(arr_a, arr_b, d, a_slice=slice(8, 24), b_slice=slice(0, 8)):
    return np.concatenate([arr_a[:, d, a_slice] if arr_a.ndim == 3 else arr_a[:, a_slice], arr_b[:, b_slice]], axis=1)


def forecast_arrays(models, agents, out, inn, d, days=3):
    """Model forecasts for `days` days starting at day d, all using only what was known before d. Shape (agents, days*24)."""
    A = len(agents)
    frames = [M.predict(models, F.day_features(agents, out, inn, d + k, origin=d)) for k in range(days)]
    pick = lambda col: np.concatenate([f[col].to_numpy().reshape(A, 24) for f in frames], axis=1)  # noqa: E731
    return {c: pick(c) for c in ("p50_out", "p90_out", "p50_in", "p90_in")}


def run(seed: int = 42) -> dict:
    agents, out, inn = sim.simulate_agents(seed=seed)
    A, T = len(agents), out.shape[1]
    train_frame = F.training_frame(agents, out, inn, TRAIN_DAYS)
    test_frame = F.training_frame(agents, out, inn, TEST_DAYS)
    models = M.train(train_frame)
    M.save(models)

    # ---- forecast quality on days the model never saw
    pred = M.predict(models, test_frame)
    baseline_out = (test_frame.lag168_out_ratio * test_frame.base_out).to_numpy()
    quality = {
        "pinball_p50_model": M.pinball(test_frame.y_out.to_numpy(), pred.p50_out.to_numpy(), 0.5),
        "pinball_p50_same_hour_last_week": M.pinball(test_frame.y_out.to_numpy(), baseline_out, 0.5),
        "pinball_p90_model": M.pinball(test_frame.y_out.to_numpy(), pred.p90_out.to_numpy(), 0.9),
        "pinball_p90_same_hour_last_week": M.pinball(test_frame.y_out.to_numpy(), baseline_out, 0.9),
        "p90_coverage_cash_out": float((test_frame.y_out <= pred.p90_out).mean()),
        "p90_coverage_cash_in": float((test_frame.y_in <= pred.p90_in).mean()),
        "p90_coverage_festival_hours": float((test_frame.y_out[test_frame.in_festival == 1] <= pred.p90_out[test_frame.in_festival == 1]).mean()),
        "test_hours": int(len(test_frame)),
    }

    # ---- refill targets for every cycle (cash and e-float) under the two policies
    TRADEOFF = (0.0, 0.3, 0.6, 1.0)
    t_mix = {m: np.zeros((A, T + 1)) for m in TRADEOFF}
    t_guess = {k: np.zeros((A, T + 1)) for k in ("cash", "float")}
    t_model = {k: np.zeros((A, T + 1)) for k in ("cash", "float")}
    for d in range(F.MIN_DAY + 1, T):                           # cycle d needs hours of day d and day d+1
        f = forecast_arrays(models, agents, out, inn, d, days=2)
        sl = lambda x: x[:, 8:32]  # noqa: E731
        t_model["cash"][:, d] = P.requirement(sl(P.plan(f["p50_out"], f["p90_out"])), sl(f["p50_in"]))
        t_model["float"][:, d] = P.requirement(sl(P.plan(f["p50_in"], f["p90_in"])), sl(f["p50_out"]))
        for m in TRADEOFF:
            t_mix[m][:, d] = P.requirement(sl(P.plan(f["p50_out"], f["p90_out"], m)), sl(f["p50_in"]))
        bo = np.concatenate([out[:, d - 7, 8:], out[:, d - 6, :8]], axis=1)
        bi = np.concatenate([inn[:, d - 7, 8:], inn[:, d - 6, :8]], axis=1)
        t_guess["cash"][:, d] = P.requirement(bo, bi)
        t_guess["float"][:, d] = P.requirement(bi, bo)

    # ---- the policy comparison on the test days
    drain, supply = {"cash": (out, inn), "float": (inn, out)}["cash"]
    res_model = P.simulate(drain, supply, t_model["cash"], FIRST, LAST)
    res_guess = P.simulate(drain, supply, t_guess["cash"] * GUESS_MARGIN, FIRST, LAST)
    lo, hi = 1.0, 8.0                                            # give the old method the SAME average cash
    for _ in range(30):
        mid = (lo + hi) / 2
        if P.simulate(drain, supply, t_guess["cash"] * mid, FIRST, LAST)["avg_cash_held"] < res_model["avg_cash_held"]:
            lo = mid
        else:
            hi = mid
    res_same = P.simulate(drain, supply, t_guess["cash"] * hi, FIRST, LAST)

    def kind(d):
        return "festival" if sim.in_festival(d) else "payday" if sim.is_payday(d) else "after_festival" if sim.after_festival(d) else "normal"

    def by_kind(res):
        flat = out.reshape(A, -1)
        o = {}
        for k in ("normal", "payday", "festival", "after_festival"):
            days = [d for d in range(FIRST, LAST + 1) if kind(d) == k]
            if days:
                un = sum(res["unmet_hours"][:, d * 24 + 8:d * 24 + 32].sum() for d in days)
                dem = sum(flat[:, d * 24 + 8:d * 24 + 32].sum() for d in days)
                o[k] = {"days": len(days), "missed_share": float(un / dem)}
        return o

    def summary(res):
        return {k: res[k] for k in ("unmet_bdt", "demand_bdt", "runout_hours", "runout_agent_days", "topups_bdt", "avg_cash_held",
                                    "commission_lost_bdt", "commission_earned_bdt")} | {"by_day_type": by_kind(res)}
    tradeoff = []
    for m in TRADEOFF:
        r = P.simulate(drain, supply, t_mix[m], FIRST, LAST)
        tradeoff.append({"mix": m, "missed_share": r["unmet_bdt"] / r["demand_bdt"], "avg_cash_held": r["avg_cash_held"],
                         "runout_agent_days": r["runout_agent_days"], "topups_bdt": r["topups_bdt"]})
    policy = {"plan_mix": P.PLAN_MIX, "tradeoff": tradeoff, "cycles": LAST - FIRST + 1, "agent_cycles": A * (LAST - FIRST + 1), "commission_rate": P.COMMISSION_RATE,
              "guess_from_last_week_plus_20pct": summary(res_guess), "guess_with_same_average_cash": summary(res_same) | {"scale": hi},
              "forecast_driven": summary(res_model)}
    policy["guess_from_last_week_plus_20pct"]["scale"] = GUESS_MARGIN

    # ---- the state each agent is in at 8 am (after the usual refill) under the guess policy, for the live views
    state_cash = P.simulate(out, inn, t_guess["cash"] * GUESS_MARGIN, F.MIN_DAY + 1, LAST, state_until=LAST)["after_refill"]
    state_float = P.simulate(inn, out, t_guess["float"] * GUESS_MARGIN, F.MIN_DAY + 1, LAST, state_until=LAST)["after_refill"]
    np.savez_compressed(M.ART / "liquidity_state.npz", state_cash=state_cash, state_float=state_float,
                        target_model_cash=t_model["cash"], target_model_float=t_model["float"])

    # ---- where would a new agent help? (uses the agents' own daily demand and the turned-away demand under the old method)
    daily = out[:, F.MIN_DAY:, :].sum(2).mean(1)
    unmet_per_day = res_guess["unmet_by_agent"] / (LAST - FIRST + 1)
    coverage = cov.recommend(agents, daily, unmet_per_day)

    report = {"quality": quality, "policy": policy, "coverage": coverage, "agents": int(A), "days": int(T),
              "train_days": [TRAIN_DAYS.start, TRAIN_DAYS.stop - 1], "test_days": [TEST_DAYS.start, TEST_DAYS.stop - 1]}
    (M.ART / "liquidity_report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    r = run()
    q, p = r["quality"], r["policy"]
    print(f"cash-out forecast, P50 error {q['pinball_p50_model']:.0f} vs {q['pinball_p50_same_hour_last_week']:.0f} for 'same hour last week'")
    print(f"busy-day (P90) forecast covered {q['p90_coverage_cash_out']:.1%} of hours (festival hours {q['p90_coverage_festival_hours']:.1%})")
    for name in ("guess_from_last_week_plus_20pct", "guess_with_same_average_cash", "forecast_driven"):
        s = p[name]
        print(f"{name:34s} missed {s['unmet_bdt'] / s['demand_bdt']:.2%} | by day type {({k: round(v['missed_share'], 3) for k, v in s['by_day_type'].items()})}")
    print("new-agent recommendations:", [(c['area'], c['new_agent_would_take_per_day']) for c in r['coverage']])
