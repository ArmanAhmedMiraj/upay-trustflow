"""Request authenticity for the Shield API: only the wallet may ask Shield for a score.

The wallet signs every call with a shared secret (HMAC-SHA256 over "<timestamp>.<request body>") and sends the signature
and the timestamp in two headers. Shield recomputes it. A call with no signature, a wrong signature, an altered body or
an old timestamp (a replayed call) is answered with 401, and Shield never scores it.

Switched on by setting SHIELD_API_SECRET on BOTH sides. When it is not set, nothing is checked, so the demo and the
local tests keep working exactly as before. /health and the documentation pages stay open.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import tenants

SIGNATURE_HEADER = "x-shield-signature"
TIMESTAMP_HEADER = "x-shield-timestamp"
MAX_AGE_SECONDS = 300
OPEN_PATHS = ("/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def is_valid(secret: str, timestamp: str | None, signature: str | None, body: bytes, now: float | None = None) -> bool:
    if not timestamp or not signature:
        return False
    try:
        age = abs((now if now is not None else time.time()) - int(timestamp))
    except ValueError:
        return False
    if age > MAX_AGE_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


class SignedRequests:
    """ASGI middleware: refuses unsigned or tampered calls when SHIELD_API_SECRET is set."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or path.endswith(OPEN_PATHS):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        multi = bool(tenants.load())
        secret, tenant_id = tenants.secret_for(headers.get(tenants.TENANT_HEADER))
        if not secret and not multi:                      # single-tenant mode with no secret: nothing is checked (demo, tests)
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})["tenant"] = tenant_id
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        if not secret or not is_valid(secret, headers.get(TIMESTAMP_HEADER), headers.get(SIGNATURE_HEADER), body):
            payload = json.dumps({"detail": "Request is not signed correctly"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
            await send({"type": "http.response.body", "body": payload})
            return
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)