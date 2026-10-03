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
import scorer  # noqa: E402
from features import FEATURES  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.artifacts = scorer.load_artifacts()
        app.state.load_error = None
    except Exception as exc:  # the API still starts, and /health reports the problem
        app.state.artifacts = None
        app.state.load_error = str(exc)
    yield


app = FastAPI(title="upay Shield API", version="1.0", lifespan=lifespan,
              description="Scores a transfer before the customer confirms it. Advice only: it never blocks money.")


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


class RiskResponse(BaseModel):
    risk_pct: int
    tier: str = Field(description="low, note, high or very_high")
    action: str = Field(description="allow, allow_with_note, safety_check or hold_30min")
    scam_type: str | None
    reasons: list[Reason]
    model_version: str
    latency_ms: float


def _artifacts(request: Request) -> scorer.Artifacts:
    art = request.app.state.artifacts
    if art is None:
        raise HTTPException(status_code=503, detail="Shield model is not loaded; the wallet should allow the transfer")
    return art


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
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result
