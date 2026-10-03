"""Guards on the saved evaluation results (written by train.py)."""
import json

import pytest

import scorer

METRICS = scorer.ARTIFACT_DIR.parents[2] / "reports" / "module1" / "metrics.json"
pytestmark = pytest.mark.skipif(not METRICS.exists(), reason="run train.py first")


@pytest.fixture(scope="module")
def m():
    return json.loads(METRICS.read_text())


def test_ai_clearly_beats_simple_rules(m):
    r = m["ranking"]
    assert r["lightgbm_raw"]["pr_auc"] > r["rules_only_baseline"]["pr_auc"] + 0.2


def test_risk_percentages_are_calibrated(m):
    assert m["calibration"]["ece_calibrated"] < 0.01
    assert m["calibration"]["ece_calibrated"] <= m["calibration"]["ece_raw"]


def test_genuine_customers_are_rarely_disturbed(m):
    assert m["operating_points"]["high"]["genuine_friction_rate"] < 0.02


def test_every_scam_type_is_caught_reasonably(m):
    assert min(m["recall_by_scam_type_at_high_tier"].values()) > 0.5
