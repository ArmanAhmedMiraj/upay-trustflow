"""Train, calibrate and evaluate the transfer-risk model.

Run from the repository root:
    python shield-api/transfer_risk/train.py

Steps
 1. generate synthetic data (or reuse data/raw)
 2. build point-in-time features
 3. split BY TIME (never randomly):  train -> calibration -> test
 4. train two baselines and the LightGBM model
 5. calibrate probabilities (isotonic) so "80%" really means about 80 in 100
 6. choose tier thresholds from the calibration set with a stated friction budget
 7. save portable artifacts and evaluate everything on the untouched test period
"""
from __future__ import annotations

import json
import pathlib
import sys

import lightgbm as lgb
import matplotlib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "simulator"))
sys.path.insert(0, str(HERE))

import generate_transfers as sim  # noqa: E402
import scorer  # noqa: E402
from features import FEATURES, build_features  # noqa: E402

SEED = 42
DAY = 1440
WARMUP_DAYS = 30
TRAIN_END, CAL_END = 75, 100          # train: day 30-75, calibration: 75-100, test: 100-120
FRICTION_BUDGET = {"note": 0.06, "high": 0.02, "very_high": 0.005}  # share of GENUINE transfers
MIN_PROBABILITY = {"note": 0.10, "high": 0.30, "very_high": 0.60}    # a tier must also mean a real chance of fraud
COST_PER_GENUINE_FRICTION_BDT = 15     # assumption: cost of interrupting one genuine transfer
HEED_RATES = [0.3, 0.5, 0.7]           # assumption: share of warned customers who stop the transfer
REPORT_DIR = ROOT / "reports" / "module1"
ARTIFACT_DIR = scorer.ARTIFACT_DIR

# +1: more of this signal can only raise risk. -1: more can only lower it. 0: free.
MONOTONE = {
    "amount_zscore": 1, "balance_share": 1, "is_first_time_recipient": 1, "is_round_amount": 1,
    "hour_unusual": 1, "hesitation_secs": 1, "amount_edits": 1, "on_call": 1,
    "recipient_age_days": -1, "first_time_senders_24h": 1, "recipient_outflow_ratio_24h": 1,
    "report_count": 1, "report_rate": 1, "claim_mismatch_on_recipient": 1,
}
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=40,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
              random_state=SEED, verbosity=-1, n_jobs=-1)

LOG_COLS = ["first_time_senders_24h", "recipient_inflow_count_24h", "recipient_prior_txns",
            "report_count", "sender_history_count", "hesitation_secs", "recipient_age_days"]


# ------------------------------------------------------------------ helpers
def fit_lgb(X, y, **extra):
    return lgb.LGBMClassifier(monotone_constraints=[MONOTONE.get(f, 0) for f in FEATURES],
                              **{**PARAMS, **extra}).fit(X[FEATURES], y)


def threshold_for_budget(genuine_scores: np.ndarray, budget: float) -> float:
    """Smallest threshold t such that at most `budget` of genuine transfers score >= t."""
    for t in np.unique(genuine_scores):
        if (genuine_scores >= t).mean() <= budget:
            return float(t)
    return float(genuine_scores.max() + 1e-6)


def recall_at_fpr(y, s, fpr):
    thr = threshold_for_budget(s[y == 0], fpr)
    return float((s[y == 1] >= thr).mean())


BIN_EDGES = [0, 0.02, 0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.0001]


def reliability_table(y, p):
    """Fixed probability bands: in each band, does the actual fraud rate match the predicted risk?"""
    y, p = np.asarray(y), np.asarray(p)
    rows = []
    for lo, hi in zip(BIN_EDGES[:-1], BIN_EDGES[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 20:
            rows.append({"band": f"{lo:.0%}-{min(hi, 1):.0%}", "predicted_mean": float(p[m].mean()),
                         "actual_fraud_rate": float(y[m].mean()), "n": int(m.sum())})
    return rows


def ece(y, p):
    """Expected calibration error over the fixed bands (weighted by how many transfers fall in each)."""
    t = reliability_table(y, p)
    n = sum(r["n"] for r in t)
    return float(sum(r["n"] / n * abs(r["predicted_mean"] - r["actual_fraud_rate"]) for r in t))


def rules_baseline_score(df: pd.DataFrame) -> np.ndarray:
    """What a simple rule engine would do: add one point for each suspicious-looking sign."""
    pts = (df["is_first_time_recipient"] + df["is_round_amount"] + (df["amount_zscore"] > 2)
           + (df["balance_share"] > 0.7) + df["on_call"] + (df["hour_unusual"] > 0.9)
           + (df["recipient_age_days"] < 7) + 3 * df["claim_mismatch_on_recipient"])
    return pts.to_numpy(dtype=float)


def lr_matrix(df):
    X = df[FEATURES].copy()
    for c in LOG_COLS:
        X[c] = np.log1p(X[c])
    return X


def summarise(y, s):
    return {"pr_auc": float(average_precision_score(y, s)), "roc_auc": float(roc_auc_score(y, s)),
            "recall_at_2pct_friction": recall_at_fpr(y, s, 0.02),
            "recall_at_1pct_friction": recall_at_fpr(y, s, 0.01)}


def summary_markdown(m: dict) -> str:
    pct = lambda v: f"{100 * v:.1f}%"  # noqa: E731
    r, c, op = m["ranking"], m["calibration"], m["operating_points"]
    L = ["# Module 1 results: Coached-Transfer Interrupter", "",
         "All numbers come from a synthetic test period that the model never saw during training or calibration.",
         "They show that the method works in our simulated world; they are not claims about real upay data.", "",
         f"Test period: {m['data']['test_rows']:,} transfers, {m['data']['test_fraud']:,} fraudulent "
         f"({pct(m['data']['test_fraud_rate'])}).", "",
         "## Does AI beat simple rules?", "", "| System | PR-AUC | ROC-AUC | Fraud caught at 2% friction |", "|---|---|---|---|"]
    names = {"rules_only_baseline": "Rules only", "logistic_regression_baseline": "Logistic regression",
             "lightgbm_raw": "LightGBM", "full_system_with_rules": "Full system (LightGBM + calibration + rule)"}
    for k, n in names.items():
        L.append(f"| {n} | {r[k]['pr_auc']:.3f} | {r[k]['roc_auc']:.3f} | {pct(r[k]['recall_at_2pct_friction'])} |")
    L += ["", "LightGBM and logistic regression perform almost the same here. The simulated signals mostly add up, so a "
          "linear model captures most of the value. The big gain over rules comes from combining signals; the "
          "advantage of tree models should grow when real data contains more interactions.", "",
          "## Is the risk % trustworthy? (calibration)", "",
          f"Expected calibration error: {c['ece_raw']:.4f} before calibration, {c['ece_calibrated']:.4f} after.", "",
          "| Predicted risk band | Mean predicted | Actual fraud rate | Transfers |", "|---|---|---|---|"]
    for b in c["reliability_calibrated"]:
        L.append(f"| {b['band']} | {pct(b['predicted_mean'])} | {pct(b['actual_fraud_rate'])} | {b['n']:,} |")
    t = m["tiers"]["thresholds"]
    L += ["", "## What customers experience (tiers)", "",
          f"Thresholds: note at {pct(t['note'])}, safety check at {pct(t['high'])}, 30-minute hold at {pct(t['very_high'])}.", "",
          "| Tier | Genuine transfers disturbed | Fraud caught (count) | Fraud caught (BDT) | Precision |", "|---|---|---|---|---|"]
    for k, n in (("note", "Note or above"), ("high", "Safety check or above"), ("very_high", "Hold")):
        o = op[k]
        L.append(f"| {n} | {pct(o['genuine_friction_rate'])} | {pct(o['fraud_recall_count'])} | "
                 f"{pct(o['fraud_recall_value'])} | {pct(o['precision'])} |")
    L += ["", "## Fraud caught per scam type (safety check or above)", "", "| Scam type | Caught |", "|---|---|"]
    for k, v in m["recall_by_scam_type_at_high_tier"].items():
        L.append(f"| {k} | {pct(v)} |")
    L += ["", f"Scam-type classifier accuracy on fraud transfers: {pct(m['scam_type_accuracy'])}.", "",
          "## Business impact (assumed heeding rates)", "",
          "We do not know how many customers will stop after a warning, so we show several rates. "
          "Friction cost is assumed to be 15 BDT per interrupted genuine transfer.", "",
          "| Customers who heed a warning | Fraud BDT stopped | Genuine transfers interrupted | Net benefit (BDT) |", "|---|---|---|---|"]
    for h, v in m["impact_by_heeding_rate"].items():
        L.append(f"| {float(h):.0%} | {v['fraud_bdt_stopped']:,.0f} of {v['fraud_bdt_attempted']:,.0f} | "
                 f"{v['genuine_transfers_interrupted']} | {v['net_benefit_bdt']:,.0f} |")
    L += ["", "## Network learning", "", "Average risk shown for fraud transfers, by how many reports the recipient had already:", ""]
    for k, v in m["network_learning_mean_risk_by_prior_reports"].items():
        L.append(f"- {k}: {pct(v)}")
    L += ["", "## Fairness (does the system treat groups differently?)", "",
          "| Group | Genuine disturbed | Fraud caught | Genuine n | Fraud n |", "|---|---|---|---|---|"]
    for k, v in m["fairness"].items():
        L.append(f"| {k} | {pct(v['genuine_friction_rate'])} | {pct(v['fraud_recall'])} | {v['n_genuine']:,} | {v['n_fraud']:,} |")
    L += ["", "## Robustness: what if fraudsters adapt? (fraud caught at safety check or above)", ""]
    for k, v in m["evasion_fraud_recall_at_high_tier"].items():
        L.append(f"- {k}: {pct(v)}")
    L += ["", "Using an old, quiet mule account removes most of the recipient-side evidence. That is a real weakness, "
          "and the reason Shield should be combined with account-level controls.", "",
          "## Generalisation to a scam type the model never saw (fraud caught at 2% friction)", "",
          "| Held-out scam type | When unseen | When trained on all |", "|---|---|---|"]
    for k, v in m["leave_one_scam_type_out"].items():
        L.append(f"| {k} | {pct(v['recall_unseen_script_at_2pct_friction'])} | {pct(v['recall_when_trained_on_all'])} |")
    L += ["", f"## Speed", "", f"Average scoring time: {m['latency_ms_per_transfer']} ms per transfer (single CPU core).", ""]
    return "\n".join(L)


# --------------------------------------------------------------------- main
def main(users: int = 6000, days: int = 120, leave_one_out: bool = True) -> dict:
    print("1/7 generating synthetic data ...")
    data = sim.simulate(users, days, SEED)
    df = build_features(data)
    df["day"] = df["ts"] / DAY
    df = df[df["day"] >= WARMUP_DAYS].reset_index(drop=True)
    tr = df[df["day"] < TRAIN_END]
    ca = df[(df["day"] >= TRAIN_END) & (df["day"] < CAL_END)]
    te = df[df["day"] >= CAL_END].reset_index(drop=True)
    print(f"   rows: train {len(tr):,}  calibration {len(ca):,}  test {len(te):,}")
    print(f"   fraud: train {int(tr.label.sum()):,}  calibration {int(ca.label.sum()):,}  test {int(te.label.sum()):,}")

    print("2/7 training baselines ...")
    scaler = StandardScaler().fit(lr_matrix(tr))
    lr = LogisticRegression(max_iter=2000).fit(scaler.transform(lr_matrix(tr)), tr.label)
    lr_test = lr.predict_proba(scaler.transform(lr_matrix(te)))[:, 1]
    rules_test = rules_baseline_score(te)

    print("3/7 training LightGBM ...")
    clf = fit_lgb(tr, tr.label)
    raw_ca = clf.predict_proba(ca[FEATURES])[:, 1]
    raw_te = clf.predict_proba(te[FEATURES])[:, 1]

    print("4/7 calibrating ...")
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_ca, ca.label)
    cal_te = iso.predict(raw_te)
    cal_ca = iso.predict(raw_ca)

    print("5/7 choosing tier thresholds on the calibration period ...")
    gen_ca = cal_ca[ca.label.to_numpy() == 0]
    tiers = {k: max(threshold_for_budget(gen_ca, b), MIN_PROBABILITY[k]) for k, b in FRICTION_BUDGET.items()}
    tiers["high"] = max(tiers["high"], tiers["note"] + 1e-6)
    tiers["very_high"] = max(tiers["very_high"], tiers["high"] + 1e-6)

    print("6/7 saving artifacts ...")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    clf.booster_.save_model(str(ARTIFACT_DIR / "model.txt"))
    (ARTIFACT_DIR / "calibrator.json").write_text(json.dumps(
        {"x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_]}))
    (ARTIFACT_DIR / "tiers.json").write_text(json.dumps(tiers, indent=2))
    fr_tr = tr[tr.label == 1]
    classes = sorted(fr_tr.script.unique())
    scam = lgb.LGBMClassifier(objective="multiclass", n_estimators=150, learning_rate=0.08, num_leaves=15,
                              min_child_samples=20, random_state=SEED, verbosity=-1).fit(
        fr_tr[FEATURES], fr_tr.script.map({c: i for i, c in enumerate(classes)}))
    scam.booster_.save_model(str(ARTIFACT_DIR / "scam_type.txt"))
    (ARTIFACT_DIR / "scam_type_classes.json").write_text(json.dumps(classes))
    (ARTIFACT_DIR / "model_card.json").write_text(json.dumps({
        "version": "v1", "features": FEATURES, "seed": SEED,
        "train_days": [WARMUP_DAYS, TRAIN_END], "calibration_days": [TRAIN_END, CAL_END],
        "test_days": [CAL_END, days], "friction_budget": FRICTION_BUDGET,
        "data": "fully synthetic; see docs/synthetic-assumptions.md"}, indent=2))

    print("7/7 evaluating on the untouched test period ...")
    art = scorer.load_artifacts()
    sc = scorer.score_frame(art, te)
    y = te.label.to_numpy()
    amt = te.amount.to_numpy()
    tier = sc["tier"].to_numpy()
    risk = sc["risk"].to_numpy()

    metrics: dict = {"data": {"users": users, "days": days, "test_rows": int(len(te)), "test_fraud": int(y.sum()),
                               "test_fraud_rate": float(y.mean())}}
    metrics["ranking"] = {
        "rules_only_baseline": summarise(y, rules_test),
        "logistic_regression_baseline": summarise(y, lr_test),
        "lightgbm_raw": summarise(y, raw_te),
        "full_system_with_rules": summarise(y, risk),
    }
    metrics["calibration"] = {
        "brier_raw": float(brier_score_loss(y, raw_te)),
        "brier_calibrated": float(brier_score_loss(y, cal_te)),
        "ece_raw": ece(y, raw_te), "ece_calibrated": ece(y, cal_te),
        "reliability_calibrated": reliability_table(y, cal_te),
    }
    metrics["tiers"] = {"thresholds": tiers, "friction_budget_on_genuine": FRICTION_BUDGET,
                        "minimum_probability": MIN_PROBABILITY}

    # ---- operational results at the chosen thresholds
    g = y == 0
    f = y == 1
    op = {}
    for name in ["note", "high", "very_high"]:
        hit = np.isin(tier, {"note": ["note", "high", "very_high"], "high": ["high", "very_high"], "very_high": ["very_high"]}[name])
        op[name] = {
            "genuine_friction_rate": float(hit[g].mean()),
            "fraud_recall_count": float(hit[f].mean()),
            "fraud_recall_value": float(amt[f & hit].sum() / amt[f].sum()),
            "precision": float(y[hit].mean()) if hit.any() else None,
            "genuine_bdt_affected": float(amt[g & hit].sum()),
        }
    metrics["operating_points"] = op
    friction = np.isin(tier, ["high", "very_high"])
    metrics["recall_by_scam_type_at_high_tier"] = {
        s: float(friction[(te.script == s).to_numpy()].mean()) for s in sorted(te[te.label == 1].script.unique())}
    fraud_value_warned = amt[f & friction].sum()
    fraud_value_total = amt[f].sum()
    n_g_fric = int((g & friction).sum())
    metrics["impact_by_heeding_rate"] = {
        str(h): {
            "fraud_bdt_attempted": float(fraud_value_total),
            "fraud_bdt_stopped": float(h * fraud_value_warned),
            "genuine_transfers_interrupted": n_g_fric,
            "assumed_friction_cost_bdt": float(n_g_fric * COST_PER_GENUINE_FRICTION_BDT),
            "net_benefit_bdt": float(h * fraud_value_warned - n_g_fric * COST_PER_GENUINE_FRICTION_BDT),
        } for h in HEED_RATES}

    # ---- scam-type classifier accuracy (on fraud rows of the test period)
    fr_te = te[te.label == 1]
    probs = art.scam_booster.predict(fr_te[FEATURES])
    pred = np.array(art.scam_classes)[probs.argmax(1)]
    metrics["scam_type_accuracy"] = float((pred == fr_te.script.to_numpy()).mean())

    # ---- fairness: do error rates differ between groups?
    groups = {
        "newer_sender_(<35_transfers)": te.sender_history_count < 35,
        "established_sender_(35+)": te.sender_history_count >= 35,
        "low_balance_(below_median)": te.balance_before < te.balance_before.median(),
        "high_balance_(above_median)": te.balance_before >= te.balance_before.median(),
        "night_(22:00-05:00)": ((te.ts % DAY) / 60 >= 22) | ((te.ts % DAY) / 60 < 5),
        "daytime": ((te.ts % DAY) / 60 >= 5) & ((te.ts % DAY) / 60 < 22),
    }
    fair = {}
    for name, m in groups.items():
        m = m.to_numpy()
        gm, fm = m & g, m & f
        fair[name] = {"genuine_friction_rate": float(friction[gm].mean()) if gm.any() else None,
                      "fraud_recall": float(friction[fm].mean()) if fm.any() else None,
                      "n_genuine": int(gm.sum()), "n_fraud": int(fm.sum())}
    metrics["fairness"] = fair

    # ---- evasion: what if the fraudster changes tactics?
    base = te[te.label == 1].copy()
    med = te[te.label == 0]

    def evade(kind: str) -> pd.DataFrame:
        d = base.copy()
        if kind in ("split_amount", "combined"):        # send smaller amounts, not round
            d["amount_zscore"] = np.minimum(d["amount_zscore"], 0.5)
            d["balance_share"] = d["balance_share"] / 3
            d["is_round_amount"] = 0
        if kind in ("normal_hour", "combined"):         # only act at the customer's usual hours
            d["hour_unusual"] = med["hour_unusual"].median()
        if kind in ("aged_wallet", "combined"):         # collect on an old, quiet, unreported account
            d["recipient_age_days"] = 365.0
            d["first_time_senders_24h"] = 0
            d["recipient_inflow_count_24h"] = 0
            d["recipient_outflow_ratio_24h"] = 0.0
            d["recipient_prior_txns"] = 40
            d["report_count"] = 0
            d["report_rate"] = 0.0
        if kind in ("no_sms_story", "combined"):        # skip the fake "money received" SMS
            for c in ["sms_claims_credit", "sms_mentions_recipient", "ledger_confirms_credit", "claim_ledger_mismatch",
                      "claim_mismatch_on_recipient", "sms_official_sender"]:
                d[c] = 0
        return d
    ev = {}
    for kind in ["none", "split_amount", "normal_hour", "aged_wallet", "no_sms_story", "combined"]:
        s2 = scorer.score_frame(art, evade(kind) if kind != "none" else base)
        ev[kind] = float(s2["tier"].isin(["high", "very_high"]).mean())
    metrics["evasion_fraud_recall_at_high_tier"] = ev

    # ---- network learning: same fraud wallets, risk before vs after reports
    fr_sc = sc[te.label.to_numpy() == 1].copy()
    fr_sc["reports"] = fr_te["report_count"].to_numpy()
    bins = {"0 reports": fr_sc.reports == 0, "1-2 reports": fr_sc.reports.between(1, 2), "3+ reports": fr_sc.reports >= 3}
    metrics["network_learning_mean_risk_by_prior_reports"] = {k: float(fr_sc[m].risk.mean()) for k, m in bins.items() if m.any()}

    # ---- latency
    import time
    row = te.iloc[[0]]
    t0 = time.perf_counter()
    for i in range(200):
        scorer.score_transfer({f_: float(te.iloc[i][f_]) for f_ in FEATURES}, art)
    metrics["latency_ms_per_transfer"] = round((time.perf_counter() - t0) / 200 * 1000, 1)

    # ---- leave-one-scam-type-out: does it generalise to a script it never saw?
    if leave_one_out:
        loo = {}
        for s in classes:
            keep = ~((tr.label == 1) & (tr.script == s))
            c2 = fit_lgb(tr[keep], tr[keep].label)
            s2 = c2.predict_proba(te[FEATURES])[:, 1]
            thr = threshold_for_budget(s2[g], 0.02)
            loo[s] = {"recall_unseen_script_at_2pct_friction": float((s2[(te.script == s).to_numpy()] >= thr).mean()),
                      "recall_when_trained_on_all": float((raw_te[(te.script == s).to_numpy()] >= threshold_for_budget(raw_te[g], 0.02)).mean())}
        metrics["leave_one_scam_type_out"] = loo

    # ---- plots
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5, 5))
    for name, p in [("raw LightGBM", raw_te), ("calibrated", cal_te)]:
        t = reliability_table(y, p)
        ax.plot([r["predicted_mean"] for r in t], [r["actual_fraud_rate"] for r in t], "o-", label=name)
    ax.plot([0, 1], [0, 1], "k--", label="perfect")
    ax.set_xlabel("predicted risk"); ax.set_ylabel("actual fraud rate"); ax.set_title("Reliability (test period)")
    ax.legend(); fig.tight_layout(); fig.savefig(REPORT_DIR / "calibration.png", dpi=140); plt.close(fig)

    from sklearn.metrics import precision_recall_curve
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for name, s_ in [("rules only", rules_test), ("logistic regression", lr_test), ("full system", risk)]:
        p_, r_, _ = precision_recall_curve(y, s_)
        ax.plot(r_, p_, label=f"{name} (PR-AUC {average_precision_score(y, s_):.2f})")
    ax.set_xlabel("recall (share of fraud caught)"); ax.set_ylabel("precision"); ax.legend()
    ax.set_title("Precision-recall (test period)"); fig.tight_layout(); fig.savefig(REPORT_DIR / "pr_curve.png", dpi=140); plt.close(fig)

    ths = np.unique(np.quantile(risk[g], np.linspace(0.85, 0.9998, 120)))
    xs = [(risk[g] >= t_).mean() * 100 for t_ in ths]
    ys = [amt[f & (risk >= t_)].sum() / fraud_value_total * 100 for t_ in ths]
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.plot(xs, ys); ax.set_xlim(0, 15); ax.axvline(2, color="grey", ls="--", label="2% friction budget")
    ax.set_xlabel("% of genuine transfers disturbed"); ax.set_ylabel("% of fraud BDT warned")
    ax.set_title("Friction vs fraud value caught (test period)"); ax.legend()
    fig.tight_layout(); fig.savefig(REPORT_DIR / "tradeoff.png", dpi=140); plt.close(fig)

    (REPORT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (REPORT_DIR / "summary.md").write_text(summary_markdown(metrics))
    return metrics


if __name__ == "__main__":
    m = main()
    print(json.dumps({k: m[k] for k in ["ranking", "operating_points", "scam_type_accuracy"]}, indent=2))
