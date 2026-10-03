import generate_transfers as sim


def test_simulated_data_is_sane():
    d = sim.simulate(n_users=400, days=60, seed=7)
    t = d["transfers"]
    assert 0.010 < t["label"].mean() < 0.030                      # fraud is rare, as in real life
    assert set(t[t.label == 1]["script"]) == set(sim.SCRIPTS)    # all five scripts are present
    assert (t["sender"] != t["recipient"]).all()                  # nobody pays themselves
    assert (t["amount"] > 0).all()
    assert (t["balance_before"] >= t["amount"]).all()             # nobody sends money they do not have
    assert t["ts"].is_monotonic_increasing


def test_simulation_is_repeatable():
    a = sim.simulate(n_users=200, days=40, seed=3)["transfers"]
    b = sim.simulate(n_users=200, days=40, seed=3)["transfers"]
    assert a.equals(b)
