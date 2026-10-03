"""The most important test in the project: features must never use the future."""
import numpy as np

import generate_transfers as sim
from features import FEATURES, build_features, truncate


def test_features_use_only_information_available_before_the_transfer():
    data = sim.simulate(n_users=300, days=50, seed=11)
    full = build_features(data).set_index("txn_id")
    rng = np.random.default_rng(0)
    late = full[full["ts"] > 15 * 1440]
    # test the rows where a leak would show: fraud, reported recipients, busy recipients, and random ones
    picks = np.concatenate([
        rng.choice(late[late["label"] == 1].index.to_numpy(), 25, replace=False),
        rng.choice(late[late["report_count"] > 0].index.to_numpy(), 15, replace=False),
        rng.choice(late[late["first_time_senders_24h"] > 0].index.to_numpy(), 15, replace=False),
        rng.choice(late[late["claim_ledger_mismatch"] == 1].index.to_numpy(), 5, replace=False),
        rng.choice(late.index.to_numpy(), 20, replace=False),
    ])
    for txn_id in picks:
        ts = full.loc[txn_id, "ts"]
        # rebuild the features using ONLY what existed at the moment of this transfer
        past = build_features(truncate(data, ts)).set_index("txn_id")
        a = full.loc[txn_id, FEATURES].astype(float).to_numpy()
        b = past.loc[txn_id, FEATURES].astype(float).to_numpy()
        assert np.allclose(a, b, atol=1e-9), f"future information leaked into transfer {txn_id}"
