"""Database tables of the wallet.

Money rules built into the design
 - Amounts are whole taka (integers). Decimals cause tiny rounding errors with money.
 - Every movement is a row in `transactions` (the ledger). A balance can always be re-checked
   by replaying the ledger, and the Shield story check reads the same ledger.
 - PINs are stored only as salted hashes. Session tokens are stored only as hashes.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def utcnow() -> datetime:
    """Current UTC time without timezone info (SQLite stores naive datetimes, so we stay consistent)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """A wallet owner: customer, agent or distributor."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    pin_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="customer")
    balance: Mapped[int] = mapped_column(Integer, default=0)  # whole BDT
    failed_pin_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Transaction(Base):
    """The ledger: one row per money movement."""

    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("sender_id", "idempotency_key", name="uq_sender_idempotency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # add_money, send_money, cash_out
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    receiver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(Integer)  # whole BDT
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # filled in by Shield when it scores a transfer (empty until then)
    risk_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # lets a client safely retry a request (double tap, bad network) without moving money twice
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuthSession(Base):
    """A logged-in session. Only a hash of the token is stored, never the token itself."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
