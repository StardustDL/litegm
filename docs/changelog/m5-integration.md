# M5 — Integration verification

Date: 2026-10-23
Status: completed

## Scope

Verify every configured alias end to end against the real ComfyUI instance, and
verify that the official OpenAI SDK can drive the gateway unmodified.

## Results

| Check | Result |
|-------|--------|
| `litegm check` (schema validation of all aliases against live `/object_info`) | 4/4 ok |
| `test_health_reports_backend` | pass (real ComfyUI backend online) |
| `test_models_lists_turbo_aliases` | pass |
| `test_requires_api_key` (401 `invalid_api_key`) | pass |
| `test_generate_image` — real 768×768 PNG via `/v1/images/generations` | pass |
| `test_edit_image` — real edit via `/v1/images/edits` (upload → wire slots → submit) | pass |
| OpenAI SDK `client.images.generate(...)` | pass (768×768 PNG) |
| OpenAI SDK `client.images.edit(...)` | pass |
| OpenAI SDK wrong key → `openai.AuthenticationError` 401 | pass |
| Live gateway run: generation via HTTP in 6.1s; admin API shows task, artifact, events | pass |
| Unit suite (`-m "not integration"`) | 17 passed |

## Defects found and fixed during verification

1. **`BatchImagesNode` rejected the edit workflow** (`required_input_missing: image0`).
   `wire_images` wrote autogrow links into a nested `images` dict; ComfyUI expects
   flat `images.imageN` keys. Fixed; the edit path now submits successfully.
2. **FastAPI `on_event` deprecation** — replaced with a lifespan handler.
3. **Pillow `getdata()` deprecation** — pixel sampling rewritten using `getpixel`.

## Test infrastructure notes

* pytest's `tmpdir` plugin and `tempfile.mkdtemp` are both avoided: on Windows,
  mode-0700 directories do not inherit the workspace ACLs and can become unreadable
  to the process that opens them later. Tests use a `workdir` fixture with plain
  `mkdir` under `.test-work/`.
* Integration tests are marked `integration`; run with `pixi run -e dev test-integration`.

## Known gaps (carried forward to v2)

* `mask` / inpainting unsupported.
* Video (`/v1/videos` async protocol) and audio not yet exposed.
* Config is loaded at startup; hot reload not implemented.
