"""Hard rules, kept SEPARATE from the machine-learning model.

A rule covers a case that is certain enough that no learning is needed.
(We also tested a second rule, "recipient reported 3+ times". It was only 33% precise
because popular honest shops collect false reports over time, so we removed it and
gave the model a report RATE feature instead. See reports/module1/rule_experiments.md.)

 A rule
hit sets a MINIMUM risk. The model's own score is never changed by rules, and
the reasons shown to the analyst are labelled "rule" or "model" so that a fixed
rule is never confused with a learned prediction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RULES = [
    {
        "id": "story_mismatch",
        "floor": 0.90,
        "text": "An SMS says money was received from this number, but the upay ledger shows no such credit",
        "when": lambda r: r["claim_mismatch_on_recipient"] == 1 and r["is_first_time_recipient"] == 1,
    },
]


def rule_hits(row: dict) -> list[dict]:
    """Rules that fire for one transfer (row is a dict of feature values)."""
    return [{"id": r["id"], "floor": r["floor"], "text": r["text"]} for r in RULES if r["when"](row)]


def floor_frame(df: pd.DataFrame, min_floor: float = 0.0) -> np.ndarray:
    """Minimum risk demanded by rules for every row of a feature table (0 when no rule fires)."""
    floor = np.zeros(len(df))
    cols = df.to_dict("list")
    for i in range(len(df)):
        row = {k: v[i] for k, v in cols.items()}
        for h in rule_hits(row):
            floor[i] = max(floor[i], h["floor"], min_floor)
    return floor
