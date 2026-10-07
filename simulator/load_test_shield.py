"""Load test for Shield: how many risk scores per second, and how fast is each one, with many callers at once?

It sends made-up but valid transfers (about 70% genuine-looking, 30% scam-looking) to Shield's /risk/score, several at
the same time, then prints throughput and latency. It never touches the wallet database and moves no money.

    python simulator/load_test_shield.py                       # 500 requests, 20 at once, against http://localhost:9100/shield
    python simulator/load_test_shield.py --requests 2000 --workers 50 --url http://localhost:9000/shield

If SHIELD_API_SECRET is set it signs the calls, exactly as the wallet does.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


def genuine(rng: random.Random) -> dict:
    return {
        "amount_zscore": rng.uniform(-1, 1.5), "balance_share": rng.uniform(0.01, 0.3),
        "is_first_time_recipient": int(rng.random() < 0.2), "is_round_amount": int(rng.random() < 0.3),
        "hour_unusual": rng.uniform(0, 0.3), "log_mins_since_incoming": rng.uniform(1, 9),
        "hesitation_secs": rng.uniform(2, 15), "amount_edits": rng.randint(0, 1), "on_call": 0,
        "sender_history_count": rng.randint(20, 300),
        "recipient_age_days": rng.uniform(100, 1500), "first_time_senders_24h": rng.randint(0, 3),
        "recipient_inflow_count_24h": rng.randint(0, 30), "recipient_outflow_ratio_24h": rng.uniform(0, 0.6),
        "recipient_prior_txns": rng.randint(50, 2000), "report_count": 0, "report_rate": 0.0,
        "sms_claims_credit": 0, "sms_mentions_recipient": 0, "ledger_confirms_credit": 0,
        "claim_ledger_mismatch": 0, "claim_mismatch_on_recipient": 0, "sms_official_sender": 0,
    }


def scam_like(rng: random.Random) -> dict:
    claim = int(rng.random() < 0.4)
    return {
        "amount_zscore": rng.uniform(3, 12), "balance_share": rng.uniform(0.5, 0.95),
        "is_first_time_recipient": 1, "is_round_amount": 1,
        "hour_unusual": rng.uniform(0.5, 1), "log_mins_since_incoming": rng.uniform(0, 3),
        "hesitation_secs": rng.uniform(20, 90), "amount_edits": rng.randint(2, 6), "on_call": 1,
        "sender_history_count": rng.randint(5, 60),
        "recipient_age_days": rng.uniform(0.5, 8), "first_time_senders_24h": rng.randint(4, 14),
        "recipient_inflow_count_24h": rng.randint(4, 15), "recipient_outflow_ratio_24h": rng.uniform(0.6, 1.5),
        "recipient_prior_txns": rng.randint(2, 30), "report_count": rng.randint(0, 3), "report_rate": rng.uniform(0, 0.4),
        "sms_claims_credit": claim, "sms_mentions_recipient": claim, "ledger_confirms_credit": 0,
        "claim_ledger_mismatch": claim, "claim_mismatch_on_recipient": claim, "sms_official_sender": 0,
    }


def make_payloads(how_many: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    return [genuine(rng) if rng.random() < 0.7 else scam_like(rng) for _ in range(how_many)]


def send(client: httpx.Client, url: str, payload: dict, secret: str) -> tuple[float, int, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        stamp = str(int(time.time()))
        headers["X-Shield-Timestamp"] = stamp
        headers["X-Shield-Signature"] = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    start = time.perf_counter()
    try:
        response = client.post(url, content=body, headers=headers)
        return (time.perf_counter() - start) * 1000, response.status_code, response.text[:200]
    except Exception as exc:  # network error: count it as a failure
        return (time.perf_counter() - start) * 1000, 0, str(exc)[:200]


def percentile(sorted_values: list[float], p: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(p / 100 * len(sorted_values)))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:9100/shield", help="Shield address (default: %(default)s)")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--workers", type=int, default=20, help="callers at the same time")
    args = parser.parse_args()

    secret = os.getenv("SHIELD_API_SECRET", "").strip()
    target = args.url.rstrip("/") + "/risk/score"
    payloads = make_payloads(args.requests)

    with httpx.Client(timeout=10.0, limits=httpx.Limits(max_connections=args.workers)) as client:
        first = send(client, target, payloads[0], secret)           # warm-up: the model may load on first use
        if first[1] != 200:
            sys.exit(f"STOP: Shield did not answer the first call ({first[1]}): {first[2]}")
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(lambda p: send(client, target, p, secret), payloads))
        elapsed = time.perf_counter() - started

    ok = sorted(ms for ms, status, _ in results if status == 200)
    failed = [r for r in results if r[1] != 200]
    print(f"Shield at {target}")
    print(f"  {args.requests} requests, {args.workers} at the same time, {'signed' if secret else 'unsigned'}")
    print(f"  finished in {elapsed:.2f} s  ->  {len(ok) / elapsed:,.0f} scores per second")
    if ok:
        print(f"  latency per score: median {statistics.median(ok):.1f} ms, p95 {percentile(ok, 95):.1f} ms, "
              f"p99 {percentile(ok, 99):.1f} ms, slowest {ok[-1]:.1f} ms")
    print(f"  failed: {len(failed)} of {args.requests}" + (f"  (first: {failed[0][1]} {failed[0][2]})" if failed else ""))
    print("  Note: this measures the scoring service on this one computer; the number depends on the machine.")


if __name__ == "__main__":
    main()