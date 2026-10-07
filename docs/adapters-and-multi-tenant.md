# Adapters and multi-tenant design

Judges asked how Shield could serve more than one provider. This is the design, and the part that is built and tested.

## The idea in one paragraph
Shield is a stateless advisory service: a provider sends the signals about one transfer, Shield returns a risk score, a tier,
reasons and questions, and keeps nothing. So many providers can share one Shield safely. Two small pieces make that real:
a **tenant** (who is calling, proved by their own secret) and an **adapter** (that provider's field names and units
turned into Shield's signals). The model, thresholds and explanations are shared and never changed by an adapter.

## What is built
| Piece | File | What it does |
|---|---|---|
| Tenants | `shield-api/tenants.py` | Each provider has an id, its own signing secret and an adapter name, set in the `SHIELD_TENANTS` environment variable (JSON). With it unset, Shield behaves exactly as before (one provider, `SHIELD_API_SECRET`). |
| Per-tenant signing | `shield-api/request_auth.py` | The caller names itself in the `X-Shield-Tenant` header and signs with its own secret (same HMAC-SHA256 as before). Provider A's secret cannot sign as provider B; an unknown tenant gets 401. No header means `upay`. |
| Adapters | `shield-api/adapters.py` | `upay` is a pass-through; `demo-mfs` is an invented second provider with other field names, milliseconds instead of seconds, Y/N flags and percentages. Adding a provider means one function plus one registry line. |
| Endpoint | `POST /risk/score-adapted` | Takes the provider's own format, translates it with that tenant's adapter, scores it with the shared model. A request the adapter cannot read gets a clear 422 naming the missing field. |
| Tests | `tests/test_tenants.py` | The invented provider gets exactly the same score as our own format for the same transfer; one provider cannot sign as another; unknown tenants are refused; a bad request is a clear 422; with no tenants set nothing changes. |

Example environment (placeholders only, never real secrets):
```
SHIELD_TENANTS={"upay":{"secret":"<secret-1>","adapter":"upay"},"demo-mfs":{"secret":"<secret-2>","adapter":"demo-mfs"}}
```

## Why this isolates providers
- **No shared data.** Shield stores no customer or transfer data between calls, so there is no table where one provider's
  customers could leak to another. Each provider's ledger stays in its own wallet system.
- **Own keys.** A leaked secret affects one provider only, and each secret can be rotated on its own.
- **Same model, same rules.** Every provider gets the same explainable score, which makes results comparable and audits simpler.

## What is NOT built (be honest about it)
- **Adapters for real providers.** `demo-mfs` is invented. A real adapter needs that provider's real field list.
- **Per-tenant calibration and thresholds.** Today all tenants share one calibration and the same tier cut-offs. Different
  providers have different fraud rates, so a pilot should calibrate per tenant on that provider's own data.
- **Per-tenant monitoring, rate limits and billing,** and a tenant admin screen. Tenants are set by configuration.
- **Shield building the signals itself.** Providers still compute the signals (our wallet does it from its ledger). A
  provider that cannot would need a feature-building adapter that reads its transaction history, which is larger work.
- **Secret storage.** Secrets come from environment variables; production would use a secrets manager.

## Pilot path
1. Shadow mode: the provider sends real transfers, Shield scores silently, results are compared with confirmed fraud reports.
2. Calibrate the tiers on that provider's data. 3. Switch on notes, then safety checks, then holds for the top tier in one region.
