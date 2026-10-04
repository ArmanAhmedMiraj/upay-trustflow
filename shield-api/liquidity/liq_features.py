"""Features for the cash forecast, built point in time.

To forecast the 24 hours that start on the morning of `origin`, we may use only what was known before that morning:
the calendar (known in advance), each agent's own earlier days, and the same hour on earlier weeks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import liq_simulate as sim

FEATURES = ["hour", "dow", "dom", "is_payday", "days_to_festival", "in_festival", "after_festival", "is_haat", "area_code", "log_base_out",
            "log_base_in", "lag168_out_ratio", "how4_out_ratio", "lag168_in_ratio", "how4_in_ratio"]
MIN_DAY = 28           # the first day with four weeks of history behind it


def day_features(agents: pd.DataFrame, out: np.ndarray, inn: np.ndarray, day: int, origin: int | None = None) -> pd.DataFrame:
    """One row per (agent, hour) for `day`, using only days before `origin` (default: the day itself)."""
    origin = day if origin is None else origin
    A = len(agents)
    hist = slice(max(origin - 28, 0), origin)
    # the agent's "normal" hourly level: the MEDIAN of the last 28 days, so a payday week or a festival rush does not distort it
    base_out = np.median(out[:, hist, :].sum(2), axis=1) / 24 + 1.0
    base_in = np.median(inn[:, hist, :].sum(2), axis=1) / 24 + 1.0
    lag = [day - 7 * k for k in (1, 2, 3, 4)]
    if min(lag) < 0 or max(lag) >= origin:
        raise ValueError("not enough earlier history for this day")
    lag168_out, lag168_in = out[:, lag[0], :], inn[:, lag[0], :]
    how4_out = np.mean([out[:, d, :] for d in lag], axis=0)
    how4_in = np.mean([inn[:, d, :] for d in lag], axis=0)
    h = np.tile(np.arange(24), A)
    rep = lambda x: np.repeat(x, 24)  # noqa: E731
    df = pd.DataFrame({
        "agent_id": rep(agents.agent_id.to_numpy()), "day": day, "hour": h, "dow": sim.dow(day), "dom": sim.dom(day),
        "is_payday": sim.is_payday(day), "days_to_festival": sim.days_to_festival(day), "in_festival": sim.in_festival(day),
        "after_festival": sim.after_festival(day),
        "is_haat": (rep(agents.haat_dow.to_numpy()) == sim.dow(day)).astype(int),
        "area_code": rep(agents.area_type.map({t: i for i, t in enumerate(sim.AREA_TYPES)}).to_numpy()),
        "log_base_out": np.log(rep(base_out)), "log_base_in": np.log(rep(base_in)),
        "lag168_out_ratio": lag168_out.ravel() / rep(base_out), "how4_out_ratio": how4_out.ravel() / rep(base_out),
        "lag168_in_ratio": lag168_in.ravel() / rep(base_in), "how4_in_ratio": how4_in.ravel() / rep(base_in),
    })
    df["base_out"] = rep(base_out)
    df["base_in"] = rep(base_in)
    return df


def training_frame(agents, out, inn, days) -> pd.DataFrame:
    frames = []
    for d in days:
        f = day_features(agents, out, inn, d)
        f["y_out"], f["y_in"] = out[:, d, :].ravel(), inn[:, d, :].ravel()
        frames.append(f)
    return pd.concat(frames, ignore_index=True)
