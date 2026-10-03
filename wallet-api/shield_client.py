"""How the wallet talks to Shield over HTTP.

Fail-open by design: if Shield is switched off, slow or down, the wallet keeps working and
lets the transfer through (the event is logged). Freezing every customer's money because an
AI helper is unavailable would do more harm than the fraud it might catch.

Shield is switched on by setting the environment variable SHIELD_API_URL, for example
    $env:SHIELD_API_URL = "http://localhost:8001"
"""
import logging
import os

import httpx

log = logging.getLogger("wallet.shield")


def _post(path: str, payload: dict) -> dict | None:
    """One HTTP call to Shield. Tests replace this function."""
    url = os.getenv("SHIELD_API_URL", "").strip().rstrip("/")
    if not url:
        return None
    timeout = float(os.getenv("SHIELD_TIMEOUT_SECONDS", "2.0"))
    response = httpx.post(url + path, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


SCORE_KEYS = {"action", "risk_pct", "tier"}
REFINE_KEYS = {"action_after", "risk_after_pct", "tier_after", "risk_before_pct"}


def _checked(result: dict | None, keys: set) -> dict | None:
    """A reply that is missing fields is treated as 'Shield unavailable', never trusted halfway."""
    if result is None:
        return None
    if not isinstance(result, dict) or not keys <= set(result):
        raise ValueError(f"unexpected reply from Shield: {str(result)[:120]}")
    return result


def assess(features: dict) -> dict | None:
    """Ask Shield to score a transfer. Returns None when Shield is unavailable for any reason."""
    try:
        return _checked(_post("/risk/score", features), SCORE_KEYS)
    except Exception as exc:   # network error, timeout, bad reply: never let it break a payment
        log.warning("Shield unavailable, allowing the transfer: %s", exc)
        return None


def refine(features: dict, answers: list[dict]) -> dict | None:
    """Ask Shield to re-score a transfer using the customer's safety-check answers (None if unavailable)."""
    try:
        return _checked(_post("/risk/refine", {"features": features, "answers": answers}), REFINE_KEYS)
    except Exception as exc:
        log.warning("Shield refine unavailable: %s", exc)
        return None
