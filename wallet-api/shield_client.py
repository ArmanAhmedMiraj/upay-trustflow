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


def assess(features: dict) -> dict | None:
    """Ask Shield to score a transfer. Returns None when Shield is unavailable for any reason."""
    try:
        return _post("/risk/score", features)
    except Exception as exc:   # network error, timeout, bad reply: never let it break a payment
        log.warning("Shield unavailable, allowing the transfer: %s", exc)
        return None
