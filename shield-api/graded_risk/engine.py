"""Scores one transfer and explains it, signal by signal.

Contributions come from the model itself (TreeSHAP, via LightGBM `pred_contrib`), measured in log-odds and then
converted to percentage points so a judge can read "this signal added 9.4 points".

How log-odds become points: risk = sigmoid(base + sum of contributions). Each signal gets the same share of the
move from the baseline risk to the final risk as its share of the log-odds move (the chord slope of the sigmoid),
so the points add up exactly: baseline + all signals = final risk.
"""
from __future__ import annotations

import json
import pathlib
import threading

import lightgbm as lgb
import numpy as np

from graded_risk import catalogue as cat

ARTIFACT_DIR = pathlib.Path(__file__).resolve().parent / "artifacts"
ACTIONS = {"low": "allow", "note": "allow_with_note", "high": "safety_check", "very_high": "hold_30min"}
_lock = threading.Lock()
_cache: dict = {}


class Engine:
    def __init__(self, directory: pathlib.Path = ARTIFACT_DIR):
        self.booster = lgb.Booster(model_file=str(directory / "model.txt"))
        cal = json.loads((directory / "calibration.json").read_text())
        self.a, self.b = cal["a"], cal["b"]
        self.tiers = json.loads((directory / "tiers.json").read_text())
        rep = directory / "report.json"
        self.report = json.loads(rep.read_text()) if rep.exists() else None

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _row(features: dict, muted: set) -> np.ndarray:
        missing = [n for n in cat.FEATURE_NAMES if n not in features]
        if missing:
            raise ValueError(f"missing signals: {missing[:3]}")
        return np.array([[cat.TYPICAL[n] if n in muted else float(features[n]) for n in cat.FEATURE_NAMES]])

    def _terms(self, x: np.ndarray):
        """(log-odds contribution of every signal, calibrated base log-odds) for the rows in x."""
        c = self.booster.predict(x, pred_contrib=True)
        return c[:, :-1] * self.a, c[:, -1] * self.a + self.b

    @staticmethod
    def _sigmoid(z):
        return 1.0 / (1.0 + np.exp(-z))

    def risk(self, features: dict, muted: set | None = None) -> float:
        z = self.booster.predict(self._row(features, muted or set()), raw_score=True)[0]
        return float(self._sigmoid(self.a * z + self.b))

    def tier(self, p: float) -> str:
        if p >= self.tiers["very_high"]:
            return "very_high"
        if p >= self.tiers["high"]:
            return "high"
        if p >= self.tiers["note"]:
            return "note"
        return "low"

    # ------------------------------------------------------------ the explanation
    def explain(self, features: dict, mute_sides: list[str] | None = None, mute_signals: list[str] | None = None) -> dict:
        """Risk %, tier, action, a point contribution for every signal, and the sender/recipient/combination split."""
        muted = set(mute_signals or [])
        for s in mute_sides or []:
            if s not in cat.SIDES:
                raise ValueError(f"unknown side: {s}")
            muted |= set(cat.names_of(s))
        unknown = muted - set(cat.FEATURE_NAMES)
        if unknown:
            raise ValueError(f"unknown signals: {sorted(unknown)[:3]}")

        x = self._row(features, muted)
        contrib, base_z = self._terms(x)
        contrib, base_z = contrib[0], float(base_z[0])
        total = float(contrib.sum())
        p0 = float(self._sigmoid(base_z))
        p = float(self._sigmoid(base_z + total))
        # chord slope: (p - p0) / total, which stays bounded (<= 0.25) even when positives and negatives cancel
        slope = (p - p0) / total if abs(total) > 1e-6 else p0 * (1 - p0)

        rows = []
        for i, name in enumerate(cat.FEATURE_NAMES):
            f = cat.FEATURES[name]
            v = float(x[0][i])
            rows.append({"signal": name, "side": f.side, "label": f.label, "value": round(v, 3),
                         "text": f.text(v), "present": bool(f.present(v)), "muted": name in muted,
                         "points": round(100 * slope * float(contrib[i]), 2), "why": f.why})
        rows.sort(key=lambda r: -abs(r["points"]))
        sides = {s: round(sum(r["points"] for r in rows if r["side"] == s), 2) for s in cat.SIDES}

        # the combination test: what would the model say if only ONE side's signals were real?
        ref = {n: cat.TYPICAL[n] for n in cat.FEATURE_NAMES}
        keep = lambda ss: {n: (features[n] if cat.FEATURES[n].side in ss and n not in muted else ref[n]) for n in cat.FEATURE_NAMES}  # noqa: E731
        p_ref = self.risk(ref)
        p_sender = self.risk(keep({"sender"}))
        p_recip = self.risk(keep({"recipient", "pair"}))
        extra = (p - p_ref) - (p_sender - p_ref) - (p_recip - p_ref)
        tier = self.tier(p)
        return {
            "risk_pct": round(100 * min(max(p, 0.001), 0.999), 1), "tier": tier, "action": ACTIONS[tier],
            "baseline_pct": round(100 * p0, 1), "sides": sides, "contributions": rows,
            "combination": {"typical_transfer_pct": round(100 * p_ref, 1), "sender_signals_only_pct": round(100 * p_sender, 1),
                            "recipient_signals_only_pct": round(100 * p_recip, 1), "all_signals_pct": round(100 * p, 1),
                            "extra_from_combining_points": round(100 * extra, 1)},
            "muted": sorted(muted), "signals_present": sum(1 for r in rows if r["present"] and not r["muted"]),
            "tier_thresholds_pct": {k: round(100 * v, 1) for k, v in self.tiers.items()},
        }


def get_engine() -> Engine:
    with _lock:
        if "engine" not in _cache:
            _cache["engine"] = Engine()
        return _cache["engine"]
