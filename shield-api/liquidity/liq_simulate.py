"""Synthetic agents for Module 2: hourly cash-out and cash-in demand for 120 agents across Dhaka.

Everything is invented. The patterns are the ones agents describe: lunch and evening peaks, a payday surge at the end and start
of the month, a festival rush in the days before Eid, a weekly haat (market) day for market agents, quieter Fridays.

Time: day 0 is a Monday. "dom" (day of month) is day % 30 + 1.  Hours are 0-23.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# name: (latitude, longitude, area type)
AREAS = {
    "Mirpur-10": (23.807, 90.368, "garment"), "Tejgaon": (23.760, 90.393, "garment"), "Savar": (23.858, 90.266, "garment"),
    "Uttara": (23.874, 90.399, "residential"), "Gulshan": (23.792, 90.414, "residential"), "Badda": (23.780, 90.426, "residential"),
    "Dhanmondi": (23.746, 90.376, "campus"), "Motijheel": (23.733, 90.417, "market"), "Chawkbazar": (23.717, 90.397, "market"),
    "Jatrabari": (23.710, 90.434, "transit"), "Farmgate": (23.757, 90.389, "transit"), "Mohakhali": (23.778, 90.405, "transit"),
}
AREA_TYPES = ["garment", "residential", "campus", "market", "transit"]
FESTIVALS = [(44, 49), (72, 77)]          # the days of the pre-festival rush (the second one falls in the test period)
DAYS = 90


def _bump(centre: float, width: float) -> np.ndarray:
    h = np.arange(24)
    return np.exp(-0.5 * ((h - centre) / width) ** 2)


def hour_profile(area_type: str) -> np.ndarray:
    """Share of a day's demand that falls in each hour (sums to 1)."""
    shape = {
        "market": 0.9 * _bump(12, 2.0) + 0.8 * _bump(18, 1.8),
        "residential": 0.7 * _bump(11, 2.0) + 1.0 * _bump(19, 2.2),
        "garment": 0.8 * _bump(13, 1.4) + 1.1 * _bump(18.5, 1.6),
        "campus": 1.0 * _bump(13, 2.6),
        "transit": 1.0 * _bump(8, 1.6) + 0.9 * _bump(18, 2.0),
    }[area_type] + 0.04
    shape[:6] *= 0.15                                       # almost nothing between midnight and 6 am
    return shape / shape.sum()


def dow(day: int) -> int:
    return day % 7


def dom(day: int) -> int:
    return day % 30 + 1


def is_payday(day: int) -> int:
    return int(dom(day) <= 5 or dom(day) >= 28)


def days_to_festival(day: int) -> int:
    """0 if the rush is on, otherwise days until the next one (capped at 10)."""
    for start, end in FESTIVALS:
        if start <= day <= end:
            return 0
        if day < start:
            return min(start - day, 10)
    return 10


def in_festival(day: int) -> int:
    return int(any(s <= d <= e for d in [day] for s, e in FESTIVALS))


def after_festival(day: int) -> int:
    return int(any(e < day <= e + 3 for _, e in FESTIVALS))


def simulate_agents(n_agents: int = 120, days: int = DAYS, seed: int = 42):
    """Returns (agents table, cash-out array, cash-in array); arrays have shape (agents, days, 24), in taka."""
    rng = np.random.default_rng(seed)
    names = list(AREAS)
    weights = np.array([2, 2, 1, 2, 2, 1, 1, 2, 1, 1, 1, 1], dtype=float)
    area = rng.choice(len(names), n_agents, p=weights / weights.sum())
    rows = []
    for a in range(n_agents):
        name = names[area[a]]
        lat, lng, typ = AREAS[name]
        rows.append(dict(agent_id=a, area=name, area_type=typ, lat=lat + rng.normal(0, 0.006), lng=lng + rng.normal(0, 0.006),
                         scale=float(rng.lognormal(np.log(80000), 0.5)),                 # typical cash-out per day, in taka
                         haat_dow=int(rng.integers(0, 7)) if typ == "market" else -1))
    agents = pd.DataFrame(rows)

    out = np.zeros((n_agents, days, 24))
    inn = np.zeros((n_agents, days, 24))
    for a, ag in agents.iterrows():
        prof = hour_profile(ag.area_type)
        prof_in = np.roll(prof, 3) * 0.5 + prof * 0.5                                   # deposits come a little later in the day
        for d in range(days):
            m_out = m_in = 1.0
            if d % 7 in (4, 5):                                                          # Friday and Saturday
                m_out *= 0.75; m_in *= 0.8
            if is_payday(d):
                m_out *= {"garment": 1.9, "residential": 1.3}.get(ag.area_type, 1.5); m_in *= 0.9
            for s, e in FESTIVALS:
                if s <= d <= e:
                    ramp = 1.8 + 0.5 * (d - s) / (e - s)
                    m_out *= ramp * (1.5 if ag.area_type == "garment" else 1.0); m_in *= 1.25
                elif e < d <= e + 3:
                    m_out *= 0.55; m_in *= 0.8
            if ag.haat_dow == d % 7:
                m_out *= 1.7; m_in *= 1.3
            noise_out = rng.lognormal(0, 0.25, 24) * np.where(rng.random(24) < 0.01, 2.0, 1.0)
            noise_in = rng.lognormal(0, 0.25, 24)
            out[a, d] = ag.scale * m_out * prof * noise_out
            inn[a, d] = 0.55 * ag.scale * m_in * prof_in * noise_in
    return agents, out.round(), inn.round()
