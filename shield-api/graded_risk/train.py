"""Train, calibrate and test the graded-risk model.

Run from the repository root:
    python shield-api/graded_risk/train.py

What it proves (all written to artifacts/report.json and printed):
 1. Both sides are needed: sender-only, recipient-only and both-sides models are compared.
 2. No single signal carries the model: each signal is switched off in turn and the damage is measured.
 3. Scores are graded: how many scams score a flat 100%? (the answer should be none)
 4. Each scam story is caught for a different reason (recall per story, and which side drove it).
 5. Probabilities are honest: a calibration table.
"""
from __future__ import annotations

import json
import pathlib
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # so that `graded_risk` can be imported when this file is run as a script

from graded_risk import catalogue as cat  # noqa: E402
from graded_risk import synth  # noqa: E402

ARTIFACTS = HERE / "artifacts"
SEED = 11
# a tier must keep the share of GENUINE transfers it disturbs under this budget
FRICTION_BUDGET = {"note": 0.05, "high": 0.015, "very_high": 0.003}
PARAMS = dict(n_estimators=450, learning_rate=0.04, num_leaves=8, max_depth=4, min_child_samples=150,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=10.0, random_state=SEED,
              verbosity=-1, n_jobs=-1)


def fit(train: pd.DataFrame, feats: list[str]) -> lgb.LGBMClassifier:
    mono = [cat.FEATURES[f].direction for f in feats]
    return lgb.LGBMClassifier(monotone_constraints=mono, **PARAMS).fit(train[feats], train["label"])


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def threshold_for_budget(genuine_scores: np.ndarray, budget: float) -> float:
    for t in np.unique(genuine_scores):
        if (genuine_scores >= t).mean() <= budget:
            return float(t)
    return float(genuine_scores.max() + 1e-6)


def mute(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    out = df.copy()
    for n in names:
        out[n] = cat.TYPICAL[n]
    return out


def metrics(y, p, thr_hold) -> dict:
    return {"pr_auc": round(float(average_precision_score(y, p)), 3), "roc_auc": round(float(roc_auc_score(y, p)), 3),
            "caught_at_hold_tier": round(float((p[y == 1] >= thr_hold).mean()), 3)}


def main() -> None:
    df = synth.generate(200_000)
    train, rest = train_test_split(df, test_size=0.4, random_state=SEED, stratify=df["label"])
    cal, test = train_test_split(rest, test_size=0.5, random_state=SEED, stratify=rest["label"])
    F = cat.FEATURE_NAMES

    # ---- main model + Platt calibration (a monotone stretch, so the ranking and the explanations are unchanged)
    model = fit(train, F)
    raw_cal = model.predict_proba(cal[F])[:, 1]
    platt = LogisticRegression(C=1e6).fit(logit(raw_cal).reshape(-1, 1), cal["label"])
    a, b = float(platt.coef_[0][0]), float(platt.intercept_[0])

    def prob(frame, feats=F, mdl=model):
        return 1 / (1 + np.exp(-(a * logit(mdl.predict_proba(frame[feats])[:, 1]) + b)))

    p_cal, p_test = prob(cal), prob(test)
    tiers = {t: threshold_for_budget(p_cal[cal["label"].to_numpy() == 0], bud) for t, bud in FRICTION_BUDGET.items()}
    y = test["label"].to_numpy()
    gen = y == 0
    hold = tiers["very_high"]

    # ---- 1. which sides are needed?  (each side-model gets its own thresholds at the same friction budget)
    sides = {}
    for name, feats in {"sender signals only": cat.names_of("sender"),
                        "recipient signals only": cat.names_of("recipient"),
                        "sender + recipient (no link signals)": cat.names_of("sender") + cat.names_of("recipient"),
                        "all three sides": F}.items():
        m = model if feats == F else fit(train, feats)
        pc, pt = m.predict_proba(cal[feats])[:, 1], m.predict_proba(test[feats])[:, 1]
        thr = threshold_for_budget(pc[cal["label"].to_numpy() == 0], FRICTION_BUDGET["very_high"])
        sides[name] = {**metrics(y, pt, thr), "signals": len(feats)}

    # ---- 2. switch each signal off in turn (set to a harmless value) and measure the damage
    base_pr = average_precision_score(y, p_test)
    base_caught = (p_test[y == 1] >= hold).mean()
    ablation = []
    for f in F:
        pm = prob(mute(test, [f]))
        ablation.append({"signal": f, "side": cat.FEATURES[f].side,
                         "pr_auc_drop": round(float(base_pr - average_precision_score(y, pm)), 3),
                         "caught_drop": round(float(base_caught - (pm[y == 1] >= hold).mean()), 3)})
    ablation.sort(key=lambda r: -r["pr_auc_drop"])
    side_off = {}
    for s in cat.SIDES:
        pm = prob(mute(test, cat.names_of(s)))
        side_off[s] = {"pr_auc": round(float(average_precision_score(y, pm)), 3),
                       "caught_at_hold_tier": round(float((pm[y == 1] >= hold).mean()), 3)}

    # ---- 3. graded scores: how are scam scores spread?
    sc = p_test[y == 1]
    spread = {"scams_scoring_99_or_more_pct": round(float((sc >= .99).mean() * 100), 2),
              "scam_score_percentiles": {str(q): round(float(np.percentile(sc, q) * 100), 1) for q in (5, 25, 50, 75, 95)},
              "genuine_score_percentiles": {str(q): round(float(np.percentile(p_test[gen], q) * 100), 1) for q in (50, 95, 99)},
              "distinct_scores_in_test": int(len(np.unique(np.round(p_test * 100, 0))))}

    # ---- 4. per story: caught, and which side usually drives it (contribution split on that story)
    contrib = model.booster_.predict(test[F], pred_contrib=True)[:, :-1] * a
    side_idx = {s: [F.index(n) for n in cat.names_of(s)] for s in cat.SIDES}
    stories = {}
    for st, g in test.groupby("story"):
        idx = test.index.get_indexer(g.index)
        pos = np.maximum(contrib[idx], 0)
        tot = pos.sum() or 1.0
        stories[st] = {"label": int(g["label"].iloc[0]), "n": int(len(g)),
                       "caught_at_hold_tier_pct": round(float((p_test[idx] >= hold).mean() * 100), 1),
                       "median_risk_pct": round(float(np.median(p_test[idx]) * 100), 1),
                       "push_share_pct": {s: round(float(pos[:, side_idx[s]].sum() / tot * 100), 0) for s in cat.SIDES}}

    # ---- 5. calibration
    bands = [0, .02, .05, .1, .2, .4, .6, .8, 1.0001]
    calib = []
    for lo, hi in zip(bands[:-1], bands[1:]):
        m = (p_test >= lo) & (p_test < hi)
        if m.sum() >= 30:
            calib.append({"band": f"{lo:.0%}-{min(hi, 1):.0%}", "predicted_pct": round(float(p_test[m].mean() * 100), 1),
                          "actual_scam_pct": round(float(y[m].mean() * 100), 1), "n": int(m.sum())})
    ece = float(sum(r["n"] / len(y) * abs(r["predicted_pct"] - r["actual_scam_pct"]) / 100 for r in calib))

    # ---- strength of each signal inside the model (mean absolute contribution, share of total)
    imp = np.abs(contrib).mean(axis=0)
    importance = sorted(({"signal": f, "side": cat.FEATURES[f].side, "share_pct": round(float(v / imp.sum() * 100), 1)}
                         for f, v in zip(F, imp)), key=lambda r: -r["share_pct"])

    report = {
        "data": {"transfers": len(df), "train": len(train), "calibration": len(cal), "test": len(test),
                 "scams_in_test": int(y.sum()), "scam_rate_pct": synth.FRAUD_RATE * 100,
                 "note": "Synthetic data. The scam rate is far higher than real life, so the percentages describe this mix."},
        "signals": {"total": len(F), **{s: len(cat.names_of(s)) for s in cat.SIDES}},
        "tiers": {k: round(v, 4) for k, v in tiers.items()},
        "friction_budget_pct_of_genuine": {k: v * 100 for k, v in FRICTION_BUDGET.items()},
        "headline": {**metrics(y, p_test, hold),
                     "genuine_disturbed_pct_at_hold": round(float((p_test[gen] >= hold).mean() * 100), 2),
                     "precision_at_hold": round(float(y[p_test >= hold].mean()), 3) if (p_test >= hold).any() else None,
                     "calibration_error": round(ece, 4)},
        "which_sides_are_needed": sides,
        "switch_a_whole_side_off": side_off,
        "switch_one_signal_off_worst5": ablation[:5],
        "switch_one_signal_off_all": ablation,
        "worst_single_signal_drop_in_caught_pct": round(max(r["caught_drop"] for r in ablation) * 100, 1),
        "score_spread": spread, "by_story": stories, "calibration": calib, "signal_strength": importance,
        "platt": {"a": a, "b": b},
    }
    ARTIFACTS.mkdir(exist_ok=True)
    model.booster_.save_model(str(ARTIFACTS / "model.txt"))
    (ARTIFACTS / "calibration.json").write_text(json.dumps({"a": a, "b": b}))
    (ARTIFACTS / "tiers.json").write_text(json.dumps(report["tiers"]))
    (ARTIFACTS / "report.json").write_text(json.dumps(report, indent=1))
    h = report["headline"]
    print(f"test: {len(test)} transfers, {int(y.sum())} scams")
    print(f"headline  PR-AUC {h['pr_auc']}  ROC-AUC {h['roc_auc']}  caught at hold tier {h['caught_at_hold_tier']:.1%}  "
          f"genuine disturbed {h['genuine_disturbed_pct_at_hold']}%  calibration error {h['calibration_error']}")
    for k, v in sides.items():
        print(f"  {k:40s} PR-AUC {v['pr_auc']}  caught {v['caught_at_hold_tier']:.1%}")
    print("whole side off:", side_off)
    print("worst single-signal drop in caught %:", report["worst_single_signal_drop_in_caught_pct"], ablation[:3])
    print("spread:", spread)
    for k, v in stories.items():
        print(f"  {k:20s} caught {v['caught_at_hold_tier_pct']:5.1f}%  median {v['median_risk_pct']:5.1f}%  push {v['push_share_pct']}")
    print("tiers:", report["tiers"])


if __name__ == "__main__":
    main()
