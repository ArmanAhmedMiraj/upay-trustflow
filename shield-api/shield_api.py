"""Shield API: the transfer-risk engine as a web service.

Run it from inside the shield-api folder:
    uvicorn shield_api:app --port 8001

Then open http://localhost:8001/docs to try it in the browser.

Design rules
 - The wallet calls Shield; Shield never moves money. It only returns advice.
 - If Shield is down or fails, the wallet must keep working (it falls back to "allow").
   Shield therefore answers 503 instead of guessing when its model is not loaded.
 - Inputs are validated, so a bad request cannot produce a silent wrong score.
"""
from __future__ import annotations

import pathlib
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "transfer_risk"))
import messages  # noqa: E402
import safety_check  # noqa: E402
import request_auth  # noqa: E402
import scorer  # noqa: E402
from graded_risk import api as graded_api  # noqa: E402
from features import FEATURES  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.artifacts = scorer.load_artifacts()
        app.state.load_error = None
    except Exception as exc:  # the API still starts, and /health reports the problem
        app.state.artifacts = None
        app.state.load_error = str(exc)
    app.state.llm = messages.make_llm_from_env()   # None unless LLM_API_KEY is set: templates are used
    yield


app = FastAPI(title="upay Shield API", version="1.0", lifespan=lifespan,
              description="Scores a transfer before the customer confirms it. Advice only: it never blocks money.")


# only the wallet may ask for a score: calls must be signed when SHIELD_API_SECRET is set (see request_auth.py)
app.add_middleware(request_auth.SignedRequests)

# the graded-risk model with per-signal explanations (sender, recipient and link signals); see graded_risk/
app.include_router(graded_api.router)


class TransferFeatures(BaseModel):
    """The signals about one transfer. The wallet (or, later, Shield itself) fills these in."""
    # Group A: sender behaviour
    amount_zscore: float = Field(ge=-10, le=30, description="Amount compared with this sender's usual amounts")
    balance_share: float = Field(ge=0, le=1, description="Share of the wallet balance being sent")
    is_first_time_recipient: int = Field(ge=0, le=1)
    is_round_amount: int = Field(ge=0, le=1)
    hour_unusual: float = Field(ge=0, le=1, description="0 = the sender's usual hour, 1 = never sends at this hour")
    log_mins_since_incoming: float = Field(ge=0, le=12, description="log(1 + minutes since the sender last received money)")
    hesitation_secs: float = Field(ge=0, le=3600)
    amount_edits: int = Field(ge=0, le=50)
    on_call: int = Field(ge=0, le=1)
    sender_history_count: int = Field(ge=0)
    # Group B: recipient wallet
    recipient_age_days: float = Field(ge=0)
    first_time_senders_24h: int = Field(ge=0)
    recipient_inflow_count_24h: int = Field(ge=0)
    recipient_outflow_ratio_24h: float = Field(ge=0, le=3)
    recipient_prior_txns: int = Field(ge=0)
    report_count: int = Field(ge=0)
    report_rate: float = Field(ge=0)
    # Group C: story check (SMS claim against the ledger)
    sms_claims_credit: int = Field(ge=0, le=1)
    sms_mentions_recipient: int = Field(ge=0, le=1)
    ledger_confirms_credit: int = Field(ge=0, le=1)
    claim_ledger_mismatch: int = Field(ge=0, le=1)
    claim_mismatch_on_recipient: int = Field(ge=0, le=1)
    sms_official_sender: int = Field(ge=0, le=1)


class Reason(BaseModel):
    source: str = Field(description="'rule' = a verified fact, 'model' = a learned signal")
    feature: str
    text: str
    share_pct: int | None = Field(default=None, description="Share of the model's push towards 'risky' (model reasons only)")


class Question(BaseModel):
    id: str
    risky_answer: str = Field(description="Which answer is the worrying one for this question")
    bn: str = Field(description="Question text in Bangla (shown to the customer)")
    en: str = Field(description="Question text in English (for analysts and judges)")


class RiskResponse(BaseModel):
    risk_pct: int
    tier: str = Field(description="low, note, high or very_high")
    action: str = Field(description="allow, allow_with_note, safety_check or hold_30min")
    scam_type: str | None
    reasons: list[Reason]
    questions: list[Question] = Field(default_factory=list, description="Safety-check questions, only when action = safety_check")
    message_bn: str | None = Field(default=None, description="Warning for the customer in Bangla (none for low risk)")
    message_en: str | None = Field(default=None, description="The same warning in English, for analysts")
    message_source: str | None = Field(default=None, description="'template' or 'llm'")
    model_version: str
    latency_ms: float


class Answer(BaseModel):
    question_id: str
    answer: str = Field(description="yes, no or not_sure")


class RefineRequest(BaseModel):
    features: TransferFeatures
    answers: list[Answer]


class RefineStep(BaseModel):
    question_id: str
    answer: str
    log_odds_change: float


class RefineResponse(BaseModel):
    risk_before_pct: int
    risk_after_pct: int
    tier_before: str
    tier_after: str
    action_after: str
    total_log_odds_change: float
    steps: list[RefineStep]
    scam_type: str | None
    reasons: list[Reason] = Field(default_factory=list)
    message_bn: str | None = None
    message_en: str | None = None
    message_source: str | None = None


def _artifacts(request: Request) -> scorer.Artifacts:
    art = request.app.state.artifacts
    if art is None:
        raise HTTPException(status_code=503, detail="Shield model is not loaded; the wallet should allow the transfer")
    return art


def _attach_message(result: dict, tier: str, request: Request) -> None:
    """Add the customer's warning. The decision (tier, action) is already final; this only adds words."""
    msg = messages.generate_message(tier, result.get("scam_type"), result["reasons"], request.app.state.llm)
    result["message_bn"] = msg["bn"] if msg else None
    result["message_en"] = msg["en"] if msg else None
    result["message_source"] = msg["source"] if msg else None


@app.get("/health")
def health(request: Request):
    art = request.app.state.artifacts
    return {
        "status": "ok" if art is not None else "degraded",
        "model_loaded": art is not None,
        "model_version": "v1",
        "feature_count": len(FEATURES),
        "tier_thresholds": art.tiers if art is not None else None,
        "error": request.app.state.load_error,
    }


@app.post("/risk/score", response_model=RiskResponse)
def risk_score(body: TransferFeatures, request: Request):
    art = _artifacts(request)
    t0 = time.perf_counter()
    result = scorer.score_transfer(body.model_dump(), art)
    result["questions"] = safety_check.questions_for(result["scam_type"]) if result["action"] == "safety_check" else []
    _attach_message(result, result["tier"], request)
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result


@app.get("/risk/questions", response_model=list[Question])
def risk_questions(scam_type: str | None = None):
    """The safety-check questions for a scam type (or the fallback pair when the type is unknown)."""
    return safety_check.questions_for(scam_type)


@app.post("/risk/refine", response_model=RefineResponse)
def risk_refine(body: RefineRequest, request: Request):
    """Re-score a transfer using the customer's safety-check answers.

    The starting score is recomputed from the features, so it cannot be tampered with.
    """
    art = _artifacts(request)
    answers = {a.question_id: a.answer for a in body.answers}
    try:
        result = safety_check.refine(body.features.model_dump(), answers, art)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _attach_message(result, result["tier_after"], request)
    return result
