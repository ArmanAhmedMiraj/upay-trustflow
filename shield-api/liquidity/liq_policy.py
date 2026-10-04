"""How much cash must an agent hold, when will it run out, and what does a refill policy achieve?

Plain arithmetic, kept separate from the learned model so an operator can audit it:
    cash needed = the largest cumulative (cash taken out - cash deposited) over the planning window.
"""
from __future__ import annotations

import numpy as np

COMMISSION_RATE = 0.005       # assumption: an agent earns 0.5% on each cash-out
REFILL_HOUR = 8               # the daily refill happens at 8 am
PLAN_MIX = 0.6                # plan on 60% of the way from the normal-day (P50) to the busy-day (P90) forecast; chosen on validation days


def plan(p50: np.ndarray, p90: np.ndarray, mix: float = PLAN_MIX) -> np.ndarray:
    """The demand we plan for: between the normal-day and the busy-day forecast.

    Adding up 24 separate busy-HOUR forecasts would plan for a day far busier than any real busy day, so we blend instead."""
    return p50 + mix * (p90 - p50)


def requirement(drain: np.ndarray, supply: np.ndarray) -> np.ndarray:
    """Starting balance needed so that it never goes below zero. Arrays have shape (agents, hours)."""
    return np.maximum(np.cumsum(drain - supply, axis=1).max(axis=1), 0.0)


def first_shortfall(balance: np.ndarray, drain: np.ndarray, supply: np.ndarray) -> np.ndarray:
    """Hour index (0-based, counted from the start of the window) at which the balance first goes below zero, or -1."""
    path = balance[:, None] - np.cumsum(drain - supply, axis=1)
    hit = path < 0
    return np.where(hit.any(axis=1), hit.argmax(axis=1), -1)


def cycle(arr: np.ndarray, day: int, hours: int = 24) -> np.ndarray:
    """The `hours` hours that start at the refill hour of `day`: arr has shape (agents, days, 24)."""
    flat = arr.reshape(arr.shape[0], -1)
    start = day * 24 + REFILL_HOUR
    return flat[:, start:start + hours]


def simulate(drain: np.ndarray, supply: np.ndarray, target: np.ndarray, first_day: int, last_day: int, state_until: int | None = None) -> dict:
    """Run a policy hour by hour. target[a, d] is the cash the agent should hold after the refill at 8 am on day d.

    Customers are served from the cash on hand; whatever cannot be served is lost (a customer turned away).
    """
    A = drain.shape[0]
    flat_d, flat_s = drain.reshape(A, -1), supply.reshape(A, -1)
    total = flat_d.shape[1]
    end_day = last_day if state_until is None else max(last_day, state_until)
    cycles_end = (last_day + 1) * 24 + REFILL_HOUR                 # the last simulated cycle ends here (exclusive)
    cash = np.zeros(A)
    unmet_hours = np.zeros((A, total))
    topups = np.zeros((A, end_day + 1))
    after_refill = np.full((A, end_day + 1), np.nan)
    held = []
    for t in range(first_day * 24 + REFILL_HOUR, max(cycles_end, end_day * 24 + REFILL_HOUR + 1)):
        if t % 24 == REFILL_HOUR and t // 24 <= end_day:
            d = t // 24
            need = np.maximum(target[:, d] - cash, 0.0)
            topups[:, d] = need
            cash = cash + need
            after_refill[:, d] = cash
        if t >= total or t >= cycles_end:
            continue
        served = np.minimum(flat_d[:, t], cash)
        unmet_hours[:, t] = flat_d[:, t] - served
        cash = cash - served + flat_s[:, t]
        held.append(cash.mean())
    window = slice(first_day * 24 + REFILL_HOUR, (last_day + 1) * 24 + REFILL_HOUR)
    u = unmet_hours[:, window]
    served_total = flat_d[:, window].sum() - u.sum()
    return {
        "unmet_bdt": float(u.sum()), "demand_bdt": float(flat_d[:, window].sum()),
        "runout_hours": int((u > 0).sum()),
        "runout_agent_days": int((u.reshape(A, -1, 24).sum(2) > 0).sum()),
        "topups_bdt": float(topups[:, first_day:last_day + 1].sum()), "avg_cash_held": float(np.mean(held)),
        "commission_lost_bdt": float(u.sum() * COMMISSION_RATE), "commission_earned_bdt": float(served_total * COMMISSION_RATE),
        "unmet_by_agent": u.sum(1), "after_refill": after_refill, "topups": topups, "unmet_hours": unmet_hours,
    }
