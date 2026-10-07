"""Tenants: more than one payment provider can use the same Shield service, each with its own secret and its own adapter.

A tenant is one provider (upay today; another mobile-money provider tomorrow). What a tenant gets:
 - its own signing secret, so provider A can never act as provider B (see request_auth.py)
 - its own adapter, which turns that provider's request format into Shield's signals (see adapters.py)

Shield keeps NO provider data between calls: every request carries the signals it needs and the answer is returned and
forgotten. So there is no shared table that could leak one provider's customers to another; isolation comes from the design.

Configuration (environment variable SHIELD_TENANTS, JSON), for example:
    {"upay": {"secret": "...", "adapter": "upay"}, "demo-mfs": {"secret": "...", "adapter": "demo-mfs"}}
When SHIELD_TENANTS is not set, Shield behaves exactly as before: one tenant, "upay", using SHIELD_API_SECRET.
"""
from __future__ import annotations

import json
import os

DEFAULT_TENANT = "upay"
TENANT_HEADER = "x-shield-tenant"


def load() -> dict[str, dict]:
    """tenant id -> {"secret": str, "adapter": str}. Empty dict means the single-tenant (legacy) mode."""
    raw = os.getenv("SHIELD_TENANTS", "").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return {str(k): {"secret": str(v.get("secret", "")), "adapter": str(v.get("adapter", "upay"))} for k, v in data.items()}


def secret_for(tenant: str | None) -> tuple[str | None, str]:
    """(secret, tenant id) for a request. Secret is None when the tenant is unknown (the call is refused)."""
    tenants = load()
    if not tenants:                                     # legacy mode: one provider, SHIELD_API_SECRET
        return os.getenv("SHIELD_API_SECRET", "").strip() or None, DEFAULT_TENANT
    tid = (tenant or DEFAULT_TENANT).strip()
    entry = tenants.get(tid)
    return (entry["secret"] or None) if entry else None, tid


def adapter_name(tenant: str) -> str:
    return load().get(tenant, {}).get("adapter", "upay")
