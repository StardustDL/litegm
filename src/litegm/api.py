"""OpenAI-compatible image API.

Endpoints mirror OpenAI's image API contract:

* ``POST /v1/images/generations`` — JSON body, returns ``ImagesResponse``.
* ``POST /v1/images/edits``       — multipart body, returns ``ImagesResponse``.
* ``GET  /v1/models``             — model aliases available from configuration.
* ``GET  /v1/health``             — gateway and backend health.
* ``GET  /v1/tasks/{id}``         — non-standard extension; retrieves a task after
  a synchronous request timed out (``X-Litegm-Task-Id`` on the 504).

Image requests are synchronous, as OpenAI's are. Internally each request is
persisted as a task, which also makes it visible in the admin UI.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import Authenticator
from .backends import BackendRegistry
from .config import Config
from .engine import Engine
from .errors import (
    BadRequestError,
    LiteGMError,
    NotFoundError,
    SyncTimeoutError,
    UnknownModelError,
    UnsupportedParameterError,
    ValidationError,
)
from .requests import GenerationRequest, validate_request
from .storage import ArtifactStore
from .store import TaskStore

router = APIRouter()


# -- request models ---------------------------------------------------------


class ImageGenerationBody(BaseModel):
    prompt: str
    model: str | None = None
    n: int | None = None
    size: str | None = None
    quality: str | None = None
    output_format: str | None = None
    output_compression: int | None = None
    background: str | None = None
    moderation: str | None = None
    safety_identifier: str | None = None
    user: str | None = None
    stream: bool | None = None
    response_format: str | None = None
    seed: int | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)


# -- dependencies -----------------------------------------------------------


def get_state(request: Request) -> Any:
    return request.app.state


async def _require_api_key(
    authorization: str | None = Header(default=None),
    request: Request = None,  # type: ignore[assignment]
) -> None:
    request.app.state.auth.require_bearer(authorization)


def _default_model(cfg: Config, task_type: str) -> str:
    models = cfg.task(task_type).models
    if not models:
        raise ValidationError(f"no models configured for {task_type}")
    return models[0].alias


def _check_model_for_task(cfg: Config, task_type: str, alias: str | None) -> str:
    if alias is None:
        return _default_model(cfg, task_type)
    known = {m.alias for t in cfg.tasks.values() for m in t.models}
    if alias not in known:
        raise UnknownModelError(alias, task_type)
    if alias not in {m.alias for m in cfg.task(task_type).models}:
        raise UnknownModelError(alias, task_type)
    return alias


def _resolve_model(cfg: Config, alias: str | None, *, endpoint: str, has_images: bool) -> tuple[str, str]:
    """Return ``(task_type, alias)`` for an image request.

    Unified aliases route by whether input images were supplied; otherwise the
    endpoint decides the task. A unified alias is accepted on either image
    endpoint, so callers can use one model name for generation and editing.
    """
    if alias is None:
        task_type = "image.edit" if has_images else "image.generate"
        return task_type, _default_model(cfg, task_type)

    known = {m.alias for t in cfg.tasks.values() for m in t.models}
    if alias not in known:
        raise UnknownModelError(alias, endpoint)

    unified = cfg.unified(alias)
    if unified is not None:
        task_type = cfg.route_image_request(alias, has_images=has_images)
        return task_type, alias

    if alias in {m.alias for m in cfg.task(endpoint).models}:
        return endpoint, alias

    # A non-unified alias passed to the other endpoint: accept it when it is
    # compatible with the request shape.
    other = "image.edit" if endpoint == "image.generate" else "image.generate"
    variant = cfg.variant(other, alias) if alias in {m.alias for m in cfg.task(other).models} else None
    if variant is not None:
        accepts = variant.image_slots is not None
        if accepts == has_images:
            return other, alias
    raise UnknownModelError(alias, endpoint)


def _build_response(
    state: Any,
    task_id: str,
    *,
    response_format: str | None,
    size: str,
    quality: str | None,
    output_format: str,
    background: str,
    created: int,
) -> dict[str, Any]:
    artifacts: ArtifactStore = state.artifacts
    arts = [a for a in state.tasks.list_artifacts(task_id) if a.kind == "image"]
    data = []
    for a in arts:
        if response_format == "url":
            data.append({"url": artifacts.download_url(a.id)})
        else:
            raw = artifacts.artifact_path(a).read_bytes()
            data.append({"b64_json": base64.b64encode(raw).decode("ascii")})
    return {
        "created": created,
        "data": data,
        "size": size,
        "quality": quality,
        "output_format": output_format,
        "background": background,
    }


async def _run_sync(
    *,
    state: Any,
    req: GenerationRequest,
) -> dict[str, Any]:
    """Create, run and wait for a task; translate the outcome into an OpenAI body."""
    cfg: Config = state.config
    engine: Engine = state.engine
    tasks: TaskStore = state.tasks
    artifacts: ArtifactStore = state.artifacts

    variant = cfg.variant(req.task_type, req.model_alias)
    normalized = validate_request(req, variant, is_edit=req.task_type.endswith("edit"))
    task = await engine.submit(req)
    runner = asyncio.create_task(engine.run(task, req))
    state.running[task.id] = runner
    runner.add_done_callback(lambda _t, tid=task.id: state.running.pop(tid, None))

    try:
        await asyncio.wait_for(asyncio.shield(runner), timeout=cfg.server.sync_timeout_s)
    except TimeoutError as exc:
        raise SyncTimeoutError(
            f"generation is still running after {cfg.server.sync_timeout_s:.0f}s; "
            f"retrieve it with GET /v1/tasks/{task.id}",
            task.id,
        ) from exc

    final = tasks.get_task(task.id)
    if final is None:
        raise LiteGMError("task disappeared", status=500, code="internal_error")
    if final.status == "succeeded":
        arts = [a for a in tasks.list_artifacts(task.id) if a.kind == "image"]
        if arts and arts[0].width and arts[0].height:
            size = f"{arts[0].width}x{arts[0].height}"
        else:
            size = f"{normalized['width']}x{normalized['height']}"
        return _build_response(
            state, task.id,
            response_format=req.response_format,
            size=size,
            quality=req.quality,
            output_format=normalized["output_format"],
            background=normalized["background"],
            created=req.created,
        )
    if final.status == "cancelled":
        raise LiteGMError("The request was cancelled.", status=409,
                          type="invalid_request_error", code="task_cancelled")
    err = final.error or {}
    raise LiteGMError(
        err.get("message", "generation failed"),
        status=int(err.get("status", 422)),
        type="server_error" if int(err.get("status", 422)) >= 500 else "invalid_request_error",
        code=err.get("code", "generation_failed"),
        details=err.get("details") or {},
    )


def _stream_response(
    *,
    state: Any,
    req: GenerationRequest,
    body_kwargs: dict[str, Any],
):
    """SSE streaming shaped like OpenAI's image edit/generation stream.

    ComfyUI does not expose intermediate frames for these workflows, so a single
    ``*.completed`` event is emitted when the image is ready.
    """
    cfg: Config = state.config
    engine: Engine = state.engine
    tasks: TaskStore = state.tasks
    artifacts: ArtifactStore = state.artifacts

    async def gen():
        task = await engine.submit(req)
        runner = asyncio.create_task(engine.run(task, req))
        state.running[task.id] = runner
        runner.add_done_callback(lambda _t, tid=task.id: state.running.pop(tid, None))
        try:
            await asyncio.wait_for(asyncio.shield(runner), timeout=cfg.server.sync_timeout_s)
        except TimeoutError:
            runner.cancel()
            yield _sse({"type": "error", "error": {"code": "sync_timeout",
                                                   "message": f"see GET /v1/tasks/{task.id}"}})
            return
        final = tasks.get_task(task.id)
        if final is None or final.status != "succeeded":
            err = (final.error if final else None) or {"code": "generation_failed",
                                                       "message": "generation failed"}
            yield _sse({"type": "error", "error": {"code": err.get("code"),
                                                   "message": err.get("message")}})
            return
        arts = [a for a in state.tasks.list_artifacts(task.id) if a.kind == "image"]
        for i, a in enumerate(arts):
            raw = state.artifacts.artifact_path(a).read_bytes()
            yield _sse({
                "type": "image_edit.completed",
                "b64_json": base64.b64encode(raw).decode("ascii"),
                "created_at": int(time.time()),
                "background": body_kwargs.get("background") or "opaque",
                "output_format": body_kwargs.get("output_format") or "png",
                "quality": body_kwargs.get("quality") or "auto",
                "size": body_kwargs.get("size") or "auto",
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                          "input_tokens_details": {"image_tokens": 0, "text_tokens": 0}},
                "partial_image_index": i,
            })

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse(payload: dict[str, Any]) -> bytes:
    import json

    return (f"data: {json.dumps(payload, ensure_ascii=False)}\n\n").encode()


# -- endpoints --------------------------------------------------------------


@router.post("/v1/images/generations", dependencies=[Depends(_require_api_key)])
async def images_generations(request: Request, body: ImageGenerationBody) -> Any:
    state = request.app.state
    cfg: Config = state.config
    task_type, alias = _resolve_model(cfg, body.model, endpoint="image.generate", has_images=False)
    variant = cfg.variant(task_type, alias)
    return await _handle_generate(request, body, alias=alias, variant=variant)


async def _handle_generate(
    request: Request,
    body: ImageGenerationBody,
    *,
    alias: str | None = None,
    variant: Any = None,
) -> Any:
    state = request.app.state
    cfg: Config = state.config
    if alias is None:
        task_type, alias = _resolve_model(cfg, body.model, endpoint="image.generate", has_images=False)
        variant = cfg.variant(task_type, alias)

    if body.extra_body:
        unknown = set(body.extra_body) - _KNOWN_FIELDS
        if unknown:
            raise UnsupportedParameterError(
                f"unsupported parameter(s): {', '.join(sorted(unknown))}",
                param=sorted(unknown)[0],
            )
    if body.stream:
        req = _req_from_body(body, alias, task_type="image.generate")
        return _stream_response(
            state=state, req=req,
            body_kwargs={"size": body.size, "quality": body.quality,
                         "output_format": body.output_format, "background": body.background},
        )
    req = _req_from_body(body, alias, task_type="image.generate")
    validate_request(req, variant, is_edit=False)
    return JSONResponse(await _run_sync(state=state, req=req))


@router.post("/v1/images", dependencies=[Depends(_require_api_key)])
async def images_unified(request: Request) -> Any:
    """One image endpoint for both generation and editing.

    Accepts either a JSON body (text-to-image) or multipart with ``image`` files
    (image editing). Routing is driven by configuration: aliases listed under
    ``routing.unified_image_models`` pick the matching variant based on whether
    images were supplied. The response shape is identical to the OpenAI endpoints.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        files = form.getlist("image")
        if not files:
            raise ValidationError("multipart requests to /v1/images require 'image' file(s)", param="image")
        prompt = form.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValidationError("prompt is required", param="prompt")
        model = form.get("model")
        return await _handle_edit(
            request,
            files=files,  # type: ignore[arg-type]
            prompt=prompt,
            model=model if isinstance(model, str) else None,
            n=_form_int(form, "n"),
            size=_form_str(form, "size"),
            quality=_form_str(form, "quality"),
            output_format=_form_str(form, "output_format"),
            output_compression=_form_int(form, "output_compression"),
            background=_form_str(form, "background"),
            mask=form.get("mask") if hasattr(form.get("mask"), "read") else None,
            stream=_form_bool(form, "stream"),
            response_format=_form_str(form, "response_format"),
            seed=_form_int(form, "seed"),
            negative_prompt=_form_str(form, "negative_prompt"),
        )

    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"invalid JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")
    try:
        body = ImageGenerationBody.model_validate(payload)
    except Exception as exc:  # pydantic validation error -> OpenAI shape
        raise ValidationError(str(exc).splitlines()[0]) from exc
    return await _handle_generate(request, body)


def _form_str(form: Any, name: str) -> str | None:
    value = form.get(name)
    return value if isinstance(value, str) and value != "" else None


def _form_int(form: Any, name: str) -> int | None:
    value = _form_str(form, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer", param=name) from exc


def _form_bool(form: Any, name: str) -> bool | None:
    value = _form_str(form, name)
    if value is None:
        return None
    return value.lower() in ("1", "true", "yes", "on")


_KNOWN_FIELDS = {
    "prompt", "model", "n", "size", "quality", "output_format", "output_compression",
    "background", "moderation", "safety_identifier", "user", "stream", "response_format",
    "seed", "style",
}


def _req_from_body(body: ImageGenerationBody, alias: str, *, task_type: str) -> GenerationRequest:
    extra = dict(body.extra_body or {})
    # ``style`` is a legacy OpenAI parameter; fold it into the prompt like OpenAI
    # clients expect instead of rejecting it.
    style = extra.pop("style", None)
    prompt = body.prompt
    if style and style not in prompt:
        prompt = f"{prompt}, {style} style"
    return GenerationRequest(
        task_type=task_type,
        model_alias=alias,
        prompt=prompt,
        n=body.n or 1,
        size=body.size,
        quality=body.quality,
        output_format=body.output_format or "png",
        background=body.background or "opaque",
        output_compression=body.output_compression,
        response_format=body.response_format,
        seed=body.seed,
        extra=extra,
    )


@router.post("/v1/images/edits", dependencies=[Depends(_require_api_key)])
async def images_edits(
    request: Request,
    image: list[UploadFile] = File(...),
    prompt: str = Form(...),
    model: str | None = Form(default=None),
    n: int | None = Form(default=None),
    size: str | None = Form(default=None),
    quality: str | None = Form(default=None),
    output_format: str | None = Form(default=None),
    output_compression: int | None = Form(default=None),
    background: str | None = Form(default=None),
    mask: UploadFile | None = File(default=None),
    stream: bool | None = Form(default=None),
    response_format: str | None = Form(default=None),
    seed: int | None = Form(default=None),
    negative_prompt: str | None = Form(default=None),
) -> Any:
    return await _handle_edit(
        request,
        files=image,
        prompt=prompt,
        model=model,
        n=n,
        size=size,
        quality=quality,
        output_format=output_format,
        output_compression=output_compression,
        background=background,
        mask=mask,
        stream=stream,
        response_format=response_format,
        seed=seed,
        negative_prompt=negative_prompt,
    )


async def _handle_edit(
    request: Request,
    *,
    files: list[Any],
    prompt: str,
    model: str | None,
    n: int | None,
    size: str | None,
    quality: str | None,
    output_format: str | None,
    output_compression: int | None,
    background: str | None,
    mask: Any,
    stream: bool | None,
    response_format: str | None,
    seed: int | None,
    negative_prompt: str | None,
) -> Any:
    state = request.app.state
    cfg: Config = state.config
    task_type, alias = _resolve_model(cfg, model, endpoint="image.edit", has_images=True)
    variant = cfg.variant(task_type, alias)

    if mask is not None:
        raise UnsupportedParameterError(
            "mask is not supported in v1: the configured edit workflow has no "
            "inpainting node; describe the region to change in the prompt instead",
            param="mask",
        )
    if variant.mask_policy == "unsupported" and mask is not None:
        raise UnsupportedParameterError("mask is not supported by this model", param="mask")

    blobs: list[bytes] = []
    names: list[str] = []
    for up in files:
        data = await up.read()
        if not data:
            raise ValidationError("empty image upload", param="image")
        if len(data) > 50 * 1024 * 1024:
            raise ValidationError(f"{getattr(up, 'filename', None) or 'image'} exceeds 50MB", param="image")
        blobs.append(data)
        names.append(getattr(up, "filename", None) or "image.png")

    req = GenerationRequest(
        task_type=task_type,
        model_alias=alias,
        prompt=prompt,
        n=n or 1,
        size=size,
        quality=quality,
        output_format=output_format or "png",
        background=background or "opaque",
        output_compression=output_compression,
        response_format=response_format,
        seed=seed,
        images=blobs,
        image_names=names,
        extra={"negative_prompt": negative_prompt or ""},
    )
    validate_request(req, variant, is_edit=True)
    if stream:
        return _stream_response(
            state=state, req=req,
            body_kwargs={"size": size, "quality": quality,
                         "output_format": output_format, "background": background},
        )
    return JSONResponse(await _run_sync(state=state, req=req))


@router.get("/v1/models", dependencies=[Depends(_require_api_key)])
async def list_models(request: Request) -> dict[str, Any]:
    cfg: Config = request.app.state.config
    created = 0
    out = []
    for task_name, task in cfg.tasks.items():
        for m in task.models:
            c = m.constraints
            unified = cfg.unified(m.alias)
            if unified is not None and task_name == unified.edit_task:
                # The unified entry is emitted from its generate variant below.
                continue
            if unified is not None:
                edit = cfg.variant(unified.edit_task, m.alias)
                caps = {
                    "task": [unified.generate_task, unified.edit_task],
                    "unified": True,
                    "endpoints": ["/v1/images", "/v1/images/generations", "/v1/images/edits"],
                    "routing": "images present -> edit; no images -> generate",
                    "accepts_images": True,
                    "max_images": _max_images(edit),
                    "n_max": min(c.n_max, edit.constraints.n_max),
                    "size_step": c.size_step,
                    "min_edge": c.min_edge,
                    "max_edge": c.max_edge,
                    "default_size": c.default_size,
                    "size_policy": "auto_or_explicit",
                    "output_formats": c.output_formats,
                    "backgrounds": c.backgrounds,
                    "mask": edit.mask_policy,
                }
            else:
                caps = {
                    "task": task_name,
                    "accepts_images": m.image_slots is not None,
                    "max_images": _max_images(m),
                    "n_max": c.n_max,
                    "size_step": c.size_step,
                    "min_edge": c.min_edge,
                    "max_edge": c.max_edge,
                    "default_size": c.default_size,
                    "size_policy": c.size_policy,
                    "output_formats": c.output_formats,
                    "backgrounds": c.backgrounds,
                    "mask": m.mask_policy,
                }
            out.append({
                "id": m.alias,
                "object": "model",
                "created": created,
                "owned_by": "litegm",
                "capabilities": caps,
            })
    for family in cfg.routing.video_families:
        variants = {
            "text_to_video": family.text_to_video,
            "image_to_video": family.image_to_video,
            "reference_to_video": family.reference_to_video,
        }
        out.append({
            "id": family.family,
            "object": "model",
            "created": created,
            "owned_by": "litegm",
            "capabilities": {
                "task": family.task,
                "video_family": True,
                "endpoints": ["/v1/videos"],
                "routing": "no images -> text_to_video; input_reference -> image_to_video; "
                           "reference_images[] -> reference_to_video",
                "variants": {k: v for k, v in variants.items() if v},
            },
        })
    return {"object": "list", "data": out}


def _max_images(variant: Any) -> int:
    slots = variant.image_slots
    if slots is None:
        return 0
    ref = slots.reference
    if ref is not None and ref.extra_node_base is not None:
        return 16
    return 2 if ref is not None else 1


@router.get("/v1/health")
async def health(request: Request) -> dict[str, Any]:
    state = request.app.state
    backends: BackendRegistry = state.backends
    tasks: TaskStore = state.tasks
    health_map = await backends.health_all()
    ok = any(v.get("healthy") for v in health_map.values())
    return {
        "status": "ok" if ok else "degraded",
        "version": state.version,
        "tasks": tasks.counts_by_status(),
        "queues": state.engine.queue_stats(),
        "backends": health_map,
    }


@router.get("/v1/tasks/{task_id}", dependencies=[Depends(_require_api_key)])
async def get_task(task_id: str, request: Request) -> dict[str, Any]:
    state = request.app.state
    task = state.tasks.get_task(task_id)
    if task is None:
        raise NotFoundError(f"no such task: {task_id}", code="task_not_found")
    arts = state.tasks.list_artifacts(task_id)
    return {
        "id": task.id,
        "object": "litegm.task",
        "status": task.status,
        "stage": task.stage,
        "progress": task.progress,
        "model": task.model_alias,
        "task_type": task.task_type,
        "created_at": int(task.created_at),
        "started_at": int(task.started_at) if task.started_at else None,
        "finished_at": int(task.finished_at) if task.finished_at else None,
        "error": task.error,
        "attempts": task.attempts,
        "data": [
            {"url": state.artifacts.download_url(a.id), "size": a.size_bytes,
             "width": a.width, "height": a.height, "suspicious": a.suspicious}
            for a in arts
        ],
    }


@router.get("/v1/files/{artifact_id}")
async def download_file(artifact_id: str, request: Request, expires: int = 0, sig: str = "") -> Any:
    """Signed download links used by ``response_format=url``; no bearer needed."""
    state = request.app.state
    if not state.artifacts.verify(artifact_id, expires, sig):
        raise NotFoundError("download link is invalid or expired", code="invalid_signature")
    art = state.tasks.get_artifact(artifact_id)
    if art is None:
        raise NotFoundError(f"no such artifact: {artifact_id}", code="artifact_not_found")
    path = state.artifacts.artifact_path(art)
    if not path.exists():
        raise NotFoundError("artifact file is missing from storage", code="artifact_missing")
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type=art.mime_type, filename=art.filename)


# -- error rendering --------------------------------------------------------


async def litegm_error_handler(request: Request, exc: LiteGMError) -> JSONResponse:
    headers: dict[str, str] = {}
    if isinstance(exc, SyncTimeoutError) and exc.details.get("task_id"):
        headers["X-Litegm-Task-Id"] = str(exc.details["task_id"])
    return JSONResponse(exc.to_openai(), status_code=exc.status, headers=headers)
