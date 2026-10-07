# Production infrastructure

What the live demo is, what a production-shaped deployment looks like, and exactly what is built and tested versus not.

## The live demo (built, tested, running)
One Docker service on Render: the phone app, the wallet API and Shield together, SQLite, synthetic data rebuilt on start.
Health check `/health`. This is right for a demo and wrong for production on purpose.

## Built and tested in this repository
| Need | What exists | Where | Proof |
|---|---|---|---|
| Is it alive? | `/health` on wallet and Shield | `wallet_api.py`, `shield_api.py` | existing tests |
| Should it get traffic? | `/ready`: Shield answers 503 until the model is loaded; the wallet answers 503 if the database does not answer | same | `tests/test_monitoring.py` |
| Monitoring | `/metrics` in Prometheus text format: requests by route and status, latency histogram, decisions by tier, uptime. Counters only, never customer data. Routes are counted by template, not by id, so labels stay few | `shield-api/metrics.py` | `tests/test_monitoring.py` |
| Service-to-service security | signed calls (HMAC-SHA256), per-provider secrets | `request_auth.py`, `tenants.py` | `tests/test_request_auth.py`, `tests/test_tenants.py` |
| Fail safely | if Shield is down the wallet allows the payment; Shield answers 503 rather than guessing | wallet risk hook | existing tests |
| Scale out | Shield keeps no data between calls, so copies can be added behind a load balancer (first model about 130 scores/s per copy on one laptop) | design | load test of one copy only |
| Offline agents | an agent's phone keeps the last forecast it received and shows it, labelled with the time saved, when there is no connection. A server refusal is never replaced by an old forecast. | `AgentHome.jsx` | `Agents.test.jsx` (3 tests) |
| Database setting | the wallet reads `DATABASE_URL` (SQLite by default) | `wallet-api/database.py` | SQLite only |

## Written but not run here
- `docker-compose.production.yml`: PostgreSQL, 2 wallet copies, 2 Shield copies, readiness-based health checks. **Not run in this
  environment and the wallet has not been tested on PostgreSQL.** It also needs a PostgreSQL driver in the image and a real
  secrets manager. Treat it as the starting layout for a pilot, not as proven.

## Not built (the honest list)
- Alerting rules and dashboards on top of `/metrics` (the numbers are exposed; nothing watches them).
- Database migrations (Alembic), backups, point-in-time recovery, high-availability database.
- Rate limiting and abuse protection in front of the API (belongs in a gateway or load balancer).
- Structured request logging with correlation ids, log shipping, tracing.
- Secrets manager, key rotation, TLS termination (done by the platform or load balancer).
- Autoscaling, multi-region, disaster recovery, load test of the two-model path and of many copies together.
- True offline *actions* for agents (queueing a refill request while offline). Only the last forecast is kept.
- Model operations: drift monitoring, scheduled retraining, model registry, shadow mode comparison on real data.

## Suggested pilot order
1. Run the compose file on a test server; fix what PostgreSQL shows. 2. Point Prometheus at `/metrics` and `/ready`, add alerts for
5xx rate, p95 latency and any 503 from `/ready`. 3. Shadow mode: score real transfers silently and compare with confirmed
fraud. 4. Add a gateway for TLS, rate limits and per-provider keys. 5. Load test the full path, then turn on notes, safety checks, holds.
