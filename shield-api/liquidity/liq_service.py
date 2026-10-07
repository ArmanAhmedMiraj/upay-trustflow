"""Module 2 service: for every agent, how much cash will be needed, when will it run out, and how much should be added?

Loads the saved models and the precomputed state, so it starts in about a second. "Day" means a day of the simulated calendar;
three named scenarios make the demo easy: a normal day, the start of the month (payday), and the festival rush.
"""
from __future__ import annotations

import json

import numpy as np

import liq_features as F
import liq_model as M
import liq_policy as P
import liq_simulate as sim

SCENARIOS = {"normal": 82, "payday": 88, "festival": 74}          # all three are days the model never saw in training
SCENARIO_TEXT = {"normal": "A normal day", "payday": "Payday week (end of month)", "festival": "Festival rush (days before Eid)"}
DAY_MIN, DAY_MAX = F.MIN_DAY + 1, 88
HORIZON = 48
BN_DIGITS = "০১২৩৪৫৬৭৮৯"
DEMO_NAMES = ["Agent Babul", "Agent Shiuli", "Agent Monir"]
DEMO_PHONES = ["01811000001", "01811000002", "01811000003"]


# Estimated active upay users within walking distance of an agent. INVENTED for the demo (no real counts exist here):
# a base per area type, varied a little per agent. In a pilot this comes from upay's own active-user counts by location.
USERS_BASE = {"garment": 5200, "residential": 3100, "campus": 3800, "market": 4600, "transit": 4100}


def nearby_users_est(area_type: str, agent_id: int) -> int:
    return int(round(USERS_BASE.get(area_type, 3000) * (0.8 + 0.4 * ((agent_id * 0.6180339887) % 1.0)), -1))


def group_lakh(x) -> str:
    """1234567 -> '12,34,567' (Bangladesh groups the last three digits, then pairs)."""
    digits = str(int(round(abs(x))))
    if len(digits) <= 3:
        return ("-" if x < 0 else "") + digits
    head = digits[:-3]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ("-" if x < 0 else "") + ",".join(parts + [digits[-3:]])


def bn_num(x) -> str:
    return "".join(BN_DIGITS[int(c)] if c.isdigit() else c for c in group_lakh(x))


def clock_en(abs_hour: int) -> str:
    day, h = divmod(abs_hour, 24)
    h12 = h % 12 or 12
    return f"{['Today', 'Tomorrow', 'In two days'][min(day, 2)]} {h12}:00 {'am' if h < 12 else 'pm'}"


def clock_bn(abs_hour: int) -> str:
    day, h = divmod(abs_hour, 24)
    part = "রাত" if h < 4 else "ভোর" if h < 6 else "সকাল" if h < 12 else "দুপুর" if h < 15 else "বিকেল" if h < 18 else "সন্ধ্যা" if h < 20 else "রাত"
    return f"{['আজ', 'আগামীকাল', 'পরশু'][min(day, 2)]} {part} {bn_num(h % 12 or 12)}টা"


class World:
    def __init__(self):
        self.agents, self.out, self.inn = sim.simulate_agents()
        self.models = M.load()
        st = np.load(M.ART / "liquidity_state.npz")
        self.cash, self.efloat = st["state_cash"], st["state_float"]
        self.report = json.loads((M.ART / "liquidity_report.json").read_text())
        self._forecasts: dict[int, dict] = {}
        self.demo_agents = self._choose_demo_agents()

    # ------------------------------------------------------------ forecasts
    def forecast(self, day: int) -> dict:
        """Hourly forecasts for 72 hours starting at midnight of `day`, using only what was known before `day`."""
        if day not in self._forecasts:
            A = len(self.agents)
            frames = [M.predict(self.models, F.day_features(self.agents, self.out, self.inn, day + k, origin=day)) for k in range(3)]
            self._forecasts[day] = {c: np.concatenate([f[c].to_numpy().reshape(A, 24) for f in frames], axis=1)
                                    for c in ("p50_out", "p90_out", "p50_in", "p90_in")}
        return self._forecasts[day]

    @staticmethod
    def check_day(day: int) -> int:
        if not (DAY_MIN <= day <= DAY_MAX):
            raise ValueError(f"day must be between {DAY_MIN} and {DAY_MAX}")
        return day

    # ------------------------------------------------------------ one agent, one day
    def status(self, agent_id: int, day: int) -> dict:
        self.check_day(day)
        f = self.forecast(day)
        win = slice(8, 8 + HORIZON)
        p90o, p50o, p90i, p50i = (f[c][agent_id, win] for c in ("p90_out", "p50_out", "p90_in", "p50_in"))
        plan_out, plan_in = P.plan(p50o, p90o), P.plan(p50i, p90i)         # what we plan for: between a normal and a busy day
        cash, efloat = float(self.cash[agent_id, day]), float(self.efloat[agent_id, day])
        need_cash = float(P.requirement(plan_out[None, :24], p50i[None, :24])[0])
        need_float = float(P.requirement(plan_in[None, :24], p50o[None, :24])[0])
        k = int(P.first_shortfall(np.array([cash]), plan_out[None], p50i[None])[0])
        kf = int(P.first_shortfall(np.array([efloat]), plan_in[None], p50o[None])[0])
        run_abs = 8 + k if k >= 0 else None
        refill_cash = max(0.0, need_cash - cash)
        refill_float = max(0.0, need_float - efloat)
        # red: expected to run out within 24 hours (even on a normal day); yellow: could run out within 12 hours if the day is busier
        k50 = int(P.first_shortfall(np.array([cash]), p50o[None], p50i[None])[0])
        kf50 = int(P.first_shortfall(np.array([efloat]), p50i[None], p50o[None])[0])
        red = (0 <= k50 < 24) or (0 <= kf50 < 24)
        yellow = (0 <= k < 12) or (0 <= kf < 12)
        status = "red" if red else "yellow" if yellow else "green"
        ag = self.agents.iloc[agent_id]
        name = DEMO_NAMES[self.demo_agents.index(agent_id)] if agent_id in self.demo_agents else f"Agent #{agent_id + 1}"
        s = {
            "agent_id": int(agent_id), "name": name, "area": ag.area, "area_type": ag.area_type, "lat": round(float(ag.lat), 4), "lng": round(float(ag.lng), 4),
            "nearby_users_est": nearby_users_est(ag.area_type, int(agent_id)),
            "cash_now": round(cash), "float_now": round(efloat), "p50_out_24h": round(float(p50o[:24].sum())), "p90_out_24h": round(float(plan_out[:24].sum())),
            "need_cash_24h": round(need_cash), "need_float_24h": round(need_float),
            "runout_hours_from_now": k50 if k50 >= 0 else (k if k >= 0 else None),
            "runout_label": clock_en(8 + (k50 if k50 >= 0 else k)) if (k50 >= 0 or k >= 0) else None,
            "float_runout_hours_from_now": kf if kf >= 0 else None,
            "refill_cash": round(refill_cash), "refill_float": round(refill_float), "status": status, "day": day,
        }
        run_abs = 8 + s["runout_hours_from_now"] if s["runout_hours_from_now"] is not None else None
        s["runout_label_bn"] = clock_bn(run_abs) if run_abs is not None else None
        s["briefing_en"], s["briefing_bn"] = self.briefing(s, run_abs)
        return s

    def briefing(self, s: dict, run_abs: int | None) -> tuple[str, str]:
        peak = int(np.argmax(self.forecast(s["day"])["p90_out"][s["agent_id"], 8:8 + 24])) + 8
        if s["refill_cash"] > 0 and run_abs is not None:
            en = (f"Your cash may run out around {clock_en(run_abs).lower()}. Add ৳{group_lakh(s['refill_cash'])} cash before then. "
                  f"You need about ৳{group_lakh(s['need_cash_24h'])} for the next 24 hours; the busiest hour is around {peak % 12 or 12}:00 {'am' if peak < 12 else 'pm'}.")
            bn = (f"{clock_bn(run_abs)}-এর দিকে আপনার নগদ শেষ হয়ে যেতে পারে। তার আগে ৳{bn_num(s['refill_cash'])} নগদ যোগ করুন। "
                  f"আগামী ২৪ ঘণ্টায় প্রায় ৳{bn_num(s['need_cash_24h'])} লাগবে।")
        elif s["refill_float"] > 0:
            en = f"Your e-float may run short for deposits. Add ৳{group_lakh(s['refill_float'])} e-float; you need about ৳{group_lakh(s['need_float_24h'])} for the next 24 hours."
            bn = f"জমার জন্য আপনার ই-ফ্লোট কম পড়তে পারে। ৳{bn_num(s['refill_float'])} ই-ফ্লোট যোগ করুন। আগামী ২৪ ঘণ্টায় প্রায় ৳{bn_num(s['need_float_24h'])} লাগবে।"
        else:
            en = f"You have enough cash for the next 24 hours. Customers may take out about ৳{group_lakh(s['p90_out_24h'])}."
            bn = f"আগামী ২৪ ঘণ্টার জন্য আপনার নগদ যথেষ্ট। গ্রাহকরা প্রায় ৳{bn_num(s['p90_out_24h'])} তুলতে পারেন।"
        return en, bn

    def detail(self, agent_id: int, day: int) -> dict:
        s = self.status(agent_id, day)
        f = self.forecast(day)
        win = slice(8, 8 + HORIZON)
        p50o, p90o, p50i, p90i = (f[c][agent_id, win] for c in ("p50_out", "p90_out", "p50_in", "p90_in"))
        cash_path = s["cash_now"] - np.cumsum(P.plan(p50o, p90o) - p50i)
        float_path = s["float_now"] - np.cumsum(P.plan(p50i, p90i) - p50o)
        return s | {
            "hours": [(8 + i) % 24 for i in range(HORIZON)],
            "p50_out": np.round(p50o).astype(int).tolist(), "p90_out": np.round(p90o).astype(int).tolist(),
            "p50_in": np.round(p50i).astype(int).tolist(), "p90_in": np.round(p90i).astype(int).tolist(),
            "cash_path_plan": np.round(cash_path).astype(int).tolist(), "float_path_plan": np.round(float_path).astype(int).tolist(),
        }

    # ------------------------------------------------------------ all agents
    def overview(self, day: int) -> dict:
        self.check_day(day)
        rows = [self.status(a, day) for a in range(len(self.agents))]
        order = {"red": 0, "yellow": 1, "green": 2}
        rows.sort(key=lambda r: (order[r["status"]], -(r["refill_cash"] + r["refill_float"])))
        counts = {c: sum(r["status"] == c for r in rows) for c in ("red", "yellow", "green")}
        scenario = next((k for k, v in SCENARIOS.items() if v == day), None)
        return {"day": day, "scenario": scenario, "calendar": self.calendar(day), "counts": counts,
                "total_refill_cash": sum(r["refill_cash"] for r in rows), "total_refill_float": sum(r["refill_float"] for r in rows),
                "agents": rows}

    def days(self) -> list[dict]:
        """Every day the forecaster can cover, with what makes it unusual (payday, festival rush ...), for the calendar view."""
        scen = {v: k for k, v in SCENARIOS.items()}
        return [{"day": d, "scenario": scen.get(d), **self.calendar(d)} for d in range(DAY_MIN, DAY_MAX + 1)]

    @staticmethod
    def calendar(day: int) -> dict:
        return {"day_of_month": sim.dom(day), "weekday": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][sim.dow(day)],
                "payday": bool(sim.is_payday(day)), "festival_rush": bool(sim.in_festival(day)), "days_to_festival": sim.days_to_festival(day)}

    def _choose_demo_agents(self) -> list[int]:
        """Pick three agents who tell the story: tight on cash during the festival rush, fine on a normal day."""
        chosen = []
        for a in range(len(self.agents)):
            if len(chosen) == 3:
                break
            if a in chosen:
                continue
            self.demo_agents = chosen
            if self.status(a, SCENARIOS["festival"])["status"] == "red" and self.status(a, SCENARIOS["normal"])["status"] == "green":
                chosen.append(a)
        return chosen or [0, 1, 2]

    def agent_for_phone(self, phone: str) -> int | None:
        return self.demo_agents[DEMO_PHONES.index(phone)] if phone in DEMO_PHONES else None


_world: World | None = None


def get_world() -> World:
    global _world
    if _world is None:
        _world = World()
    return _world
