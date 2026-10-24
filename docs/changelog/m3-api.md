# M3 — OpenAI-compatible images API, auth and error mapping

Date: 2026-10-23
Status: completed

## Scope

Expose the gateway as an OpenAI-shaped image API, with the configured
username + master key auth, OpenAI error bodies, model listing and health.

## Endpoints

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/v1/images/generations` | Bearer master key | JSON body; returns `ImagesResponse` (`created`, `data[{b64_json\|url}]`, `size`, `quality`, `output_format`, `background`) |
| POST | `/v1/images/edits` | Bearer master key | multipart `image[]` (1–16) + `prompt`; `mask` rejected with `unsupported_parameter` |
| GET | `/v1/models` | Bearer master key | aliases + capabilities from configuration |
| GET | `/v1/health` | none | gateway + per-backend `/system_stats` and queue depth |
| GET | `/v1/tasks/{id}` | Bearer master key | non-standard retrieval after a 504 (`X-Litegm-Task-Id`) |
| GET | `/v1/files/{id}` | signed link | artifact download for `response_format=url` |

`stream=true` is accepted and emits OpenAI-shaped SSE
(`image_edit.completed` events); ComfyUI exposes no intermediate frames for these
workflows, so a single completion event is sent.

## What was built

| File | Purpose |
|------|---------|
| `src/litegm/api.py` | OpenAI-compatible routes, request models, response shaping, SSE |
| `src/litegm/auth.py` | Bearer check for the API, HTTP Basic → signed HttpOnly session for admin, constant-time comparisons |
| `src/litegm/app.py` | App factory, startup/shutdown, resume of interrupted tasks, error handlers |
| `src/litegm/admin.py` | Admin API (session-gated): task list/detail/cancel/retry, artifact raw, config view, health, SSE events |
| `src/litegm/storage.py` | Artifact save + image sanity check, signed URLs, retention purge |
| `src/litegm/cli.py` | `litegm serve` / `litegm check` |

## Error mapping

| Condition | Status | `code` |
|-----------|--------|--------|
| missing/invalid key | 401 | `invalid_api_key` |
| unknown model alias | 404 | `model_not_found` |
| bad parameter | 400 | `invalid_value` / `unsupported_parameter` |
| ComfyUI queue full | 429 | `rate_limit_exceeded` |
| node/execution error | 422 | `comfy_execution_error` / `node_errors` |
| backend unreachable | 503 | `backend_unavailable` |
| synchronous wait exceeded `sync_timeout_s` | 504 + `X-Litegm-Task-Id` | `sync_timeout` |

Errors are always rendered as `{"error": {type, code, message, param}}`.

## Synchronous semantics

Image requests block until the image is ready, matching OpenAI. The task is persisted
before the wait, so a timeout still leaves a retrievable task, and the admin UI shows
the same task. Fallback chains configured per alias are tried when a variant fails
before producing output.

## Verification

* `test_health_reports_backend`, `test_models_lists_turbo_aliases`,
  `test_requires_api_key` and `test_generate_image` pass against the live backend
  (real 768×768 PNG returned as `b64_json`).
* `test_edit_image` initially failed: `BatchImagesNode` requires flat `images.imageN`
  keys, while `wire_images` wrote a nested `images` dict. Fixed in `workflow.py`
  (autogrow links are now written as flat keys, matching the templates).
