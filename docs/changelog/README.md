# Changelog

Each milestone of the litegm implementation gets one record here, written when the
milestone is completed and verified.

## Index

| Milestone | Scope | Status | Record |
|-----------|-------|--------|--------|
| M1 | Environment (Python 3.15 via pixi), config schema, backend registry, ComfyUI adapter, task store | Completed | [M1](m1-foundation.md) |
| M2 | Workflow compilation and pre-submit validation for the turbo t2i/edit variants | Completed | [M2](m2-workflow.md) |
| M3 | OpenAI-compatible images API, auth, error mapping, models/health | Completed | [M3](m3-api.md) |
| M4 | Admin frontend (history, status, details, artifacts) | Completed | [M4](m4-admin-ui.md) |
| M5 | Integration verification on the real ComfyUI backend + OpenAI SDK check | Completed | [M5](m5-integration.md) |
| v1.5 | Additional image workflows (Qwen 2.1 base, MOSS, Z-Image ×2, zib-image, Qwen 2.1 edit) added via configuration; 10/10 aliases verified live (the Z-Image family was dropped from the shipped example during open-source preparation) | Completed | [v1.5](v1.5-workflows.md) |
| v1.6 | Unified image model (one alias for generate + edit, routed by supplied images) via `POST /v1/images`; admin task detail shows uploaded inputs | Completed | [v1.6](v1.6-unified-and-inputs.md) |
| v2-M6 | Pre-requisite fixes: `n` multi-image, quality→steps mapping, webp/jpeg output, per-backend queue with 429 backpressure | Completed | [M6](v2-m6-fixes.md) |
| v2-M7 | Video: OpenAI async `/v1/videos` protocol + H3 T2V/I2V/R2V | Completed | [M7](v2-m7-video.md) |
| v2-M8 | Audio: Music3 via task protocol (`/v1/audio/generations`) | Completed | [M8](v2-m8-audio.md) |
| v2.1 | Video task families: one family name routed by supplied input (t2v/i2v/r2v), with `requested_model` transparency; R2V single-reference fix | Completed | [v2.1](v2.1-video-families.md) |
| v3 | P0: storage governance, observability, config hot reload, progress fix (estimated; `/ws` → v4). P1: Docker, admin search/export/retry/delete/queue, media previews, light-theme UI, Playground, auth switch | Completed | [v3](v3-ops-and-ui.md) |
| v4-UI | Admin console redesign ("Darkroom"): dark designed theme, overview pulse dashboard, gallery/table history with bulk actions, print-style detail with lightbox and input/output comparison, constraint-driven Studio, system control room, command palette and shortcuts; backend thumbnails, list previews, gzip and asset caching | Completed | [v4](v4-ui-redesign.md) |
| v4-DOCS | Documentation set: user-facing README (features, quick start, deployment), developer guide (`docs/development.md`: structure, module index, extension guide), agent guide (`AGENTS.md`); usage/API docs updated for the containerised deployment and v4 admin API additions | Completed | [v4](v4-ui-redesign.md) |
| v4.1 | Container image and default pixi environment include `ffmpeg`/`ffprobe` (declared in `pyproject.toml`, re-locked), with a build-time binary check; video first-frame thumbnails work in the image | Completed | [v4.1](v4.1-ffmpeg.md) |
| v4.2 | Container start-up fix: entrypoint takes ownership of root-owned bind-mounted `./data`/`./config` and drops to UID 10001, resolving `unable to open database file` on ARM64 hosts; `linux-aarch64` added to the locked pixi platforms | Completed | [v4.2](v4.2-container-ownership.md) |
| v4.3 | Audio artifacts play inline in the admin task detail (player instead of the placeholder thumbnail); signed download URLs derive scheme/host from the request instead of the configured `public_base_url`, so any port/proxy works | Completed | [v4.3](v4.3-audio-preview-and-signed-urls.md) |
| v4.4 | Container build fix: the environment stage copies `README.md` and `LICENSE`, which hatchling requires when building the editable `litegm` wheel (`readme`/`license-files` in `pyproject.toml`), resolving `Readme file does not exist: README.md` | Completed | [v4.4](v4.4-docker-readme.md) |
| v4.5 | First-deployment notes: `docs/usage.md` §9 documents the `./data` ownership failure (`unable to open database file`, container restart loop) with the `chown -R 10001:10001` fix and a writability probe, plus the `.config/workflows/...` vs `config/workflows/...` template-path rule | Completed | [v4.5](v4.5-deployment-notes.md) |
| v4.6 | Agent discovery: `GET /llms.txt` generated from the live configuration (aliases, constraints, snippets, async protocol, errors), `GET /swagger-ui` (`/docs`) interactive docs and an enriched `GET /openapi.json`; admin console entry points to open the docs or copy the agent link | Completed | [v4.6](v4.6-agent-discovery.md) |
