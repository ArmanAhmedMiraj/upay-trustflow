"""Quantile models: how much cash will customers take out (and deposit) in each hour?

Four LightGBM models: cash-out at the 50th and 90th percentile (normal day and busy day) and cash-in at the 50th and 90th.
They predict demand as a RATIO of the agent's recent average, so one model serves big and small agents alike.
"""
from __future__ import annotations

import json
import pathlib

import lightgbm as lgb
import numpy as np
import pandas as pd

from liq_features import FEATURES

ART = pathlib.Path(__file__).parent / "artifacts"
TARGETS = {"out_q50": ("y_out", "base_out", 0.5), "out_q90": ("y_out", "base_out", 0.9),
           "in_q50": ("y_in", "base_in", 0.5), "in_q90": ("y_in", "base_in", 0.9)}
PARAMS = dict(n_estimators=250, learning_rate=0.05, num_leaves=31, min_child_samples=40, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.9, random_state=42, verbosity=-1, n_jobs=-1)


def train(frame: pd.DataFrame) -> dict:
    models = {}
    for name, (target, base, alpha) in TARGETS.items():
        m = lgb.LGBMRegressor(objective="quantile", alpha=alpha, **PARAMS)
        m.fit(frame[FEATURES], frame[target] / frame[base])
        models[name] = m.booster_
    return models


def save(models: dict) -> None:
    ART.mkdir(exist_ok=True)
    for name, booster in models.items():
        booster.save_model(str(ART / f"{name}.txt"))


def load() -> dict:
    return {name: lgb.Booster(model_file=str(ART / f"{name}.txt")) for name in TARGETS}


def exists() -> bool:
    return all((ART / f"{n}.txt").exists() for n in TARGETS)


def predict(models: dict, frame: pd.DataFrame) -> pd.DataFrame:
    """Adds p50_out, p90_out, p50_in, p90_in in taka (never negative, p90 never below p50)."""
    out = frame.copy()
    for name, (target, base, alpha) in TARGETS.items():
        out[name] = np.maximum(models[name].predict(frame[FEATURES]) * frame[base], 0)
    out["out_q90"] = np.maximum(out["out_q90"], out["out_q50"])
    out["in_q90"] = np.maximum(out["in_q90"], out["in_q50"])
    return out.rename(columns={"out_q50": "p50_out", "out_q90": "p90_out", "in_q50": "p50_in", "in_q90": "p90_in"})


def pinball(y: np.ndarray, q: np.ndarray, alpha: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(alpha * d, (alpha - 1) * d)))
