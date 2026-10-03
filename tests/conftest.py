"""Tell pytest where the project code lives (folder names with hyphens cannot be imported directly)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("wallet-api", "simulator", "shield-api", "shield-api/transfer_risk"):
    sys.path.insert(0, str(ROOT / sub))
