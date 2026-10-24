# M4 — Admin frontend

Date: 2026-10-23
Status: completed

## Scope

A web UI to inspect task history and status, view task details (including the exact
workflow that was submitted), preview/download artifacts, and see backend health.

## What was built

| File | Purpose |
|------|---------|
| `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, Tailwind/PostCSS config | React 19 + TypeScript + Vite + Tailwind build, `base: /admin/` |
| `web/src/api.ts` | Admin API client (cookie session, SSE subscription) |
| `web/src/App.tsx` | Login (username + master key), task list with filters and live refresh, task detail (request, attempts, workflow JSON, artifacts, events, cancel/retry), backend health, read-only config view |
| `scripts/screenshot.py` | Headless Edge screenshot helper used for visual verification |

The built assets are served by the gateway at the configured `server.admin_path`
(`/admin`), with `LITEGM_WEB_DIR` overriding the directory.

## Admin API (session-gated)

* `POST /admin/api/login` — Basic auth → signed HttpOnly session cookie
* `GET /admin/api/tasks` — filters: status, task_type, model_alias, backend_id, time range
* `GET /admin/api/tasks/{id}` — full detail incl. workflow snapshot and event trail
* `POST /admin/api/tasks/{id}/cancel` and `/retry` (retry reuses retained input images)
* `GET /admin/api/artifacts/{id}/raw` — inline preview
* `GET /admin/api/health`, `GET /admin/api/config` (read-only)
* `GET /admin/api/events` — SSE stream of task state changes

## Verification

* `npm install` + `npm run build` succeed (tsc + vite, no type errors).
* Gateway serves `/admin/` (HTML) and the hashed JS bundle (HTTP 200).
* Admin API verified live against a real generation: login → `/me` → task list →
  task detail with artifact metadata (`768×768`, `suspicious=false`) and event trail
  (`created`, `submitted`, `comfy_text`, `status:succeeded`, `artifacts`).
* UI renders (screenshot via headless Edge).

## Notes

* npm's default cache lives outside the workspace; builds use
  `npm_config_cache=<workspace>/.cache/npm` so installs are reproducible in
  sandboxed/CI environments.
* Node.js is provided by the pixi `web` environment (`nodejs >= 22`).
* Config editing is intentionally out of scope for v1 (read-only view).
