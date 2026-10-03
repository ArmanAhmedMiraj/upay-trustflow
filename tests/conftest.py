"""Tell pytest where the project code lives, and keep every test independent of the developer's terminal."""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))          # so that "deploy.app" can be imported
for sub in ("wallet-api", "simulator", "shield-api", "shield-api/transfer_risk"):
    sys.path.insert(0, str(ROOT / sub))

# Settings a developer may have switched on in their own terminal (for running the real servers).
# Tests must never see them: a leftover SHIELD_API_URL would make every test wait for a real network call.
ENVIRONMENT_SETTINGS = ("SHIELD_API_URL", "SHIELD_TIMEOUT_SECONDS", "LLM_API_KEY", "LLM_MODEL", "HOLD_MINUTES", "DATABASE_URL")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ENVIRONMENT_SETTINGS:
        monkeypatch.delenv(name, raising=False)
