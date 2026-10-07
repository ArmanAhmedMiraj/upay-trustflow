# Upay Shield: AI Fraud Protection and Agent Cash Forecasting for Mobile Money

**Stopping people from being talked into sending money to scammers, at the moment they press Send.**

Built for **AI Dev Fest 2026 (DIU CPC × upay)**. Two modules: **Shield** (Track 01, Trust & Risk) and **Agent Cash Forecasting** (Track 05, Merchant & Agent). All data is synthetic.

- **Live demo:** https://upay-trustflow.onrender.com/  *(the free plan sleeps when idle; the first visit takes about a minute)*
- **Demo accounts:** tap a name on the login screen. Customers use PIN `12345`; the fraud analyst uses `99999`.
- **Project report and demo video:** submitted with this repository.

---

## 1. Overview

### The problem
In mobile money, a common fraud is not a hack. The customer is **talked into sending the money themselves**: a fake
"your account will be blocked" call, a fake "I sent you money by mistake, please return it" SMS, a prize fee, an urgent
request from a "relative" on a new number, or an advance payment for a shop, job or visa. The customer enters the correct PIN
on their own phone, so account-security checks see a normal transfer. The money is lost, trust in digital finance is damaged,
and upay carries the complaints.

### The solution
**Shield** is a security layer that sits inside the wallet. Before the customer enters their PIN, it shows a live,
calibrated **security-risk %**, in Bangla, with the reasons. The response is graded:

| Risk | What the customer sees |
|---|---|
| Low | Nothing. The transfer goes through. |
| Note | A one-line reminder. |
| Safety check | Two short questions in Bangla; the answers re-score the transfer. |
| Hold | A warning and a **cancellable 30-minute hold**, reviewed by a fraud analyst. |

Shield never blocks money by itself. The customer can always cancel, an analyst can approve or reject, and an unanswered hold is
released when its time is up.

### Module 2: agent cash forecasting
Agents run out of cash, or of e-float, at the worst moments: payday, the days before Eid, market days. A customer who is turned
away at the counter loses trust, and the agent loses commission. This module forecasts, for every agent, **how much cash will be
needed in the next 24 hours, when it will run out, how much to add, and where another agent would help**. It tells the agent on
their phone (English and Bangla) and tells upay's operations team on a map, with a refill-request loop between them.

### Purpose
Show upay a working, explainable and responsible way to protect customers from coached-transfer fraud and to keep agents
stocked with cash, with measurable customer and business impact, and a clear path to validation on real, governed data.

---

## 2. Features and how AI is used

| Feature | How it works | AI / method |
|---|---|---|
| Live security-risk % | 23 signals about the sender's habits, the recipient wallet and the SMS "story" are combined into one probability | LightGBM classifier, isotonic calibration, monotone constraints |
| "Is the story true?" check | A "money received" SMS is checked against the upay ledger. A false claim naming the recipient is a verified fact | Exact ledger lookup (not AI) plus one hard rule, kept separate from the model |
| Reasons for every alert | Each reason is labelled *Verified fact* (rule) or *Pattern* (model) | TreeSHAP contributions |
| Scam-type guess | Matches the warning to the likely script (return-by-mistake, fake officer, prize fee, relative emergency, advance payment) | Multiclass LightGBM |
| Safety-check questions | Two Bangla questions; answers change the odds by fixed, capped amounts; a "no" can only lower risk a little because victims are coached | Documented log-odds update |
| Bangla warnings | Reviewed fixed templates by default; an optional LLM rewrite is allowed only from fixed phrases and its reply is validated, with automatic fallback | Template + guarded GenAI |
| Network learning | Customers can report a number; reports raise the risk for the next sender | Report-rate signal in the model |
| 30-minute hold | Money leaves the sender, waits in escrow, can be cancelled, is reviewed by an analyst, and auto-releases | Business logic |
| Analyst console | Held cases with reasons, approve / reject, live countdown | Explainable AI output |
| Impact dashboard | Measures what customers did after each warning, in taka, plus offline test results | Measured outcomes |
| Wallet | Register, PIN login with lockout, add money, send, cash out, history, inbox, report. English and Bangla, installable on a phone | Software engineering |
| Agent cash forecast | Hour-by-hour cash-out and cash-in demand for each agent for the next 48 hours, with a normal-day and a busy-day line | LightGBM quantile regression (4 models), calendar-aware, scale-free |
| Run-out time and refill amount | Cash needed = the deepest point of the running balance; run-out = the first hour it goes below zero. Kept separate from the model so an operator can audit it | Plain arithmetic |
| Agent phone screen and operations map | The agent sees status, run-out time and a message in Bangla; operations sees every agent on a map, sorted by urgency | Explainable output |
| Refill requests | An agent asks upay to bring cash with one tap; operations dispatches it | Workflow |
| Where to add agents | Finds areas where each agent carries far more than the city's typical load and estimates what a new agent would take | Demand-per-agent analysis |

**Responsible-AI choices:** synthetic data only; explainable reasons; a fairness check across customer groups; robustness tests
against fraudsters who adapt; prompt-injection-safe design; human oversight on every hold; the wallet keeps working if Shield is
unavailable (it fails open and logs it).

---

## 3. Tech stack

| Layer | Technology |
|---|---|
| Languages | Python 3.12 (also run on 3.14), JavaScript (React) |
| Backend | FastAPI, Uvicorn, SQLAlchemy, Pydantic; SQLite (PostgreSQL-ready through `DATABASE_URL`) |
| Machine learning | LightGBM (fraud classifier and cash-demand quantile models), scikit-learn (training and baselines), NumPy, pandas, matplotlib |
| Generative AI | Optional LLM API (Anthropic Messages API) for Bangla warning wording; off unless `LLM_API_KEY` is set |
| Frontend | React 19, Vite 8, installable web app (manifest + service worker), English and Bangla |
| Testing | pytest (Python), Vitest and Testing Library (app) |
| Deployment | Docker, Render (free plan) |
| Services | No external service is required to run the demo |

---

## 4. Requirements

- **Software:** Python 3.12 or newer, Node.js 22.22 or newer (or 24.15+), Git.
- **Hardware:** any modern laptop. The live service uses about 200 MB of memory (peak about 280 MB while building the demo world).
- **Prerequisites:** none beyond the above. No real customer data, API key or account is needed.

---

## 5. Installation and setup

```
git clone https://github.com/ArmanAhmedMiraj/upay-trustflow.git
cd upay-trustflow

python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell.  On macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cd wallet-app
npm install
cd ..
```

The trained models are included in `shield-api/transfer_risk/artifacts/` (fraud) and `shield-api/liquidity/artifacts/` (agent
cash). To train them again from scratch (1 to 2 minutes each):
```
python shield-api/transfer_risk/train.py
python shield-api/liquidity/liq_train.py
```

### Environment variables
Copy `.env.example` to `.env` if you want to change anything. Placeholders only; no secrets belong in the repository.

| Name | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Database address | `wallet-api/trustflow.db` (SQLite) |
| `SHIELD_API_URL` | Where the wallet finds Shield. Empty means Shield is off and every transfer is allowed | empty |
| `SHIELD_TIMEOUT_SECONDS` | How long the wallet waits for Shield | `2.0` |
| `LLM_API_KEY` | Optional key for AI-written Bangla warnings. Without it, fixed templates are used | none |
| `LLM_MODEL` | Model name for the optional LLM | `claude-sonnet-5-5` |
| `PIN_PEPPER` | Secret mixed into PIN hashes. Set a long random value in production | development value |
| `DEMO_MODE` | `0` hides the demo tools and reset button | `1` |
| `HOLD_MINUTES` | Length of a hold | `30` |
| `SEED_ON_START` / `SEED_USERS` | Deployed service: build the demo world on start-up, and its size | `1` / `1500` |
| `CORS_ORIGINS` | Allowed browser origins | `*` |
| `VITE_WALLET_API` | Wallet address used by the app (empty = same address) | `http://localhost:8000` in development |
| `VITE_DEMO` | `0` hides the demo-account buttons | `1` |

---

## 6. Run it

### Option A: one command, one address (same as the live service)
```
cd wallet-app
npm run build
cd ..
python -m uvicorn deploy.app:app --port 9000
```
Open http://localhost:9000. On the first start it builds the synthetic demo world (about 5 seconds).

### Option B: three terminals (development)
```
# Terminal 1: Shield
cd shield-api
python -m uvicorn shield_api:app --port 8001

# Terminal 2: wallet (builds the demo world first)
python simulator/seed_wallet.py --reset
cd wallet-api
$env:SHIELD_API_URL = "http://localhost:8001"          # macOS/Linux: export SHIELD_API_URL=http://localhost:8001
python -m uvicorn wallet_api:app --port 8000

# Terminal 3: phone app
cd wallet-app
npm run dev                                            # http://localhost:5173
```

### Try the demo
1. Tap **Rahim** and log in. Open **Demo tools** and tap **Drop SMS** (a scammer's fake "money received" message).
2. **Send Money** to `01711999999`, amount `5000`, and press Continue. You see **100%**, the warning, and the verified ledger fact.
3. Confirm with PIN `12345`. The money is held, with a 30-minute countdown. Tap **Cancel** to get every taka back.
4. Log in as **Fraud analyst** (in a private window) to review cases and open the **Impact** tab.
5. In the analyst console, **Reset demo** rebuilds the world. Do this just before presenting.
6. **Agent cash (Module 2):** in the analyst console open the **Agents** tab. Switch between *A normal day*, *Payday week* and
   *Festival rush* and watch the map turn from green to red. Click an agent to see the forecast, the run-out time and the message.
7. Log in as **Agent Babul** on a phone-sized window. He sees that his cash will run short, when, and how much to add, in English or
   Bangla. Tap **Ask upay to bring cash**; in the console the request appears under *Refill requests* and you can **Dispatch** it.

| Demo character | Phone | Role |
|---|---|---|
| Rahim Uddin | 01711000001 | The customer who is scammed |
| Rahima Begum (Mum) | 01711000002 | Everyday payments |
| Nusrat Jahan | 01711000005 | Another customer (use it for the safety-check questions) |
| Fashion Hub BD | 01711000007 | A young online seller |
| Jamal Hossain | 01711999999 | Fraud wallet 1 (already reported twice) |
| Mitu Akter | 01711999998 | Fraud wallet 2 (not yet reported) |
| Agent Babul | 01811000001 | Agent cash forecast (PIN 12345) |
| Fraud analyst | 01911000001 | PIN 99999 |

Run `python simulator/check_demo_scenarios.py` to see what Shield decides for each situation, and which amount lands in the
question tier at this moment (it depends on the time of day).

---

## 7. Testing

```
python -m pytest -q                    # backend, both models, deployment: 278 tests
cd wallet-app
npm test                               # phone app and console: 134 tests
```
What the tests prove: features never use the future (a test rebuilds features from truncated history and we checked it catches a
deliberate leak); the live feature builder matches the training builder on a whole simulated world; no single signal can raise an
alert alone; balances always match the ledger after hundreds of random operations including holds, cancels and reviews;
the impact numbers match what happened to each flagged transfer. For Module 2, the forecast features use only what was known before
the morning being forecast, the cash-needed arithmetic matches hand-worked cases, and the forecast beats a "copy last week" baseline.
We also broke key behaviours on purpose to confirm tests fail.

---

## 8. Results (synthetic test period never used for training or calibration)

50,960 transfers, 943 fraudulent.

| System | PR-AUC | Fraud caught at 2% friction |
|---|---|---|
| Simple rules | 0.32 | 34% |
| Logistic regression | 0.83 | 84% |
| LightGBM | 0.83 | 84% |

At the safety-check level (30% risk or above): 0.2% of genuine transfers disturbed, 72% of fraud caught (82% by value), 87% of
warnings were real fraud. Calibration error 0.002. Scoring takes about 4 ms. Details and charts: `reports/module1/summary.md`.

**These numbers prove the method on synthetic data. They are not performance claims about real upay data.**

### Module 2: agent cash (120 simulated agents, 12 areas of Dhaka, 19 days the model never saw)

| Refill method | Customers turned away | Average cash on hand | Normal days | Payday | Festival rush |
|---|---|---|---|---|---|
| Refill to last week's need + 20% | 26.4% | ৳86,711 | 0.05% | 26.6% | 45.5% |
| Same, scaled to the forecast's average cash | 28.0% | ৳78,506 | 0.13% | 31.2% | 47.5% |
| **Refill from the forecast** | **0.14%** | ৳78,506 | 0.37% | 0.27% | 0% |

- The forecast error is 67% lower than copying "the same hour last week". The busy-day line covered 92.7% of hours (target 90%),
  and 95.1% of hours during the festival rush.
- **The gain comes from rush days.** Copying last week works on quiet days and fails when demand jumps. On normal days the forecast
  method is not better (0.37% against 0.05% missed).
- **It has a cost:** the forecast method moves about 84% more cash through refills, because it stocks up before rush days.
- A safety setting trades cash against service: planning 0% of the way to a busy day misses 3.6% of demand with ৳38,800 on hand;
  60% (our choice, picked on earlier validation days) misses 0.14% with ৳78,500; 100% misses 0.01% with ৳110,100.
- New-agent suggestions, e.g. Tejgaon (each agent carries 2.5× the typical load), Jatrabari (1.9×), Motijheel (1.7×).

---

## 9. Repository map

```
deploy/            one-address service (wallet + Shield + phone app), Dockerfile at the root, render.yaml
wallet-api/        accounts, ledger, holds, analyst API, live feature builder, impact calculation
shield-api/        Shield API and the transfer-risk engine (features, model, rules, safety check, messages)
shield-api/liquidity/  Module 2: agent simulator, cash-demand models, refill arithmetic, coverage, service
wallet-app/        React phone app and analyst console
simulator/         synthetic data generator, demo-world seeding, scenario checker
reports/module1/   evaluation results, charts, rule experiments
docs/              problem statements, synthetic-data assumptions, demo script
tests/             backend tests
```

---

## 10. Honest limitations

- All results come from synthetic data. Real upay data would be used to retrain and recalibrate, first in "shadow mode".
- A wallet with **no history** looks risky to the model. The demo is seeded so everyday wallets have history.
- A fraudster using an old, quiet account and acting calmly defeats the model (fraud caught falls to about 25%). Combine with
  account-level controls.
- The scam-type guess is only about 54% accurate, so general advice is used until a transfer is held.
- LightGBM performs about the same as logistic regression on this synthetic data; the large gain is over simple rules.
- SMS reading and the "on a call" flag are simulated; a production app would read them on the phone.
- The optional LLM wording path has been tested against its guards but not against the live service.
- **Module 2 limits:** the agents, their demand and the Eid and payday patterns are all simulated. The model saw only one festival
  in training; an earlier version confused the days before the festival with payday until we moved the simulated festival away from
  payday, so real use needs several years of calendar history. Demand per agent is divided by an agent's recent level, so a brand-new
  agent with no history cannot be forecast. The coverage suggestions come from demand per agent only; they ignore roads, rent and
  competitors. Refill logistics (trucks, routes, cost per delivery) are not modelled.

## Licence
MIT. See `LICENSE`.


## Updates during the final (7 October 2026)

Work done during the final, in response to the Phase 1 judge feedback. All numbers below were measured on one laptop with the synthetic demo data.

**Security: signed wallet-to-Shield calls.** When `SHIELD_API_SECRET` is set on both sides, every call from the wallet to Shield carries an HMAC-SHA256 signature over a timestamp and the request body. Shield refuses unsigned, altered or replayed (older than 5 minutes) calls with a 401. With no secret set nothing changes, so the demo and the tests run as before (`shield-api/request_auth.py`, `tests/test_request_auth.py`).

**Performance: load and latency test.** `python simulator/load_test_shield.py` sends valid made-up transfers to Shield and prints throughput and latency.
- One caller at a time: median 6.2 ms per score over HTTP (p95 11.8 ms, p99 14.5 ms), about 126 scores per second.
- 50 callers at once: about 135 scores per second, 0 failures out of 1,000. One Shield process on one laptop reaches roughly 130 scores per second; scaling beyond that means running more copies of the service, which we have not load tested.

**Accessibility: automated WCAG 2.1 A/AA audit (axe-core).** We checked the login screen (0 violations), the home screen (1 colour-contrast violation, fixed, then 0) and the risk-warning screen (0 violations). This is an automated check, which finds only part of the possible problems. Screen-reader and keyboard testing are still to be done.

**Honest notes.**
- All data is synthetic. Validation on real upay data is the first step of any pilot.
- Before the final we also prepared, on a private branch, a second experimental model and an analyst explanation view. They are not part of this repository.
- Known limits: quiet, unreported mule wallets are the weakest case, and the scam-type guess is only about 54% accurate.
