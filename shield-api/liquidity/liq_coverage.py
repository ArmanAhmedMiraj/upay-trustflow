"""Where would another agent help most?

For each map cell (about 2 km square) we compare the cash-out demand per agent with the city median. A cell where each agent
carries much more than the median is under-served: a new agent there would take a share of that demand.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import liq_simulate as sim

CELL = 0.02          # degrees of latitude / longitude


def nearest_area(lat: float, lng: float) -> str:
    return min(sim.AREAS, key=lambda n: (sim.AREAS[n][0] - lat) ** 2 + (sim.AREAS[n][1] - lng) ** 2)


def recommend(agents: pd.DataFrame, daily_demand: np.ndarray, unmet_per_day: np.ndarray, top: int = 5, min_pressure: float = 1.15) -> list[dict]:
    df = agents[["agent_id", "lat", "lng", "area"]].copy()
    df["demand"], df["unmet"] = daily_demand, unmet_per_day
    df["cx"], df["cy"] = np.floor(df.lat / CELL).astype(int), np.floor(df.lng / CELL).astype(int)
    median = float(np.median(daily_demand))
    cells = df.groupby(["cx", "cy"]).agg(agents=("agent_id", "count"), demand=("demand", "sum"), unmet=("unmet", "sum"),
                                         lat=("lat", "mean"), lng=("lng", "mean")).reset_index()
    cells["per_agent"] = cells.demand / cells.agents
    cells["pressure"] = cells.per_agent / median
    cells["new_agent_would_take"] = cells.demand / (cells.agents + 1)
    cells["unmet_share"] = cells.unmet / cells.demand
    cells["area"] = [nearest_area(la, ln) for la, ln in zip(cells.lat, cells.lng)]
    pick = (cells[cells.pressure >= min_pressure].sort_values("new_agent_would_take", ascending=False)
            .drop_duplicates("area").head(top))                       # one suggestion per area, the best cell in it
    out = []
    for _, c in pick.iterrows():
        area = c.area
        out.append({
            "area": area, "lat": round(float(c.lat), 4), "lng": round(float(c.lng), 4), "agents_here": int(c.agents),
            "demand_per_agent_per_day": round(float(c.per_agent)), "times_city_median": round(float(c.pressure), 2),
            "new_agent_would_take_per_day": round(float(c.new_agent_would_take)),
            "turned_away_share": round(float(c.unmet_share), 3),
            "reason": (f"Each of the {int(c.agents)} agents near {area} handles about {c.pressure:.1f}x the city's typical daily cash-out; "
                       f"a new agent would take roughly ৳{c.new_agent_would_take:,.0f} a day."),
        })
    return out
