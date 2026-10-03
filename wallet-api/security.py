"""PIN hashing and session tokens (standard library only).

 - PINs: PBKDF2-HMAC-SHA256 with a random salt per user and a server-side secret ("pepper").
 - Session tokens: random, and only their SHA-256 hash is stored in the database.

Honest limit: a 5-digit PIN has only 100,000 possibilities, so hashing alone cannot stop someone
who steals the whole database. Online protection comes from the lockout after repeated wrong PINs.
A production system would keep the pepper in a hardware security module.
"""
import hashlib
import hmac
import os
import secrets

ITERATIONS = 200_000
PEPPER = os.getenv("PIN_PEPPER", "dev-only-pepper-change-me").encode()


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode() + PEPPER, salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode() + PEPPER, bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)   # constant-time comparison


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
