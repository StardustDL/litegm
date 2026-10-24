"""Observability: request-scoped structured logging and a Prometheus-style /metrics.

Deliberately dependency-free: the metrics are rendered in the Prometheus text
exposition format by hand, and request logging emits one JSON line per request.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("litegm.access")

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
task_id_var: ContextVar[str] = ContextVar("task_id", default="-")

ESTIMATE_FULL_S = 120.0
"""Time after which the estimated in-flight progress reaches its cap.

ComfyUI's queue gives no step-level progress and the ``/ws`` listener is
deferred to v4, so the engine interpolates progress from elapsed time towards
this budget (see ``Engine._advance_estimated_progress``)."""


@dataclass
class Metrics:
    requests_total: dict[tuple[str, str, int], int] = field(default_factory=lambda: defaultdict(int))
    request_duration_sum: dict[tuple[str, str], float] = field(default_factory=lambda: defaultdict(float))
    request_duration_count: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    task_submitted: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    task_finished: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    task_duration_sum: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    task_duration_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def observe_request(self, method: str, path: str, status: int, duration: float) -> None:
        # Collapse path parameters so cardinality stays bounded.
        route = _route_label(path)
        self.requests_total[(method, route, status)] += 1
        self.request_duration_sum[(method, route)] += duration
        self.request_duration_count[(method, route)] += 1

    def observe_task(self, task_type: str, status: str, duration: float) -> None:
        self.task_finished[(task_type, status)] += 1
        self.task_duration_sum[task_type] += duration
        self.task_duration_count[task_type] += 1


def _route_label(path: str) -> str:
    """Normalise dynamic path segments (ids) to keep metric cardinality low."""
    parts = []
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        if len(seg) > 20 or seg.startswith(("task_", "art_")):
            parts.append("{id}")
        else:
            parts.append(seg)
    return "/" + "/".join(parts)


METRICS = Metrics()


class RequestLoggingMiddleware:
    """Assigns a request id and emits a structured access log line.

    Implemented as a plain ASGI middleware rather than ``BaseHTTPMiddleware`` so
    downstream responses keep their single-message body: Starlette's gzip layer
    gates on that body's size, and a BaseHTTPMiddleware would always re-emit it
    as ``more_body=True`` (which bypasses the gate and compresses tiny JSON).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        rid = headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500

        async def send_with_log(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                raw = message.get("headers") or []
                raw.append((b"x-request-id", rid.encode("latin-1")))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_with_log)
        finally:
            duration = time.perf_counter() - start
            path = scope.get("path", "")
            METRICS.observe_request(scope.get("method", "-"), path, status, duration)
            if not path.startswith(("/admin/api/events", "/metrics")):
                client = scope.get("client")
                log.info(json.dumps({
                    "ts": round(time.time(), 3),
                    "request_id": rid,
                    "method": scope.get("method"),
                    "path": _route_label(path),
                    "status": status,
                    "duration_ms": round(duration * 1000, 1),
                    "client": client[0] if client else None,
                }, ensure_ascii=False))
            request_id_var.reset(token)


router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    state = request.app.state
    lines: list[str] = []

    def emit(name: str, labels: dict[str, Any], value: Any) -> None:
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")

    lines.append("# HELP litegm_http_requests_total HTTP requests by method, route and status")
    lines.append("# TYPE litegm_http_requests_total counter")
    for (method, route, status), count in sorted(METRICS.requests_total.items()):
        emit("litegm_http_requests_total", {"method": method, "route": route, "status": status}, count)

    lines.append("# HELP litegm_http_request_duration_seconds_sum Total request time")
    lines.append("# TYPE litegm_http_request_duration_seconds_sum counter")
    for (method, route), total in sorted(METRICS.request_duration_sum.items()):
        emit("litegm_http_request_duration_seconds_sum", {"method": method, "route": route}, round(total, 4))
        emit("litegm_http_request_duration_seconds_count", {"method": method, "route": route},
             METRICS.request_duration_count[(method, route)])

    lines.append("# HELP litegm_tasks_finished_total Finished generation tasks by type and status")
    lines.append("# TYPE litegm_tasks_finished_total counter")
    for (task_type, status), count in sorted(METRICS.task_finished.items()):
        emit("litegm_tasks_finished_total", {"task_type": task_type, "status": status}, count)

    lines.append("# HELP litegm_task_duration_seconds_sum Total task execution time")
    lines.append("# TYPE litegm_task_duration_seconds_sum counter")
    for task_type, total in sorted(METRICS.task_duration_sum.items()):
        emit("litegm_task_duration_seconds_sum", {"task_type": task_type}, round(total, 3))
        emit("litegm_task_duration_seconds_count", {"task_type": task_type},
             METRICS.task_duration_count[task_type])

    counts = state.tasks.counts_by_status()
    lines.append("# HELP litegm_tasks_by_status Current tasks by status")
    lines.append("# TYPE litegm_tasks_by_status gauge")
    for status, count in sorted(counts.items()):
        emit("litegm_tasks_by_status", {"status": status}, count)

    lines.append("# HELP litegm_backend_queue_tasks Backend queue depth")
    lines.append("# TYPE litegm_backend_queue_tasks gauge")
    for backend_id, q in state.engine.queue_stats().items():
        emit("litegm_backend_queue_tasks", {"backend": backend_id, "state": "running"}, q["running"])
        emit("litegm_backend_queue_tasks", {"backend": backend_id, "state": "waiting"}, q["waiting"])

    lines.append("# HELP litegm_backend_up Whether a backend responded to health checks")
    lines.append("# TYPE litegm_backend_up gauge")
    try:
        health_map = await state.backends.health_all()
        for backend_id, h in health_map.items():
            emit("litegm_backend_up", {"backend": backend_id}, 1 if h.get("healthy") else 0)
    except Exception:  # noqa: BLE001 - metrics must always render
        pass

    usage = state.artifacts.usage()
    lines.append("# HELP litegm_storage_bytes Bytes used by artifacts and uploads")
    lines.append("# TYPE litegm_storage_bytes gauge")
    emit("litegm_storage_bytes", {"kind": "artifacts"}, usage["artifacts_bytes"])
    emit("litegm_storage_bytes", {"kind": "uploads"}, usage["uploads_bytes"])

    lines.append("# HELP litegm_info Static build information")
    lines.append("# TYPE litegm_info gauge")
    emit("litegm_info", {"version": state.version}, 1)

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/health/live", include_in_schema=False)
async def health_live() -> dict[str, Any]:
    """Liveness: the process is up and the event loop responds."""
    return {"status": "alive"}


@router.get("/health/ready", include_in_schema=False)
async def health_ready(request: Request) -> Response:
    """Readiness: at least one backend answers and the task store is writable."""
    state = request.app.state
    try:
        health_map = await state.backends.health_all()
    except Exception:  # noqa: BLE001
        health_map = {}
    backends_ok = any(h.get("healthy") for h in health_map.values())
    try:
        state.tasks.counts_by_status()
        store_ok = True
    except Exception:  # noqa: BLE001
        store_ok = False
    ready = backends_ok and store_ok
    payload = {"status": "ready" if ready else "not_ready",
               "backends_healthy": backends_ok, "store_ok": store_ok}
    return PlainTextResponse(json.dumps(payload), status_code=200 if ready else 503,
                             media_type="application/json")
