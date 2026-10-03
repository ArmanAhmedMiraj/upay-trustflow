"""The wallet web API (what the phone app talks to).

Run it from inside the wallet-api folder:
    python init_db.py                         (once, creates the tables)
    uvicorn wallet_api:app --port 8000

Then open http://localhost:8000/docs to try it in the browser.
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import wallet_service as svc
from database import get_db
from models import User

app = FastAPI(title="upay-trustflow Wallet API", version="1.0",
              description="A prototype wallet. All data is synthetic. Shield plugs in through risk_hook.")

# The phone app is served from another address while developing, so the browser needs permission to call us.
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(svc.WalletError)
async def wallet_error_handler(request: Request, exc: svc.WalletError):
    body = {"code": exc.code, "detail": exc.message}
    if isinstance(exc, svc.RiskInterruption):
        body["risk"] = exc.decision.as_dict()
    return JSONResponse(status_code=exc.status, content=body)


# ------------------------------------------------------------------ request shapes
class RegisterIn(BaseModel):
    phone: str
    name: str
    pin: str


class LoginIn(BaseModel):
    phone: str
    pin: str


class AddMoneyIn(BaseModel):
    amount: int


class Behavior(BaseModel):
    """How the customer behaved on the confirm screen (used by Shield, never stored here)."""
    hesitation_secs: float = Field(default=0, ge=0, le=3600)
    amount_edits: int = Field(default=0, ge=0, le=50)
    on_call: bool = False


class SendIn(BaseModel):
    recipient_phone: str
    amount: int
    pin: str
    idempotency_key: str | None = Field(default=None, max_length=64)
    behavior: Behavior | None = None
    acknowledged_risk: bool = Field(default=False, description="True when the customer has read the warning and chooses to continue")


class PreviewIn(BaseModel):
    recipient_phone: str
    amount: int
    behavior: Behavior | None = None


class ReportIn(BaseModel):
    phone: str
    reason: str | None = Field(default=None, max_length=200)


class FakeSmsIn(BaseModel):
    amount: int
    from_number: str


class CashOutIn(BaseModel):
    agent_phone: str
    amount: int
    pin: str
    idempotency_key: str | None = Field(default=None, max_length=64)


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    return svc.authenticate(db, token)


def txn_out(t) -> dict:
    return {"id": t.id, "kind": t.kind, "amount": t.amount, "status": t.status,
            "created_at": t.created_at.isoformat(), "risk_pct": t.risk_pct, "risk_tier": t.risk_tier}


# ------------------------------------------------------------------ routes
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    return {"user": svc.user_public(svc.register(db, body.phone, body.name, body.pin))}


@app.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    token, user = svc.login(db, body.phone, body.pin)
    return {"token": token, "expires_in_hours": svc.SESSION_HOURS, "user": svc.user_public(user)}


@app.post("/auth/logout")
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if authorization and authorization.lower().startswith("bearer "):
        svc.logout(db, authorization[7:])
    return {"ok": True}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": svc.user_public(user)}


@app.post("/wallet/add-money")
def add_money(body: AddMoneyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    txn = svc.add_money(db, user, body.amount)
    return {"transaction": txn_out(txn), "balance": user.balance}


@app.post("/wallet/send")
def send(body: SendIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    behavior = body.behavior.model_dump() if body.behavior else None
    txn = svc.send_money(db, user, body.recipient_phone, body.amount, body.pin, body.idempotency_key, behavior,
                         body.acknowledged_risk)
    db.refresh(user)
    return {"transaction": txn_out(txn), "balance": user.balance}


@app.post("/wallet/send/preview")
def send_preview(body: PreviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Shield's opinion on a transfer before the PIN step. Moves no money."""
    behavior = body.behavior.model_dump() if body.behavior else None
    decision, recipient = svc.preview_send(db, user, body.recipient_phone, body.amount, behavior)
    return {"recipient": {"name": recipient.name, "phone": recipient.phone}, "risk": decision.as_dict()}


@app.post("/wallet/report")
def report(body: ReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    svc.report_number(db, user, body.phone, body.reason)
    return {"ok": True}


@app.get("/sms/inbox")
def sms_inbox(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"messages": svc.inbox(db, user)}


DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"


@app.post("/demo/fake-sms")
def demo_fake_sms(body: FakeSmsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """DEMO ONLY: drop a scammer-style fake 'money received' SMS into your own inbox (switch off with DEMO_MODE=0)."""
    if not DEMO_MODE:
        raise svc.WalletError("demo_disabled", "Demo tools are switched off", 404)
    svc.drop_fake_sms(db, user, body.amount, body.from_number)
    return {"ok": True}


@app.post("/wallet/cash-out")
def cash_out(body: CashOutIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    txn = svc.cash_out(db, user, body.agent_phone, body.amount, body.pin, body.idempotency_key)
    db.refresh(user)
    return {"transaction": txn_out(txn), "balance": user.balance}


@app.get("/wallet/transactions")
def transactions(limit: int = 20, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"transactions": svc.history(db, user, limit)}
