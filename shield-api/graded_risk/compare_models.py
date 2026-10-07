"""Why LightGBM? Train several model families on the SAME synthetic data, split and friction budget, and compare.

Run from the repository root:
    python shield-api/graded_risk/compare_models.py        (about two minutes)

Every model sees the same 31 signals and the same train / calibration / test split as train.py. Each gets its own tier
thresholds at the same budget (0.3% of genuine transfers disturbed at the hold tier), so "caught" is a fair comparison.
Result is written to artifacts/model_comparison.json. The data is synthetic, so this compares methods, not real-world accuracy.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import train as T  # noqa: E402
from graded_risk import catalogue as cat  # noqa: E402
from graded_risk import synth  # noqa: E402


def main() -> None:
    df = synth.generate(200_000)
    train, rest = train_test_split(df, test_size=0.4, random_state=T.SEED, stratify=df["label"])
    cal, test = train_test_split(rest, test_size=0.5, random_state=T.SEED, stratify=rest["label"])
    F = cat.FEATURE_NAMES
    ycal, y = cal["label"].to_numpy(), test["label"].to_numpy()
    mono = [cat.FEATURES[f].direction for f in F]
    import lightgbm as lgb

    models = {
        "Logistic regression (scaled)": (make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
                                         "Linear: easy to read, but cannot learn that signals strengthen each other"),
        "Random forest": (RandomForestClassifier(n_estimators=200, max_depth=14, min_samples_leaf=50, n_jobs=-1, random_state=T.SEED),
                          "Trees, but no way to forbid a signal from pushing the wrong way"),
        "Neural network (small MLP)": (make_pipeline(StandardScaler(), MLPClassifier((64, 32), max_iter=60, early_stopping=True, random_state=T.SEED)),
                                       "Flexible, but a black box: no clean per-signal explanation"),
        "Gradient boosting (scikit-learn)": (HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_depth=5, random_state=T.SEED),
                                             "Same family as LightGBM, without monotone limits here"),
        "LightGBM, no direction limits": (lgb.LGBMClassifier(**T.PARAMS),
                                          "Boosted trees, free to push any signal either way"),
        "LightGBM + direction limits (ours)": (lgb.LGBMClassifier(monotone_constraints=mono, **T.PARAMS),
                                               "Boosted trees where each signal may only push its logical way; exact per-signal points (TreeSHAP)"),
    }
    out = {}
    for name, (m, note) in models.items():
        t0 = time.time()
        m.fit(train[F], train["label"])
        fit_s = time.time() - t0
        pc, pt = m.predict_proba(cal[F])[:, 1], m.predict_proba(test[F])[:, 1]
        thr = T.threshold_for_budget(pc[ycal == 0], T.FRICTION_BUDGET["very_high"])
        res = {**T.metrics(y, pt, thr), "fit_seconds": round(fit_s, 1), "note": note}
        res["distinct_scam_scores"] = int(len(np.unique(np.round(pt[y == 1] * 100, 0))))
        out[name] = res
        print(f"{name:38} PR-AUC {res['pr_auc']:.3f}  ROC-AUC {res['roc_auc']:.3f}  caught at hold {res['caught_at_hold_tier']:.1%}  fit {fit_s:.0f}s")
    (HERE / "artifacts" / "model_comparison.json").write_text(json.dumps(
        {"data": {"train": len(train), "test": len(test), "scams_in_test": int(y.sum()), "signals": len(F)}, "models": out}, indent=2))


if __name__ == "__main__":
    main()
