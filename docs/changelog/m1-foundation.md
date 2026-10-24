# M1 — Foundation

Date: 2026-10-23
Status: completed

## Scope

Environment and the infrastructure every later milestone depends on:

* Python 3.15 pixi environment (per the design decision).
* Configuration schema and loader — no ComfyUI specifics in code.
* Backend registry and an async ComfyUI API client.
* Task store (SQLite) for tasks, artifacts, events and retained input images.

## What was built

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata, pixi workspace/features/environments, `requires-python >= 3.15` |
| `src/litegm/errors.py` | Typed errors carrying HTTP status + OpenAI error `type`/`code` |
| `src/litegm/config.py` | Pydantic config schema (server/auth/storage/backends/tasks/models), secret resolution via `env:NAME`, fail-fast template validation |
| `src/litegm/comfy.py` | Async client for `/system_stats`, `/object_info`, `/prompt`, `/history/{id}`, `/view`, `/upload/image`, `/interrupt`, `/queue`; output enumeration covering `images`/`audio` and SaveVideo's `images(animated)` + `subfolder` |
| `src/litegm/backends.py` | One client per configured backend, health aggregation |
| `src/litegm/store.py` | SQLite (WAL) tables `tasks`, `artifacts`, `events`, `input_images`; task lifecycle helpers, retention purge, resume support |

## Environment verification

* conda-forge ships `python 3.15.1` for the locked platforms; solved and installed
  successfully on the development platform.
* Verified imports in the `dev` environment: fastapi 0.161.1, uvicorn, httpx 0.28.1,
  pydantic 2.14.1, sqlalchemy 2.1.6, pyyaml 6.0.3, python-multipart, pillow 13.0.0,
  pytest 9.1.1, pytest-asyncio 1.4.0, openai 3.37.0.
* Backend reachability: `GET /system_stats` on the configured instance returned a
  ComfyUI server (0.41.x) with its Python/torch versions, confirming the adapter
  talks to a real deployment.

## Notes and decisions taken during implementation

* **Dependencies come from conda-forge, not PyPI.** `[project].dependencies` was left
  empty and the runtime set lives in `[tool.pixi.dependencies]`; dev-only tooling
  (pytest, pytest-asyncio, openai) is in a separate pixi feature. This avoids the
  conda/PyPI file-overwrite warnings and keeps the lock file single-source.
* **Relative paths in the config resolve against an explicit base directory**
  (`--base-dir`, `LITEGM_BASE_DIR`, default cwd) rather than the config file's folder,
  so `config/workflows/...` keeps working from the project root.
* **`mark_interrupted()` + `active_tasks()`** are implemented in the store so a
  restarted process can re-attach to prompts already submitted to ComfyUI.
* **`input_images`** retains uploaded images on disk, enabling faithful retry of edit
  tasks from the admin UI.
* **Local environment quirk:** pytest's `tmpdir` plugin re-creates its base directory
  with `rm_rf` + `mkdir`, which can leave it unreadable under inherited Windows ACLs.
  Tests therefore use a `workdir` fixture and the plugin is disabled in
  `pyproject.toml`.

## Verification performed

* `pixi reinstall -e dev` → `import PIL, sqlalchemy` succeeds.
* Config load + template existence check passes.
* `litegm check` reaches the live backend (validation itself is M2).

## Deviations

None from the approved design. The Python 3.15 risk called out in the design did not
materialize: all required dependencies resolved for 3.15.1.
