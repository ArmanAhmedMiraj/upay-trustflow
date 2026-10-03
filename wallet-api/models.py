"""Database tables of the wallet.

Money rules built into the design
 - Amounts are whole taka (integers). Decimals cause tiny rounding errors with money.
 - Every movement is a row in `transactions` (the ledger). A balance can always be re-checked
   by replaying the ledger, and the Shield story check reads the same ledger.
 - PINs are stored only as salted hashes. Session tokens are stored only as hashes.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class Report(Base):
    """A customer reporting a number as suspicious. One report per reporter per number (stops report-bombing)."""

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("reporter_id", "reported_id", name="uq_one_report_per_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reported_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SmsMessage(Base):
    """A message in a customer's inbox. Real upay credit messages are created by the wallet itself
    (so they are always true); demo mode can also drop in a FAKE 'money received' message."""

    __tablename__ = "sms_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sender_label: Mapped[str] = mapped_column(String(20))          # "upay" for official, otherwise a phone number
    text: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="credit_claim")
    claimed_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claimed_number: Mapped[str | None] = mapped_column(String(11), nullable=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RiskEvent(Base):
    """Every assessment Shield made, kept for the analyst console and the impact numbers."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    risk_pct: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(20))
    scam_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    source: Mapped[str] = mapped_column(String(10))                 # "preview" or "send"
    shield_available: Mapped[bool] = mapped_column(Boolean, default=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
