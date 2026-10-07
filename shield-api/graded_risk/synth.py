"""Synthetic transfers for the graded-risk model (no real customer data exists for this prototype).

Every transfer is one of several STORIES. Genuine stories include the hard ones (a busy shop, a brand-new but
honest wallet, a real family emergency). Scam stories include some where the sender looks calm and the recipient
gives the scam away, and some where the recipient looks clean and only the sender gives it away.

A scam signal is present only with some probability, so scams overlap with genuine transfers and the model has
to weigh many signals together. A model that leans on one signal will fail on the stories that lack it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from graded_risk.catalogue import FEATURE_NAMES

GENUINE_SHARE = {"routine": .75, "new_honest_wallet": .08, "busy_merchant": .06, "real_emergency": .03,
                 "basic_kyc_student": .04, "big_first_payment": .04}
FRAUD_SHARE = {"officer_call": .24, "refund_by_mistake": .20, "relative_emergency": .12, "prize_or_fee": .15,
               "quiet_old_mule": .13, "clean_recipient": .09, "faint_signals": .07}
FRAUD_RATE = 0.05   # share of scam transfers in the synthetic data (real life is far lower; probabilities are for THIS mix)


def _ln(rng, mean, sd, n, lo=0.0, hi=1e9):
    return np.clip(np.exp(rng.normal(np.log(mean), sd, n)), lo, hi)


def _base(rng, n) -> dict:
    """An ordinary transfer: every signal drawn from what harmless transfers look like."""
    d = {
        "s_amount_zscore": np.clip(rng.normal(0, 1, n), -3, 6),
        "s_balance_share": rng.beta(2, 10, n),
        "s_hour_unusual": rng.beta(3, 4, n),
        "s_log_mins_since_credit": np.clip(rng.normal(7.6, 1.5, n), 0, 9.3),
        "s_hesitation_secs": _ln(rng, 6, .5, n, 1, 300),
        "s_amount_edits": rng.poisson(.2, n).astype(float),
        "s_on_call": (rng.random(n) < .05).astype(float),
        "s_history_count": np.round(_ln(rng, 40, .9, n, 0, 3000)),
        "s_new_device": (rng.random(n) < .03).astype(float),
        "s_round_amount": (rng.random(n) < .2).astype(float),
        "r_age_days": _ln(rng, 400, .8, n, 1, 2000),
        "r_sim_age_days": _ln(rng, 900, .8, n, 1, 4000),
        "r_kyc_level": rng.choice([0., 1., 2.], n, p=[.05, .25, .70]),
        "r_wallets_per_nid": rng.choice([1., 2., 3.], n, p=[.93, .06, .01]),
        "r_shared_device_wallets": rng.choice([0., 1., 2.], n, p=[.90, .08, .02]),
        "r_first_time_senders_24h": rng.poisson(.4, n).astype(float),
        "r_inflow_count_24h": rng.poisson(1.5, n).astype(float),
        "r_outflow_ratio_24h": np.clip(rng.beta(1.5, 3, n), 0, 3),
        "r_median_hold_mins": _ln(rng, 600, 1.0, n, 1, 10080),
        "r_cashout_agents_7d": rng.poisson(.6, n).astype(float),
        "r_dormant_days": np.where(rng.random(n) < .15, _ln(rng, 20, .6, n, 1, 400), 0.0),
        "r_report_count": rng.poisson(.05, n).astype(float),
        "r_prior_txns": np.round(_ln(rng, 60, 1.0, n, 0, 5000)),
        "r_sim_swap_recent": (rng.random(n) < .02).astype(float),
        "i_first_time_recipient": (rng.random(n) < .25).astype(float),
        "i_amount_vs_recipient_typical": rng.normal(0, .7, n),
        "i_same_amount_inflows_24h": rng.poisson(.2, n).astype(float),
        "i_geo_mismatch": (rng.random(n) < .25).astype(float),
        "i_sms_claim_mismatch": (rng.random(n) < .01).astype(float),
    }
    return d


def _apply(d: dict, rng, n, over: dict) -> set:
    """Replace a signal with its story value in a share `p` of the rows. Returns the names that were set."""
    for name, (p, fn) in over.items():
        mask = rng.random(n) < p
        d[name] = np.where(mask, fn(rng, n), d[name])
    return set(over)


def _pois(lam, add=0):
    return lambda rng, n: rng.poisson(lam, n) + add


def _lnf(mean, sd, lo=0.0, hi=1e9, rnd=False):
    def f(rng, n):
        v = _ln(rng, mean, sd, n, lo, hi)
        return np.round(v) if rnd else v
    return f


def _const(v):
    return lambda rng, n: np.full(n, float(v))


def _beta(a, b):
    return lambda rng, n: rng.beta(a, b, n)


def _norm(m, s, lo=-3, hi=8):
    return lambda rng, n: np.clip(rng.normal(m, s, n), lo, hi)


def _choice(vals, probs):
    return lambda rng, n: rng.choice(vals, n, p=probs).astype(float)


def _mule(p: float) -> dict:
    """The look of a collector account. Each trait is present with probability ~p, so no single trait is guaranteed."""
    return {
        "r_age_days": (p, _lnf(22, .95, 1, 400)), "r_sim_age_days": (p, _lnf(70, 1.0, 1, 900)),
        "r_kyc_level": (p, _choice([0, 1, 2], [.45, .40, .15])),
        "r_wallets_per_nid": (p * .8, _choice([2, 3, 4, 5], [.4, .3, .2, .1])),
        "r_shared_device_wallets": (p * .7, _choice([1, 2, 3], [.5, .3, .2])),
        "r_first_time_senders_24h": (p, _pois(5)), "r_inflow_count_24h": (p, _pois(7)),
        "r_outflow_ratio_24h": (p, lambda rng, n: np.clip(rng.beta(4, 2.2, n), 0, 3)),
        "r_median_hold_mins": (p, _lnf(45, 1.0, 1, 900)), "r_cashout_agents_7d": (p * .8, _pois(3, 1)),
        "r_report_count": (p * .6, _pois(1.3, 1)), "r_prior_txns": (p, _lnf(20, .9, 0, 300, True)),
        "r_sim_swap_recent": (p * .2, _const(1)), "r_dormant_days": (p * .1, _lnf(30, .5, 5, 300)),
        "i_same_amount_inflows_24h": (p * .6, _pois(3, 1)), "i_geo_mismatch": (p * .8, _const(1)),
        "i_amount_vs_recipient_typical": (p, _norm(.8, .8, -1, 4)),
    }


def _scaled(over: dict, k: float) -> dict:
    """The same traits, each present less often (k < 1). Used to give genuine transfers a few scam-like traits."""
    return {name: (p * k, fn) for name, (p, fn) in over.items()}


def _coached_sender(on_call, zs=3.0, share=(6, 2), hes=25, edits=1.2, first=.8, newdev=.1, rnd=.6) -> dict:
    return {
        "s_on_call": (on_call, _const(1)), "s_amount_zscore": (.9, _norm(zs, 1)), "s_balance_share": (.9, _beta(*share)),
        "s_hesitation_secs": (.85, _lnf(hes, .4, 1, 300)), "s_amount_edits": (.8, _pois(edits)),
        "i_first_time_recipient": (first, _const(1)), "s_new_device": (newdev, _const(1)),
        "s_round_amount": (rnd, _const(1)), "s_hour_unusual": (.5, _beta(5, 3)),
        "s_history_count": (.25, _lnf(8, .6, 0, 40, True)),
    }


STORIES: dict[str, dict] = {
    # ---------------------------------------------------------------- genuine
    "routine": {},
    "new_honest_wallet": {"r_age_days": (1, _lnf(25, .8, 1, 120)), "r_prior_txns": (1, _lnf(6, .7, 0, 40, True)),
                          "r_sim_age_days": (.5, _lnf(300, .9, 5, 2000)), "i_first_time_recipient": (.6, _const(1)),
                          "r_kyc_level": (1, _choice([0, 1, 2], [.1, .3, .6]))},
    "busy_merchant": {"r_inflow_count_24h": (1, _pois(30)), "r_first_time_senders_24h": (1, _pois(10)),
                      "r_outflow_ratio_24h": (1, lambda rng, n: rng.beta(5, 3, n)), "r_prior_txns": (1, _lnf(800, .7, 100, 5000, True)),
                      "r_kyc_level": (.9, _const(2)), "r_report_count": (1, _pois(.5)), "r_cashout_agents_7d": (1, _pois(2)),
                      "r_median_hold_mins": (1, _lnf(120, .8, 5, 3000)), "i_first_time_recipient": (.6, _const(1)),
                      "i_same_amount_inflows_24h": (1, _pois(2)), "i_mutual_contacts": (1, _pois(.3))},
    "real_emergency": {"s_on_call": (.8, _const(1)), "s_amount_zscore": (1, _norm(2.5, 1)), "s_balance_share": (1, _beta(5, 3)),
                       "s_hour_unusual": (1, _beta(6, 2)), "s_hesitation_secs": (1, _lnf(18, .4, 1, 300)),
                       "s_amount_edits": (1, _pois(.8)), "i_first_time_recipient": (1, _const(0)), "i_mutual_contacts": (1, _pois(5))},
    "basic_kyc_student": {"r_kyc_level": (1, _choice([0, 1, 2], [.35, .50, .15])), "r_sim_age_days": (1, _lnf(120, .7, 5, 1500)),
                          "r_age_days": (1, _lnf(100, .8, 3, 800)), "r_prior_txns": (1, _lnf(15, .8, 0, 200, True)),
                          "s_history_count": (1, _lnf(10, .7, 0, 80, True))},
    "big_first_payment": {"i_first_time_recipient": (1, _const(1)), "s_round_amount": (.7, _const(1)), "s_amount_zscore": (1, _norm(2.2, .8)),
                          "s_balance_share": (1, _beta(4, 6)), "s_hesitation_secs": (1, _lnf(14, .4, 1, 200)),
                          "s_on_call": (.25, _const(1)), "i_amount_vs_recipient_typical": (1, _norm(1.2, .5, -1, 4))},
    # ---------------------------------------------------------------- scams
    "officer_call": {**_mule(.52), **_scaled(_coached_sender(.8), .85)},
    "refund_by_mistake": {**_mule(.48), **_coached_sender(.50, zs=1.5, share=(3, 6), hes=16, edits=.8, rnd=.8),
                          "i_sms_claim_mismatch": (.85, _const(1))},
    "relative_emergency": {**_mule(.44), **_coached_sender(.25, zs=1.6, share=(4, 5), hes=13, edits=.6, rnd=.5),
                           "i_mutual_contacts": (.9, _pois(.1)), "i_geo_mismatch": (.9, _const(1))},
    "prize_or_fee": {**_mule(.54), "r_report_count": (.7, _pois(2, 1)), "r_wallets_per_nid": (.8, _choice([2, 3, 4], [.5, .3, .2])),
                     **_coached_sender(.10, zs=1.0, share=(3, 8), hes=9, edits=.3, first=.75, newdev=.03, rnd=.7)},
    "quiet_old_mule": {**_scaled({"r_age_days": (1, _lnf(250, .6, 60, 1500)), "r_wallets_per_nid": (.7, _choice([2, 3, 4], [.5, .3, .2])),
                       "r_shared_device_wallets": (.6, _choice([1, 2], [.7, .3])), "r_sim_swap_recent": (.4, _const(1)),
                       "r_dormant_days": (.6, _lnf(60, .5, 15, 400)), "r_median_hold_mins": (.8, _lnf(25, .8, 1, 300)),
                       "r_outflow_ratio_24h": (.8, lambda rng, n: np.clip(rng.beta(6, 2, n), 0, 3)),
                       "r_cashout_agents_7d": (.7, _pois(3, 1)), "r_first_time_senders_24h": (.6, _pois(5)),
                       "r_inflow_count_24h": (.6, _pois(6)), "i_same_amount_inflows_24h": (.4, _pois(2, 1)),
                       "r_report_count": (.3, _pois(1, 1))}, .8),
                       **_coached_sender(.35, zs=1.8, share=(4, 6), hes=14, edits=.6, first=.9, newdev=.05, rnd=.5)},
    "clean_recipient": {**_mule(.18), **_coached_sender(.90, zs=3.0, share=(7, 2), hes=28, edits=1.5, newdev=.15)},
    "faint_signals": {**_mule(.14), "s_amount_zscore": (1, _norm(1.0, 1)), "i_first_time_recipient": (.6, _const(1)),
                      "s_round_amount": (.4, _const(1)), "s_balance_share": (.5, _beta(3, 7))},
}


def _story(rng, name: str, n: int) -> pd.DataFrame:
    d = _base(rng, n)
    over = dict(STORIES[name])
    if name in GENUINE_SHARE:   # honest people sometimes look odd too: a few scam-like traits at low rates
        over = {**_scaled(_mule(.55), .22), **_scaled(_coached_sender(.5, first=.5), .30), **over}
    mutual = over.pop("i_mutual_contacts", None)
    _apply(d, rng, n, over)
    first = d["i_first_time_recipient"] >= 1
    d["i_mutual_contacts"] = rng.poisson(np.where(first, .8, 3.0)).astype(float)
    if mutual is not None:
        _apply(d, rng, n, {"i_mutual_contacts": mutual})
    d["r_report_rate"] = d["r_report_count"] / (d["r_prior_txns"] + 5.0)
    df = pd.DataFrame(d)[FEATURE_NAMES]
    df["story"] = name
    return df


def generate(n: int = 200_000, seed: int = 7) -> pd.DataFrame:
    """`n` transfers: ~5% scams, the rest genuine, each from one of the stories above."""
    rng = np.random.default_rng(seed)
    n_fraud = int(round(n * FRAUD_RATE))
    parts = []
    for shares, total, label in ((FRAUD_SHARE, n_fraud, 1), (GENUINE_SHARE, n - n_fraud, 0)):
        for name, share in shares.items():
            k = int(round(total * share))
            part = _story(rng, name, k)
            part["label"] = label
            parts.append(part)
    return pd.concat(parts, ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)
