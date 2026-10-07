"""The wallet web API (what the phone app talks to).

Run it from inside the wallet-api folder:
    python init_db.py                         (once, creates the tables)
    uvicorn wallet_api:app --port 8000

Then open http://localhost:8000/docs to try it in the browser.
"""
from __future__ import annotations

import os
import pathlib
import sys

from fastapi import Depends, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import impact as impact_metrics
import shield_client
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "shield-api" / "liquidity"))   # Module 2 (agent cash forecasting)
import wallet_service as svc
import database
from database import get_db
from models import RefillRequest, User, utcnow
from sqlalchemy import select

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


class AnswerIn(BaseModel):
    question_id: str
    answer: str = Field(description="yes, no or not_sure")


class SendIn(BaseModel):
    recipient_phone: str
    amount: int
    pin: str
    idempotency_key: str | None = Field(default=None, max_length=64)
    behavior: Behavior | None = None
    acknowledged_risk: bool = Field(default=False, description="True when the customer has read the warning and chooses to continue")
    safety_answers: list[AnswerIn] | None = Field(default=None, description="The customer's answers to Shield's safety-check questions")


class PreviewIn(BaseModel):
    recipient_phone: str
    amount: int
    behavior: Behavior | None = None
    safety_answers: list[AnswerIn] | None = None


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=200)


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
    user = svc.authenticate(db, token)
    if svc.settle_due_holds(db):          # any hold whose time is up is released as soon as anyone makes a request
        db.refresh(user)
    return user


def analyst_user(user: User = Depends(current_user)) -> User:
    svc.require_analyst(user)
    return user


def txn_out(t) -> dict:
    return {"id": t.id, "kind": t.kind, "amount": t.amount, "status": t.status,
            "created_at": t.created_at.isoformat(), "risk_pct": t.risk_pct, "risk_tier": t.risk_tier,
            "release_at": t.release_at.isoformat() if t.release_at and t.status == "held" else None}


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
    answers = [a.model_dump() for a in body.safety_answers] if body.safety_answers else None
    txn = svc.send_money(db, user, body.recipient_phone, body.amount, body.pin, body.idempotency_key, behavior,
                         body.acknowledged_risk, answers)
    db.refresh(user)
    return {"transaction": txn_out(txn), "balance": user.balance}


@app.post("/wallet/transactions/{txn_id}/cancel")
def cancel(txn_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Cancel a held transfer. The money returns to your balance immediately."""
    txn = svc.cancel_hold(db, user, txn_id)
    db.refresh(user)
    return {"transaction": txn_out(txn), "balance": user.balance}


@app.get("/analyst/cases")
def analyst_cases(status: str = "held", limit: int = 50, user: User = Depends(analyst_user), db: Session = Depends(get_db)):
    return {"cases": svc.analyst_cases(db, status, limit)}


@app.post("/analyst/cases/{txn_id}/approve")
def analyst_approve(txn_id: int, body: DecisionIn | None = None, user: User = Depends(analyst_user), db: Session = Depends(get_db)):
    return {"transaction": txn_out(svc.analyst_decide(db, user, txn_id, True, body.note if body else None))}


@app.post("/analyst/cases/{txn_id}/reject")
def analyst_reject(txn_id: int, body: DecisionIn | None = None, user: User = Depends(analyst_user), db: Session = Depends(get_db)):
    return {"transaction": txn_out(svc.analyst_decide(db, user, txn_id, False, body.note if body else None))}


@app.get("/analyst/impact")
def analyst_impact(hours: int = 168, user: User = Depends(analyst_user), db: Session = Depends(get_db)):
    """What Shield did for customers and for upay, measured from real activity in the wallet."""
    return impact_metrics.impact(db, hours)


@app.get("/analyst/model-report")
def analyst_model_report(user: User = Depends(analyst_user)):
    """Offline test results (synthetic data where the truth is known)."""
    return {"report": impact_metrics.model_report()}


# ------------------------------------------------------------------ Risk Lab (analysts): how the model reached a score
class LabIn(BaseModel):
    sender_id: str
    recipient_id: str
    tx: dict = Field(default_factory=dict)
    mute_sides: list[str] = Field(default_factory=list)
    mute_signals: list[str] = Field(default_factory=list)


def _lab(method: str, path: str, payload: dict | None = None) -> dict:
    try:
        return shield_client.lab_call(method, path, payload)
    except Exception as exc:   # Shield off, down or slow: say so plainly; no money is involved here
        raise svc.WalletError("shield_unavailable", f"The Risk Lab needs Shield, which is not reachable ({type(exc).__name__})", 503)


@app.get("/lab/accounts")
def lab_accounts(user: User = Depends(analyst_user)):
    return _lab("GET", "/risk/graded/accounts")


@app.get("/lab/catalogue")
def lab_catalogue(user: User = Depends(analyst_user)):
    return _lab("GET", "/risk/graded/catalogue")


@app.get("/lab/report")
def lab_report(user: User = Depends(analyst_user)):
    return _lab("GET", "/risk/graded/report")


@app.post("/lab/score")
def lab_score(body: LabIn, user: User = Depends(analyst_user)):
    return _lab("POST", "/risk/graded", body.model_dump())


# ------------------------------------------------------------------ Module 2: agent cash forecasting
def _world():
    import liq_service                      # loaded on first use; it needs the trained models in shield-api/liquidity/artifacts
    return liq_service.get_world()


def _day(day: int | None, scenario: str | None = None) -> int:
    import liq_service
    chosen = liq_service.SCENARIOS.get(scenario) if scenario else day
    chosen = liq_service.SCENARIOS["festival"] if chosen is None else chosen
    if not (liq_service.DAY_MIN <= chosen <= liq_service.DAY_MAX):
        raise svc.WalletError("invalid_day", f"day must be between {liq_service.DAY_MIN} and {liq_service.DAY_MAX}", 422)
    return chosen


def agent_user(user: User = Depends(current_user)) -> User:
    if user.role != "agent":
        raise svc.WalletError("forbidden", "This area is for agents only", 403)
    return user


@app.get("/ops/agents")
def ops_agents(day: int | None = None, scenario: str | None = None, user: User = Depends(analyst_user)):
    """Every agent: cash now, cash needed, when it runs out and how much to add."""
    return _world().overview(_day(day, scenario))


@app.get("/ops/agents/{agent_id}")
def ops_agent(agent_id: int, day: int | None = None, scenario: str | None = None, user: User = Depends(analyst_user)):
    w = _world()
    if not (0 <= agent_id < len(w.agents)):
        raise svc.WalletError("agent_not_found", "No such agent", 404)
    return w.detail(agent_id, _day(day, scenario))


@app.get("/ops/coverage")
def ops_coverage(user: User = Depends(analyst_user)):
    """Where another agent would help most, and the evidence behind the forecasts."""
    w = _world()
    return {"recommendations": w.report["coverage"], "agents": [{"agent_id": int(a.agent_id), "area": a.area, "lat": round(float(a.lat), 4), "lng": round(float(a.lng), 4)} for a in w.agents.itertuples()]}


@app.get("/ops/liquidity-report")
def ops_liquidity_report(user: User = Depends(analyst_user)):
    import liq_service
    r = _world().report
    return {"quality": r["quality"], "policy": r["policy"], "agents": r["agents"], "train_days": r["train_days"], "test_days": r["test_days"],
            "scenarios": liq_service.SCENARIOS, "scenario_text": liq_service.SCENARIO_TEXT}


@app.get("/agent/forecast")
def agent_forecast(day: int | None = None, scenario: str | None = None, user: User = Depends(agent_user)):
    """An agent's own cash forecast, in plain words, English and Bangla."""
    w = _world()
    agent_id = w.agent_for_phone(user.phone)
    if agent_id is None:
        raise svc.WalletError("agent_not_found", "This agent is not part of the forecasting demo", 404)
    return w.detail(agent_id, _day(day, scenario))


class RefillIn(BaseModel):
    day: int | None = None
    scenario: str | None = None


def _request_out(r, agent=None) -> dict:
    return {"id": r.id, "agent": {"name": agent.name, "phone": agent.phone} if agent else None, "cash_bdt": r.cash_bdt, "float_bdt": r.float_bdt,
            "needed_by": r.needed_by, "status": r.status, "created_at": r.created_at.isoformat(), "scenario_day": r.scenario_day}


@app.post("/agent/refill-request")
def agent_refill_request(body: RefillIn, user: User = Depends(agent_user), db: Session = Depends(get_db)):
    """Ask upay to bring the recommended cash and e-float."""
    w = _world()
    agent_id = w.agent_for_phone(user.phone)
    if agent_id is None:
        raise svc.WalletError("agent_not_found", "This agent is not part of the forecasting demo", 404)
    s = w.status(agent_id, _day(body.day, body.scenario))
    if s["refill_cash"] <= 0 and s["refill_float"] <= 0:
        raise svc.WalletError("nothing_needed", "No refill is needed right now", 409)
    r = RefillRequest(agent_user_id=user.id, scenario_day=s["day"], cash_bdt=s["refill_cash"], float_bdt=s["refill_float"], needed_by=s["runout_label"])
    db.add(r)
    db.commit()
    return {"request": _request_out(r, user)}


@app.get("/agent/refill-requests")
def agent_refill_requests(user: User = Depends(agent_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(RefillRequest).where(RefillRequest.agent_user_id == user.id).order_by(RefillRequest.id.desc()).limit(20)).all()
    return {"requests": [_request_out(r, user) for r in rows]}


@app.get("/ops/refill-requests")
def ops_refill_requests(user: User = Depends(analyst_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(RefillRequest).order_by(RefillRequest.status.desc(), RefillRequest.id.desc()).limit(50)).all()
    return {"requests": [_request_out(r, db.get(User, r.agent_user_id)) for r in rows]}


@app.post("/ops/refill-requests/{request_id}/dispatch")
def ops_dispatch(request_id: int, user: User = Depends(analyst_user), db: Session = Depends(get_db)):
    r = db.get(RefillRequest, request_id)
    if r is None:
        raise svc.WalletError("request_not_found", "No such request", 404)
    if r.status != "open":
        raise svc.WalletError("already_decided", "This request was already handled", 409)
    r.status, r.dispatched_at, r.dispatched_by = "dispatched", utcnow(), user.id
    db.commit()
    return {"request": _request_out(r, db.get(User, r.agent_user_id))}


@app.post("/wallet/send/preview")
def send_preview(body: PreviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Shield's opinion on a transfer before the PIN step. Moves no money."""
    behavior = body.behavior.model_dump() if body.behavior else None
    answers = [a.model_dump() for a in body.safety_answers] if body.safety_answers else None
    decision, recipient = svc.preview_send(db, user, body.recipient_phone, body.amount, behavior, answers)
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


@app.post("/demo/release-holds-now")
def demo_release_holds(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """DEMO ONLY: end your own holds right now, so the 30-minute wait can be shown in seconds."""
    if not DEMO_MODE:
        raise svc.WalletError("demo_disabled", "Demo tools are switched off", 404)
    return {"released": svc.release_holds_now(db, user)}


@app.post("/demo/reset")
def demo_reset(user: User = Depends(analyst_user)):
    """DEMO ONLY (analysts): wipe everything and rebuild the demo world, ready to present."""
    if not DEMO_MODE:
        raise svc.WalletError("demo_disabled", "Demo tools are switched off", 404)
    return svc.reset_demo(database.engine, database.SessionLocal)


@app.post("/wallet/cash-out")
def cash_out(body: CashOutIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    txn = svc.cash_out(db, user, body.agent_phone, body.amount, body.pin, body.idempotency_key)
    db.refresh(user)
    return {"transaction": txn_out(txn), "balance": user.balance}


@app.get("/wallet/transactions")
def transactions(limit: int = 20, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"transactions": svc.history(db, user, limit)}
