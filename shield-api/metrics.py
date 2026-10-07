"""Monitoring: request counts, latency and decision counts for each service, in the plain-text format Prometheus reads.

Nothing here stores customer data: only counters (how many requests, how many of each status, how long they took, how many
decisions of each tier). Counters live in memory, so they restart with the process, which is how Prometheus expects them.

    GET /metrics   counters and latency histogram (Shield: /shield/metrics when mounted in the demo deployment)
    GET /ready     200 only when the service can really do its job (model loaded / database reachable), otherwise 503

Use /health for "is the process up" and /ready for "should traffic be sent here".
"""
from __future__ import annotations

import threading
import time

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)


class Registry:
    def __init__(self, service: str):
        self.service = service
        self.lock = threading.Lock()
        self.requests: dict[tuple[str, str, str], int] = {}
        self.latency: dict[str, list[int]] = {}         # route -> bucket counts (+ overflow)
        self.latency_sum: dict[str, float] = {}
        self.events: dict[tuple[str, str], int] = {}    # (name, label) -> count, for decisions and similar
        self.started = time.time()

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        with self.lock:
            key = (method, route, str(status))
            self.requests[key] = self.requests.get(key, 0) + 1
            counts = self.latency.setdefault(route, [0] * (len(BUCKETS) + 1))
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    counts[i] += 1
                    break
            else:
                counts[-1] += 1
            self.latency_sum[route] = self.latency_sum.get(route, 0.0) + seconds

    def event(self, name: str, label: str) -> None:
        with self.lock:
            self.events[(name, label)] = self.events.get((name, label), 0) + 1

    def render(self) -> str:
        s = self.service
        out = [f"# TYPE {s}_requests_total counter"]
        with self.lock:
            for (m, r, st), n in sorted(self.requests.items()):
                out.append(f'{s}_requests_total{{method="{m}",route="{r}",status="{st}"}} {n}')
            out.append(f"# TYPE {s}_request_seconds histogram")
            for route, counts in sorted(self.latency.items()):
                cum = 0
                for b, c in zip(BUCKETS, counts):
                    cum += c
                    out.append(f'{s}_request_seconds_bucket{{route="{route}",le="{b}"}} {cum}')
                cum += counts[-1]
                out.append(f'{s}_request_seconds_bucket{{route="{route}",le="+Inf"}} {cum}')
                out.append(f'{s}_request_seconds_sum{{route="{route}"}} {self.latency_sum[route]:.6f}')
                out.append(f'{s}_request_seconds_count{{route="{route}"}} {cum}')
            names = sorted({n for n, _ in self.events})
            for name in names:
                out.append(f"# TYPE {s}_{name}_total counter")
                for (n, label), c in sorted(self.events.items()):
                    if n == name:
                        out.append(f'{s}_{name}_total{{label="{label}"}} {c}')
            out.append(f"# TYPE {s}_uptime_seconds gauge")
            out.append(f"{s}_uptime_seconds {time.time() - self.started:.0f}")
        return "\n".join(out) + "\n"


_registries: dict[str, Registry] = {}


def registry(service: str) -> Registry:
    return _registries.setdefault(service, Registry(service))


class Measured:
    """ASGI middleware: times every HTTP request and counts it by route template (not by id, so labels stay few)."""

    def __init__(self, app, service: str):
        self.app = app
        self.reg = registry(service)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        status = {"v": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["v"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            name = getattr(route, "path", None) or "unmatched"
            if name not in ("/metrics",):
                self.reg.observe(scope.get("method", "GET"), name, status["v"], time.perf_counter() - t0)
