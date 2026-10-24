"""Discovery documents for agents and developers.

Three surfaces let a caller who was only handed a URL bootstrap itself:

* ``GET /llms.txt``      — llmstxt.org-style Markdown generated from the *live*
  configuration: the aliases this deployment actually serves, their constraints,
  authentication, copy-paste requests and the async task protocol.
* ``GET /swagger-ui``    — interactive Swagger UI over the OpenAPI document.
* ``GET /openapi.json``  — the OpenAPI document enriched with servers, a bearer
  security scheme and per-endpoint guidance/examples.

None of these need a bearer token: they describe the API, they do not act on it.
The master key itself never appears in them.

Everything is derived from :class:`litegm.config.Config`, so a hot reload or a
restart with a different config immediately changes what agents are told. When a
protocol endpoint is added, extend :func:`llms_txt` alongside ``docs/api.md``.
"""

from __future__ import annotations

import json
from typing import Any

# Error codes documented in ``docs/api.md``; kept here so llms.txt and the
# OpenAPI description stay in one place.
ERROR_TABLE: list[tuple[int, str, str]] = [
    (400, "invalid_request / invalid_value", "Malformed body or an out-of-range value."),
    (400, "unsupported_parameter", "A parameter the model does not support (e.g. mask)."),
    (401, "invalid_api_key", "Missing or wrong `Authorization: Bearer <master_key>`."),
    (404, "model_not_found", "The alias is not configured for that endpoint/task."),
    (404, "not_found / task_not_found / artifact_not_found", "Unknown id, or a deleted task."),
    (404, "invalid_signature", "Signed download link expired or tampered with."),
    (409, "task_cancelled", "The task was cancelled while the request was waiting."),
    (422, "generation_failed", "The backend executed the workflow but produced no usable output."),
    (422, "comfy_execution_error", "ComfyUI reported an execution error; see `message`."),
    (429, "rate_limit_exceeded", "Backend queue is full; retry after a delay."),
    (503, "backend_unavailable", "No reachable ComfyUI backend for this model."),
    (504, "sync_timeout", "Synchronous image call exceeded `server.sync_timeout_s`; "
                          "the task keeps running — poll `GET /v1/tasks/{id}`."),
]

IMAGE_ENDPOINTS = ("/v1/images", "/v1/images/generations", "/v1/images/edits")


def _base_url(state: Any, base_url: str | None) -> str:
    if base_url:
        return base_url.rstrip("/")
    return str(state.config.server.public_base_url).rstrip("/")


def _fmt_num(value: float) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def _constraint_lines(variant: Any) -> list[str]:
    """Human-readable capability summary for one configured alias."""
    c = variant.constraints
    bits: list[str] = []
    bits.append(f"size_policy={c.size_policy}, default_size={c.default_size}, "
                f"edges {c.min_edge}-{c.max_edge} step {c.size_step}")
    if c.max_pixels:
        bits.append(f"max_pixels={c.max_pixels}")
    bits.append(f"n_max={c.n_max}")
    bits.append(f"output_formats={','.join(c.output_formats)}")
    if c.duration_max is not None:
        bits.append(
            f"seconds {_fmt_num(c.duration_min or 0)}-{_fmt_num(c.duration_max)}"
            f" (default {_fmt_num(c.duration_default or 0)}, "
            f"step {_fmt_num(c.duration_step or 0)})"
        )
    if variant.image_slots is not None:
        ref = variant.image_slots.reference
        max_images = 16 if ref is not None and ref.extra_node_base is not None else (2 if ref else 1)
        bits.append(f"accepts up to {max_images} input image(s)")
    if variant.mask_policy == "supported":
        bits.append("mask supported")
    return bits


def _model_sections(state: Any) -> list[str]:
    cfg = state.config
    out: list[str] = ["## Models (as configured on this deployment)", ""]
    out.append("Model aliases are deployment-specific. **Do not guess them**: call "
               "`GET /v1/models` first and use the `id` values it returns together with "
               "their `capabilities`.")
    out.append("")

    unified = {u.alias: u for u in cfg.routing.unified_image_models}
    for task_name, task in cfg.tasks.items():
        for m in task.models:
            u = unified.get(m.alias)
            if u is not None and task_name == u.edit_task:
                continue
            out.append(f"### `{m.alias}`")
            out.append("")
            if u is not None:
                out.append(f"- task: `{u.generate_task}` + `{u.edit_task}` (unified: images "
                           f"present -> edit, no images -> generate)")
                out.append(f"- endpoints: {', '.join(f'`{e}`' for e in IMAGE_ENDPOINTS)}")
            else:
                out.append(f"- task: `{task_name}`")
            out.extend(f"- {line}" for line in _constraint_lines(m))
            if m.fallbacks:
                out.append(f"- fallbacks: {', '.join(f'`{f}`' for f in m.fallbacks)}")
            out.append("")

    families = cfg.routing.video_families
    if families:
        out.append("### Video families")
        out.append("")
        out.append("A family name may be passed as `model` to `POST /v1/videos`; the gateway "
                   "routes by the inputs you actually send and echoes the variant it ran in "
                   "`model` (`requested_model` keeps your value).")
        out.append("")
        for f in families:
            variants = [("no images", f.text_to_video), ("input_reference/first_frame", f.image_to_video),
                        ("reference_images[]", f.reference_to_video)]
            listed = [f"`{a}` ({label})" for label, a in variants if a]
            out.append(f"- `{f.family}` -> {', '.join(listed)}")
        out.append("")
    return out


def llms_txt(state: Any, *, base_url: str | None = None) -> str:
    """Render ``/llms.txt`` for this deployment.

    The document is Markdown in the llmstxt.org layout (H1, blockquote summary,
    ``##`` sections of link lists) and embeds copy-paste snippets, so an agent can
    go from the URL to a first successful request without other docs.
    """
    cfg = state.config
    base = _base_url(state, base_url)
    version = getattr(state, "version", "0.1.0")
    auth_enabled = bool(cfg.auth.enabled)

    lines: list[str] = []
    add = lines.append

    add("# litegm")
    add("")
    add("> OpenAI-compatible media generation gateway in front of ComfyUI: image "
        "generation/editing, asynchronous video and audio jobs, plus an admin console. "
        "Model aliases, sizes and durations are declared by this deployment's "
        "configuration — read `GET /v1/models` before calling anything.")
    add("")
    add(f"litegm {version} · API base `{base}/v1` · interactive docs `{base}/swagger-ui`.")
    add("")
    add("This file is generated from the live configuration, so the aliases and limits "
        "below are exactly what this instance accepts. Anything not listed is rejected "
        "with `404 model_not_found`.")
    add("")

    add("## Start here")
    add("")
    add(f"- [Interactive API reference]({base}/swagger-ui): Swagger UI for every endpoint; "
        "click *Authorize* and paste the master key to try calls in the browser.")
    add(f"- [OpenAPI document]({base}/openapi.json): machine-readable schema (OpenAPI 3) "
        "for generating clients or tool definitions.")
    add(f"- [Model catalog]({base}/v1/models): the aliases and capabilities of this "
        "deployment. Call this first.")
    add(f"- [Gateway health]({base}/v1/health): version, task counts, backend and queue state.")
    add(f"- [This file]({base}/llms.txt): regenerate/share this URL with any agent.")
    add("")

    add("## Authentication")
    add("")
    if auth_enabled:
        add("Send the master key as a bearer token on every `/v1/*` request:")
        add("")
        add("```http")
        add(f"Authorization: Bearer <master_key>")
        add("```")
        add("")
        add("The same key logs into the admin console (HTTP Basic, any username, key as "
            "password) and is the `api_key` for the OpenAI SDK. It is never included in "
            "this document.")
    else:
        add("Authentication is currently disabled on this deployment "
            "(`auth.enabled: false`): `/v1/*` accepts requests without a token. Still send "
            "`Authorization: Bearer <master_key>` so your code works when it is enabled.")
    add("")

    add("## Quick start")
    add("")
    add("Text-to-image with curl (replace `<master_key>` and the model alias):")
    add("")
    add("```bash")
    add(f"curl -s {base}/v1/images/generations \\")
    add('  -H "Authorization: Bearer <master_key>" \\')
    add('  -H "Content-Type: application/json" \\')
    add("  -d '{\"model\":\"<alias from /v1/models>\",\"prompt\":\"a red fox in autumn grass\","
        "\"size\":\"1024x1024\",\"n\":1}'")
    add("```")
    add("")
    add("Image editing (multipart, one or more `image` files; refer to them as `<image1>`, "
        "`<image2>` … in the prompt):")
    add("")
    add("```bash")
    add(f"curl -s {base}/v1/images/edits \\")
    add('  -H "Authorization: Bearer <master_key>" \\')
    add('  -F "model=<edit alias>" -F "prompt=replace <image1> background with a sunset sky" \\')
    add('  -F "image=@person.png"')
    add("```")
    add("")
    add("With the official OpenAI SDK, point `base_url` at the gateway:")
    add("")
    add("```python")
    add("from openai import OpenAI")
    add("")
    add(f'client = OpenAI(api_key="<master_key>", base_url="{base}/v1")')
    add("")
    add("models = client.models.list()          # aliases + capabilities of this deployment")
    add('r = client.images.generate(model="<alias>", prompt="a red fox in autumn grass")')
    add('print(r.data[0].b64_json[:32])')
    add("```")
    add("")
    add("```js")
    add('import OpenAI from "openai";')
    add(f'const client = new OpenAI({{ apiKey: "<master_key>", baseURL: "{base}/v1" }});')
    add('const r = await client.images.generate({ model: "<alias>", prompt: "a red fox" });')
    add("```")
    add("")

    lines.extend(_model_sections(state))
    add("")

    add("## Image API (synchronous)")
    add("")
    add(f"- [POST {base}/v1/images/generations]({base}/v1/images/generations): JSON body "
        "(`prompt`, `model`, `n`, `size`, `quality`, `output_format`, `background`, "
        "`response_format`, `seed`, `stream`). Returns an OpenAI `ImagesResponse`.")
    add(f"- [POST {base}/v1/images]({base}/v1/images): one endpoint for both — JSON body "
        "generates, multipart with `image` files edits. Unified aliases (see Models) route "
        "automatically.")
    add(f"- [POST {base}/v1/images/edits]({base}/v1/images/edits): multipart edit; `mask` is "
        "rejected when the model declares `mask_policy: unsupported`.")
    add("")
    add("`size` snaps to the model's step/limits; `n` above `n_max` is rejected. "
        "`response_format=url` returns signed links valid for "
        f"`{cfg.storage.download_url_ttl_s}` s. A call that exceeds "
        f"`server.sync_timeout_s` ({_fmt_num(cfg.server.sync_timeout_s)} s) returns 504 with "
        "header `X-Litegm-Task-Id`; the task keeps running.")
    add("")

    add("## Video API (asynchronous)")
    add("")
    add(f"- [POST {base}/v1/videos]({base}/v1/videos): multipart (`prompt`, `model`, "
        "`seconds`, `size`, optional `input_reference`/`first_frame`, or repeated "
        "`reference_images`). Returns a video object with `status: queued`.")
    add(f"- [GET {base}/v1/videos/{{id}}]({base}/v1/videos/{{id}}): poll `status` "
        "(`queued`/`in_progress`/`completed`/`failed`), `progress` and `error`.")
    add(f"- [GET {base}/v1/videos/{{id}}/content]({base}/v1/videos/{{id}}/content): download "
        "the mp4 once `completed` (`variant=thumbnail` for a first-frame still).")
    add(f"- [GET {base}/v1/videos]({base}/v1/videos) and DELETE `{base}/v1/videos/{{id}}`: "
        "list and delete jobs.")
    add("")

    add("## Audio API (asynchronous extension)")
    add("")
    add(f"- [POST {base}/v1/audio/generations]({base}/v1/audio/generations): JSON or "
        "multipart with `input` (music description), `lyrics`, `seconds`, `model`, `seed`.")
    add(f"- [GET {base}/v1/audio/{{id}}]({base}/v1/audio/{{id}}): poll status/progress.")
    add(f"- [GET {base}/v1/audio/{{id}}/content]({base}/v1/audio/{{id}}/content): download FLAC.")
    add(f"- [GET {base}/v1/audio]({base}/v1/audio) and DELETE `{base}/v1/audio/{{id}}`: list "
        "and delete jobs.")
    add("")

    add("## Async tasks and polling")
    add("")
    add(f"- [GET {base}/v1/tasks/{{id}}]({base}/v1/tasks/{{id}}): retrieve any task created "
        "by an image call (after a 504), with `status`, `progress`, `error` and signed "
        "artifact `data[].url`.")
    add(f"- [GET {base}/v1/files/{{id}}]({base}/v1/files/{{id}}): signed artifact download; "
        "no bearer token required (the signature is the credential).")
    add("")
    add("Recommended loop for async jobs: submit -> poll every 2-5 s with backoff -> on "
        "`completed`, download `/content` -> on `failed`, read `error.code` (see Errors). "
        "Jobs are retained for "
        f"{cfg.storage.artifact_ttl_days} days and then swept.")
    add("")

    add("## Errors")
    add("")
    add("Failures use the OpenAI error envelope: "
        "`{\"error\": {\"type\", \"code\", \"message\", \"param\"}}`.")
    add("")
    for status, code, note in ERROR_TABLE:
        add(f"- `{status}` `{code}`: {note}")
    add("")
    add("Treat `429` and `503` as retryable with backoff; `400`/`404`/`422` mean the request "
        "needs changing (model name, size, duration, inputs).")
    add("")

    add("## Operational endpoints")
    add("")
    add(f"- [GET {base}/health/live]({base}/health/live): liveness (no auth).")
    add(f"- [GET {base}/health/ready]({base}/health/ready): readiness incl. backend check.")
    add(f"- [GET {base}/metrics]({base}/metrics): Prometheus text metrics (no auth).")
    add(f"- [Admin console]({base}{cfg.server.admin_path}/): task history, storage and config "
        "hot reload (browser login with the master key).")
    add(f"- [Admin API]({base}{cfg.server.admin_path}/api/tasks): session-cookie protected "
        "task list/detail/retry/delete used by the console.")
    add("")

    add("## Repository docs")
    add("")
    add("- [docs/api.md](https://github.com/StardustDL/litegm/blob/main/docs/api.md): full "
        "endpoint reference in Chinese.")
    add("- [docs/usage.md](https://github.com/StardustDL/litegm/blob/main/docs/usage.md): "
        "deployment and usage guide.")
    add("")
    add("## Optional")
    add("")
    add("- Configuration drives every alias: adding a model needs no code change.")
    add("- Progress for long jobs is estimated from stage timings, not ComfyUI step events.")
    add("")
    return "\n".join(lines)


def swagger_html(
    *,
    openapi_url: str = "/openapi.json",
    llms_url: str = "/llms.txt",
    title: str = "litegm API",
) -> str:
    """A self-contained Swagger UI page (assets from a public CDN).

    The page states where the OpenAPI document and the agent brief live, so it is
    still useful when the CDN is unreachable behind a restricted network.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
<style>
  body {{ margin: 0; background: #0b0e13; color: #e6e9ef;
         font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .litegm-bar {{ display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
                padding: .7rem 1rem; background: #12161d; border-bottom: 1px solid #1f2530; }}
  .litegm-bar a {{ color: #9ecbff; text-decoration: none; font-size: .82rem; }}
  .litegm-bar a:hover {{ text-decoration: underline; }}
  .litegm-bar .spacer {{ flex: 1; }}
  .litegm-note {{ font-size: .75rem; color: #8b93a3; }}
  #swagger-ui .topbar {{ display: none; }}
  .litegm-fallback {{ padding: 1rem 1.25rem; font-size: .8rem; color: #8b93a3; }}
</style>
</head>
<body>
<div class="litegm-bar">
  <strong>{title}</strong>
  <a href="{openapi_url}">openapi.json</a>
  <a href="{llms_url}">llms.txt (agent brief)</a>
  <a href="/v1/models">/v1/models</a>
  <span class="spacer"></span>
  <span class="litegm-note">Authorize with the master key to try calls in place.</span>
</div>
<div class="litegm-fallback">
  If the UI does not render, Swagger assets could not be loaded from the CDN; the API
  description is still available at <a href="{openapi_url}">{openapi_url}</a> and the agent
  brief at <a href="{llms_url}">{llms_url}</a>.
</div>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
<script>
  window.addEventListener("load", function () {{
    if (typeof SwaggerUIBundle === "undefined") return;
    SwaggerUIBundle({{
      url: "{openapi_url}",
      dom_id: "#swagger-ui",
      deepLinking: true,
      persistAuthorization: true,
      displayRequestDuration: true,
      tryItOutEnabled: true,
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      plugins: [SwaggerUIBundle.plugins.DownloadUrl],
      layout: "StandaloneLayout"
    }});
  }});
</script>
</body>
</html>
"""


# Per-endpoint guidance merged into the OpenAPI document. Keys are the paths
# FastAPI generates; unknown paths are left untouched.
_ENDPOINT_DOCS: dict[str, dict[str, Any]] = {
    "/v1/models": {
        "summary": "List model aliases and capabilities of this deployment",
        "description": (
            "Returns every alias configured on this gateway with its `capabilities` "
            "(task, accepted endpoints, size/duration limits, `accepts_images`, "
            "`max_images`, `n_max`, output formats). Call this before choosing a model; "
            "aliases are deployment-specific and are rejected with 404 when unknown."
        ),
        "tags": ["Discovery"],
    },
    "/v1/images/generations": {
        "summary": "Text-to-image generation (synchronous, OpenAI-compatible)",
        "description": (
            "JSON body. `model` must be an alias from `GET /v1/models` whose task is "
            "`image.generate` or that is declared unified. `size` is snapped to the "
            "model's step and edge limits; `n` is capped by `n_max`. If the call exceeds "
            "`server.sync_timeout_s` the gateway answers 504 with header "
            "`X-Litegm-Task-Id`; poll `GET /v1/tasks/{task_id}` for the result. "
            "`response_format=url` returns signed links instead of base64."
        ),
        "tags": ["Image"],
        "example": {
            "model": "qwen-image-2.1-turbo",
            "prompt": "a red fox sitting in golden autumn grass, soft morning light",
            "size": "1024x1024",
            "n": 1,
            "output_format": "png",
            "response_format": "b64_json",
        },
    },
    "/v1/images": {
        "summary": "Unified image endpoint: JSON generates, multipart with images edits",
        "description": (
            "Send a JSON body like `/v1/images/generations` for text-to-image, or "
            "`multipart/form-data` with one or more `image` files for editing. Aliases "
            "declared under `routing.unified_image_models` route automatically: images "
            "present -> edit variant, no images -> generate variant."
        ),
        "tags": ["Image"],
        "example": {
            "model": "qwen-image-2.1-turbo",
            "prompt": "a red fox sitting in golden autumn grass",
            "size": "1024x1024",
        },
    },
    "/v1/images/edits": {
        "summary": "Image editing / image-to-image (multipart)",
        "description": (
            "Upload 1..N `image` files and a `prompt`. Reference uploaded images as "
            "`<image1>`, `<image2>` … in the prompt. The output canvas follows the input "
            "image; `size` is advisory. `mask` is rejected unless the model declares "
            "`mask_policy: supported`."
        ),
        "tags": ["Image"],
        "example": {
            "model": "qwen-image-2.1-turbo-edit",
            "prompt": "replace the background of <image1> with a sunset sky, keep the subject",
        },
    },
    "/v1/videos": {
        "summary": "Create a video job (asynchronous)",
        "description": (
            "multipart: `prompt`, `model`, `seconds`, `size`, and optionally "
            "`input_reference`/`first_frame` (image-to-video) or repeated "
            "`reference_images` (reference-to-video). A video family name may be used as "
            "`model`; routing follows the supplied inputs and the response's `model` "
            "names the variant actually executed. Poll `GET /v1/videos/{video_id}`."
        ),
        "tags": ["Video"],
        "example": {
            "model": "minimax-h3",
            "prompt": "a paper boat drifting down a rainy street at dusk",
            "seconds": "2",
            "size": "1280x720",
        },
    },
    "/v1/audio/generations": {
        "summary": "Create a music/audio job (asynchronous extension)",
        "description": (
            "JSON or multipart with `input` (music description), `lyrics`, `seconds`, "
            "`model`, `seed`. Duration must fall inside the model's configured range. "
            "Poll `GET /v1/audio/{audio_id}` and download `/content` when completed."
        ),
        "tags": ["Audio"],
        "example": {
            "model": "minimax-music3",
            "input": "warm lo-fi hip hop with vinyl crackle and soft piano",
            "lyrics": "[verse] city lights blur into rain",
            "seconds": 30,
        },
    },
    "/v1/tasks/{task_id}": {
        "summary": "Retrieve a task created by a synchronous call that timed out",
        "description": (
            "Non-standard extension. When an image request exceeds "
            "`server.sync_timeout_s` the gateway returns 504 with `X-Litegm-Task-Id`; the "
            "task keeps running and can be fetched here until it succeeds or fails. "
            "`data[].url` contains signed download links."
        ),
        "tags": ["Tasks"],
    },
}


def _merge_endpoint_docs(doc: dict[str, Any]) -> None:
    paths = doc.get("paths") or {}
    for path, guidance in _ENDPOINT_DOCS.items():
        entry = paths.get(path)
        if not isinstance(entry, dict):
            continue
        for method, op in entry.items():
            if not isinstance(op, dict):
                continue
            op["summary"] = guidance["summary"]
            op["description"] = guidance["description"]
            tags = op.setdefault("tags", [])
            if guidance["tags"][0] not in tags:
                tags.insert(0, guidance["tags"][0])
            example = guidance.get("example")
            if example is not None:
                body = op.get("requestBody")
                if isinstance(body, dict):
                    content = body.get("content") or {}
                    for media in content.values():
                        if isinstance(media, dict):
                            media.setdefault("example", example)


def openapi_extras(app: Any, *, base_url: str | None = None) -> dict[str, Any]:
    """Build the served OpenAPI document.

    Starts from FastAPI's own schema, then adds server URLs, a bearer security
    scheme and per-endpoint guidance. Never raises: a schema generation failure
    falls back to a minimal document so ``/openapi.json`` and the Swagger UI keep
    working.
    """
    try:
        doc = app.openapi()
        if not isinstance(doc, dict):
            raise TypeError("openapi() did not return a mapping")
        doc = json.loads(json.dumps(doc))  # detach from FastAPI's cached object
    except Exception:  # noqa: BLE001 - discovery must never take the API down
        doc = {
            "openapi": "3.1.0",
            "info": {"title": "litegm", "version": "0.1.0"},
            "paths": {},
        }

    info = doc.setdefault("info", {})
    info.setdefault("title", "litegm")
    base = (base_url or "").rstrip("/")
    info["description"] = (
        "OpenAI-compatible media generation gateway for ComfyUI.\n\n"
        "1. Read the agent brief (Markdown, generated from this deployment's live "
        f"configuration): {base}/llms.txt\n"
        f"2. Call `GET /v1/models` for the aliases and limits this instance serves.\n"
        "3. Authenticate with `Authorization: Bearer <master_key>`; image calls are "
        "synchronous, video/audio jobs are asynchronous and polled.\n"
        f"4. Signed artifact downloads (`/v1/files/{{id}}`) need no bearer token.\n\n"
        f"Interactive UI: {base}/swagger-ui — Repository docs: docs/api.md."
    )
    if base:
        doc["servers"] = [{"url": base, "description": "This gateway"}]

    components = doc.setdefault("components", {})
    schemes = components.setdefault("securitySchemes", {})
    schemes.setdefault(
        "bearerAuth",
        {
            "type": "http",
            "scheme": "bearer",
            "description": "The deployment's master key (also the OpenAI SDK api_key).",
        },
    )

    _merge_endpoint_docs(doc)

    # Document the operational/discovery endpoints that live outside the routers'
    # schema or are excluded from it.
    paths = doc.setdefault("paths", {})
    paths.setdefault(
        "/llms.txt",
        {
            "get": {
                "summary": "Agent brief: how to call and integrate this gateway",
                "description": "Markdown (llmstxt.org layout) generated from the live "
                               "configuration: aliases, constraints, auth, snippets, "
                               "async protocol and error table. No auth required.",
                "tags": ["Discovery"],
                "responses": {"200": {"description": "Markdown document"}},
            }
        },
    )
    paths.setdefault(
        "/swagger-ui",
        {
            "get": {
                "summary": "Interactive Swagger UI",
                "description": "HTML page rendering this OpenAPI document. No auth required.",
                "tags": ["Discovery"],
                "responses": {"200": {"description": "HTML page"}},
            }
        },
    )
    paths.setdefault(
        "/health/live",
        {
            "get": {
                "summary": "Liveness probe",
                "description": "200 while the process is up; does not check backends.",
                "tags": ["Operations"],
                "responses": {"200": {"description": "alive"}},
            }
        },
    )
    paths.setdefault(
        "/health/ready",
        {
            "get": {
                "summary": "Readiness probe",
                "description": "200 only when a backend is reachable and the config is loaded.",
                "tags": ["Operations"],
                "responses": {"200": {"description": "ready"},
                              "503": {"description": "not ready"}},
            }
        },
    )
    paths.setdefault(
        "/metrics",
        {
            "get": {
                "summary": "Prometheus metrics",
                "description": "Request/task counters and durations, queue depth, disk usage.",
                "tags": ["Operations"],
                "responses": {"200": {"description": "Prometheus text format"}},
            }
        },
    )
    return doc
