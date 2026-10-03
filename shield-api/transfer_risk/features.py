"""Feature builder for the Coached-Transfer Interrupter.

GOLDEN RULE: every feature for a transfer uses ONLY information that existed
strictly before that transfer. Using later information ("leakage") makes a
fraud model look brilliant in testing and fail in real life.
tests/test_features_leakage.py checks this rule automatically.

The same function builds features for training and (later) for live scoring,
so the model never sees different numbers in the demo than it learned from.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DAY = 1440
BIG = 1_000_000.0  # key spacing used for fast "events of wallet X before time T" lookups
LEDGER_WINDOW_MIN = 360  # a claimed credit must appear in the ledger within 6 hours

GROUP_A = [
    "amount_zscore", "balance_share", "is_first_time_recipient", "is_round_amount",
    "hour_unusual", "log_mins_since_incoming", "hesitation_secs", "amount_edits", "on_call",
    "sender_history_count",
]
GROUP_B = [
    "recipient_age_days", "first_time_senders_24h", "recipient_inflow_count_24h",
    "recipient_outflow_ratio_24h", "recipient_prior_txns", "report_count", "report_rate",
]
GROUP_C = [
    "sms_claims_credit", "sms_mentions_recipient", "ledger_confirms_credit",
    "claim_ledger_mismatch", "claim_mismatch_on_recipient", "sms_official_sender",
]
FEATURES = GROUP_A + GROUP_B + GROUP_C


def _window_count(keys: np.ndarray, rec: np.ndarray, ts: np.ndarray, window: float | None) -> np.ndarray:
    """How many events of wallet `rec` happened in [ts-window, ts)  (window=None: any time before ts)."""
    hi = np.searchsorted(keys, rec * BIG + ts, side="left")
    lo = np.searchsorted(keys, rec * BIG + (ts - window if window is not None else -BIG / 2), side="left")
    return hi - lo


def _window_sum(keys: np.ndarray, csum: np.ndarray, rec: np.ndarray, ts: np.ndarray, window: float) -> np.ndarray:
    hi = np.searchsorted(keys, rec * BIG + ts, side="left")
    lo = np.searchsorted(keys, rec * BIG + (ts - window), side="left")
    return csum[hi] - csum[lo]


def build_features(data: dict) -> pd.DataFrame:
    t = data["transfers"].sort_values("ts", kind="stable").reset_index(drop=True).copy()
    ts = t["ts"].to_numpy(dtype=float)
    sender = t["sender"].to_numpy()
    recip = t["recipient"].to_numpy()
    amount = t["amount"].to_numpy(dtype=float)
    out = pd.DataFrame({"txn_id": t["txn_id"].to_numpy()})

    # ------------------------------------------------ Group A: sender behaviour
    log_amt = np.log(amount)
    g = pd.DataFrame({"s": sender, "la": log_amt, "la2": log_amt ** 2})
    n_prior = g.groupby("s").cumcount().to_numpy()
    cs = g.groupby("s")["la"].cumsum().to_numpy() - log_amt
    css = g.groupby("s")["la2"].cumsum().to_numpy() - log_amt ** 2
    mu0, sd0, k0 = np.log(700.0), 0.7, 3.0  # shrink towards a typical sender while history is short
    mean = (cs + k0 * mu0) / (n_prior + k0)
    var = (css + k0 * (sd0 ** 2 + mu0 ** 2)) / (n_prior + k0) - mean ** 2
    out["amount_zscore"] = (log_amt - mean) / np.sqrt(np.maximum(var, 0.12))
    out["sender_history_count"] = n_prior
    out["balance_share"] = np.clip(amount / t["balance_before"].to_numpy(dtype=float), 0, 1)
    pair_seen = pd.DataFrame({"s": sender, "r": recip}).groupby(["s", "r"]).cumcount().to_numpy()
    out["is_first_time_recipient"] = (pair_seen == 0).astype(int)
    out["is_round_amount"] = ((amount % 500 == 0) & (amount >= 500)).astype(int)

    hour = (ts % DAY) / 60.0
    bucket = (hour // 3).astype(int)
    nb = pd.DataFrame({"s": sender, "b": bucket}).groupby(["s", "b"]).cumcount().to_numpy()
    out["hour_unusual"] = 1.0 - (nb + 1.0) / (n_prior + 8.0)

    # time since the sender last received money (transfers to them + salary credits)
    inflow_tr = pd.DataFrame({"receiver": recip, "payer": sender, "in_ts": ts, "amount": amount})
    sal = data["salary"].rename(columns={"ts": "in_ts"})[["receiver", "payer", "in_ts", "amount"]]
    inflows = pd.concat([inflow_tr, sal], ignore_index=True).sort_values("in_ts", kind="stable").reset_index(drop=True)
    left = pd.DataFrame({"ts": ts, "sender": sender, "_i": np.arange(len(t))}).sort_values("ts", kind="stable")
    m = pd.merge_asof(left, inflows[["in_ts", "receiver"]], left_on="ts", right_on="in_ts",
                      left_by="sender", right_by="receiver", allow_exact_matches=False)
    m = m.sort_values("_i")
    mins = np.where(m["in_ts"].isna(), 10080.0, np.minimum(ts - m["in_ts"].to_numpy(), 10080.0))
    out["log_mins_since_incoming"] = np.log1p(mins)
    out["hesitation_secs"] = t["hesitation_secs"].to_numpy(dtype=float)
    out["amount_edits"] = t["amount_edits"].to_numpy()
    out["on_call"] = t["on_call"].to_numpy()

    # ------------------------------------------------ Group B: recipient wallet
    wal = data["wallets"].set_index("wallet")["created_ts"]
    created = wal.reindex(recip).to_numpy()
    out["recipient_age_days"] = np.clip((ts - created) / DAY, 0, 400)

    # first payments from new senders to this recipient
    first_pair_ts = ts[pair_seen == 0]
    first_pair_rec = recip[pair_seen == 0]
    fk = np.sort(first_pair_rec * BIG + first_pair_ts)
    out["first_time_senders_24h"] = _window_count(fk, recip.astype(float), ts, DAY)

    ik = np.sort(recip * BIG + ts)
    out["recipient_inflow_count_24h"] = _window_count(ik, recip.astype(float), ts, DAY)
    out["recipient_prior_txns"] = np.minimum(_window_count(ik, recip.astype(float), ts, None), 5000)

    # how much of what arrived in the last 24h has already left (cash-out speed signal)
    order = np.argsort(recip * BIG + ts, kind="stable")
    ik_sorted = (recip * BIG + ts)[order]
    in_cs = np.concatenate([[0.0], np.cumsum(amount[order])])
    in_24 = _window_sum(ik_sorted, in_cs, recip.astype(float), ts, DAY)
    of = data["outflows"]
    ok = of["wallet"].to_numpy() * BIG + of["ts"].to_numpy()
    oo = np.argsort(ok, kind="stable")
    ok_sorted = ok[oo]
    out_cs = np.concatenate([[0.0], np.cumsum(of["amount"].to_numpy()[oo])])
    out_24 = _window_sum(ok_sorted, out_cs, recip.astype(float), ts, DAY)
    out["recipient_outflow_ratio_24h"] = np.where(in_24 > 0, np.minimum(out_24 / np.maximum(in_24, 1.0), 3.0), 0.0)

    rp = data["reports"]
    rk = np.sort(rp["wallet"].to_numpy() * BIG + rp["ts"].to_numpy())
    out["report_count"] = _window_count(rk, recip.astype(float), ts, None)
    # popular honest shops collect a few false reports over time, so reports are judged against volume
    out["report_rate"] = out["report_count"] / (out["recipient_prior_txns"] + 5.0)

    # ------------------------------------------------ Group C: story check (claim vs ledger)
    c_amt = t["claim_amount"].to_numpy(dtype=float)
    c_num = t["claim_number"].to_numpy()
    claims = ~np.isnan(c_amt)
    out["sms_claims_credit"] = claims.astype(int)
    out["sms_mentions_recipient"] = (claims & (c_num == recip)).astype(int)
    out["sms_official_sender"] = (claims & (t["claim_official"].to_numpy() == 1)).astype(int)

    confirms = np.zeros(len(t), dtype=int)
    if claims.any():
        lk = pd.DataFrame({
            "ts": ts[claims],
            "key": [f"{s}|{c}|{int(a)}" for s, c, a in zip(sender[claims], c_num[claims], c_amt[claims])],
            "_i": np.where(claims)[0],
        }).sort_values("ts", kind="stable")
        rk2 = inflows.assign(key=[f"{r}|{p}|{int(a)}" for r, p, a in
                                  zip(inflows["receiver"], inflows["payer"], inflows["amount"])])
        rk2 = rk2[rk2["key"].isin(set(lk["key"]))].sort_values("in_ts", kind="stable")
        mm = pd.merge_asof(lk, rk2[["in_ts", "key"]], left_on="ts", right_on="in_ts", by="key",
                           tolerance=LEDGER_WINDOW_MIN, allow_exact_matches=False)
        confirms[mm["_i"].to_numpy()] = (~mm["in_ts"].isna()).astype(int)
    out["ledger_confirms_credit"] = confirms
    out["claim_ledger_mismatch"] = (claims & (confirms == 0)).astype(int)
    out["claim_mismatch_on_recipient"] = (out["claim_ledger_mismatch"].to_numpy() == 1) & (out["sms_mentions_recipient"].to_numpy() == 1)
    out["claim_mismatch_on_recipient"] = out["claim_mismatch_on_recipient"].astype(int)

    # carry labels/metadata along for training and evaluation (never used as features)
    out["ts"] = ts
    out["amount"] = amount
    out["balance_before"] = t["balance_before"].to_numpy(dtype=float)
    out["label"] = t["label"].to_numpy()
    out["script"] = t["script"].to_numpy()
    out["sender"] = sender
    out["recipient"] = recip
    return out


def truncate(data: dict, upto_ts: float) -> dict:
    """The data as it looked at time `upto_ts` (used by the leakage test)."""
    return {
        "transfers": data["transfers"][data["transfers"]["ts"] <= upto_ts],
        "salary": data["salary"][data["salary"]["ts"] <= upto_ts],
        "outflows": data["outflows"][data["outflows"]["ts"] <= upto_ts],
        "reports": data["reports"][data["reports"]["ts"] <= upto_ts],
        "wallets": data["wallets"],
    }
