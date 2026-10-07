"""How the wallet talks to Shield over HTTP.

Fail-open by design: if Shield is switched off, slow or down, the wallet keeps working and
lets the transfer through (the event is logged). Freezing every customer's money because an
AI helper is unavailable would do more harm than the fraud it might catch.

Shield is switched on by setting the environment variable SHIELD_API_URL, for example
    $env:SHIELD_API_URL = "http://localhost:8001"
"""
import hashlib
import hmac
import json
import logging
import os
import time

import httpx

log = logging.getLogger("wallet.shield")


def _signed_headers(body: bytes) -> dict:
    """Content type, plus the signature Shield checks when SHIELD_API_SECRET is set."""
    headers = {"Content-Type": "application/json"}
    secret = os.getenv("SHIELD_API_SECRET", "").strip()
    if secret:   # prove to Shield that this call comes from the wallet and was not changed on the way
        stamp = str(int(time.time()))
        headers["X-Shield-Timestamp"] = stamp
        headers["X-Shield-Signature"] = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return headers


def _post(path: str, payload: dict) -> dict | None:
    """One HTTP call to Shield. Tests replace this function."""
    url = os.getenv("SHIELD_API_URL", "").strip().rstrip("/")
    if not url:
        return None
    timeout = float(os.getenv("SHIELD_TIMEOUT_SECONDS", "2.0"))
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = httpx.post(url + path, content=body, headers=_signed_headers(body), timeout=timeout)
    response.raise_for_status()
    return response.json()


def lab_call(method: str, path: str, payload: dict | None = None) -> dict:
    """A call from the analyst's Risk Lab to Shield. Unlike a payment check this has no safe fallback, so it raises.

    The lab is not on the payment path: if Shield is down the analyst sees a plain message and no money is affected.
    Tests replace this function.
    """
    url = os.getenv("SHIELD_API_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError("Shield is not switched on (SHIELD_API_URL is not set)")
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else b""
    response = httpx.request(method, url + path, content=body or None, headers=_signed_headers(body), timeout=10.0)
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
