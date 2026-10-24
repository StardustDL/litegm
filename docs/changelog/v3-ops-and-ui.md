# v3 — Operations, deployment and admin UI overhaul

Date: 2026-10-24
Status: completed and verified live (WS step progress deferred to v4)

## Scope

v3 = P0 (stability/operations) + P1 (deployment, admin efficiency, three frontend
requirements) from `docs/v3-plan.md`. Per the project decision, real step-level
progress via ComfyUI `/ws` is deferred to **v4**; v3 ships an estimated progress
model instead (see "Progress semantics").

## P0 — storage governance, observability, hot reload

### Storage governance

* `storage.max_bytes`: hard disk budget; when exceeded, the oldest artifacts and
  uploaded inputs are evicted (LRU) until usage fits.
* Tiered retention: `storage.artifact_ttl_days` for successful tasks,
  `storage.failed_retention_days` (default 2× TTL) for failed/cancelled/timed-out
  tasks so they stay available for investigation.
* Background sweep (`storage.sweep_interval_s`), manual sweep via
  `POST /admin/api/storage/sweep` and the "立即清理存储" button.
* `DELETE /admin/api/tasks/{id}`: hard-deletes artifacts and uploaded inputs,
  soft-deletes the task record (audit trail kept), cancels a running task first.
  Fixes N4 and N6 (failed-task inputs no longer accumulate).

### Observability

* Structured request log: one JSON line per request with `request_id`, method,
  path, status, `duration_ms` and `task_id`.
* `GET /metrics` in Prometheus text format (self-implemented, no new dependency):
  request counts/durations, task counts/durations by type and status, current
  tasks by status, backend queue depth, backend up, storage bytes.
* `GET /health/live` (process alive) and `GET /health/ready` (backend reachable,
  store usable) separated.
* `/admin/api/health` now reports `uptime_s` from a monotonic clock (the previous
  wall-clock arithmetic produced ~1.8e9 seconds on Windows, overflowing the UI)
  and exposes `auth_enabled`.

### Config hot reload

* `POST /admin/api/config/reload`: re-reads the config, validates it against the
  backends, and rolls back on failure. Only `tasks`/`routing`/`backends` are
  reloadable; changes to `server`/`auth`/`storage` are reported in
  `restart_required`. In-flight tasks keep the config snapshot they were
  submitted with.

## P1 — deployment, admin UI, frontend

### Docker

* Multi-stage image: Node stage builds the admin UI; runtime stage is
  `ghcr.io/prefix-dev/pixi:0.83.0` and installs the environment from
  `pixi.lock` (Python 3.15, identical to local). Runs as UID 10001, with a
  writable pixi/uv cache (`PIXI_CACHE_DIR`/`RATTLER_CACHE_DIR`/`UV_CACHE_DIR`
  under `/app/.pixi-cache`) so `pixi run` works without root.
* `docker-compose.yml` mounts `config/` and `data/`, reads
  `LITEGM_MASTER_KEY` from the environment, and defines a `/health/live`
  healthcheck.
* Verified live: image builds, container starts, reports `healthy`, serves
  `/health/live`, `/health/ready`, `/v1/models`, `/metrics` and the admin API,
  and generated a real 512×512 image through `/v1/images/generations`.

### Admin API

* `GET /admin/api/tasks`: prompt/task-id keyword `search`, plus status/type/
  model/backend/time filters.
* `GET /admin/api/tasks/export`: CSV/JSON export honouring the same filters.
* `POST /admin/api/tasks/{id}/retry`: re-run with identical parameters,
  re-uploading the original input images.
* `DELETE /admin/api/tasks/{id}`: see storage governance above.
* Queue visibility via `/admin/api/health` (per-backend running/waiting/
  concurrency/queue_max) shown on the System page.

### Frontend

* Light theme with a left navigation and main content area, responsive layout.
* Task history: search, filters, CSV/JSON export, delete.
* Task detail: uploaded inputs shown inline; artifacts previewed inline —
  images as `<img>`, video as `<video controls>`, audio as `<audio controls>` —
  with "下载原文件" as the secondary action instead of auto-download.
* Playground: submit tasks from the UI with a form generated per task type
  (image generate/edit, video, audio), reference-image upload, live progress and
  inline result previews.
* System page: backend health, queue, storage usage/cleanup, config hot reload,
  model routing table.
* Views are addressable via the URL hash (`#playground`, `#system`).

### Auth switch (new, not in the original plan)

* `auth.enabled` (default `true`) and `LITEGM_AUTH_DISABLED=1` disable both API
  Bearer checks and admin session checks. Intended for local development and
  screenshots; `/admin/api/me` reports `auth_enabled` so the UI skips the login
  screen. Do not disable on shared deployments.

## Progress semantics (replacing WS for v3)

ComfyUI's `/queue` exposes no step-level progress. v3 therefore:

* keeps the stage transitions real (`queued` → `submitting` → `running` →
  `downloading` → `completed`);
* estimates in-flight progress from elapsed time inside the generating stage,
  bounded to 20–88% (budget `ESTIMATE_FULL_S` in `observability.py`), never
  decreasing;
* keeps the progress reached on failure/cancellation (fixes the earlier
  regression to 5/10);
* sets 90–100% only from real downloading/completion events.

The `ComfyClient.listen_progress` WebSocket helper is retained for v4.

## Verification

| Check | Result |
|-------|--------|
| Unit tests (`pytest -m "not integration"`) | 58 passed |
| Integration tests (real ComfyUI) | 60 passed earlier in the milestone |
| `/metrics`, `/health/live`, `/health/ready` | 200 with expected payloads |
| Hot reload endpoint | validated, reports `restart_required` |
| Storage sweep / disk budget | covered by tests (`test_storage.py`) |
| Docker image build + run | builds; container `healthy`; real image generated |
| Admin UI (Edge headless via CDP) | tasks / detail / playground / system render with live data |
| Media previews | image, video (`<video>`), audio (`<audio>`) served with correct MIME |

## Known limitations carried into v4

* No true step-level progress (`/ws` deferred).
* `n>1` still runs variants serially.
* No `partial_image` events for `stream=true` image requests (ComfyUI emits no
  intermediate frames).
* Mask / img2img / upscale, multi-backend scheduling and prompt templates remain
  v4 items.
