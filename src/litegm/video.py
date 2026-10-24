"""OpenAI-compatible video generation API.

Implements OpenAI's native asynchronous video protocol:

* ``POST   /v1/videos``                     — create a job (multipart, optional input_reference)
* ``GET    /v1/videos/{id}``                — poll status/progress
* ``GET    /v1/videos/{id}/content``        — download the rendered video
* ``GET    /v1/videos``                     — list jobs (cursor pagination)
* ``DELETE /v1/videos/{id}``                — delete a job and its assets

Jobs map onto the same task engine used for images: a task is persisted, queued
against the backend's concurrency limit and executed by a worker. Routing by
``input_reference`` (text-to-video vs image-to-video) is configuration-driven
through ``tasks.video.generate`` aliases.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .api import _require_api_key, get_state
from .config import Config
from .engine import Engine
from .errors import (
    BadRequestError,
    ConfigError,
    NotFoundError,
    UnsupportedParameterError,
    ValidationError,
)
from .requests import GenerationRequest
from .store import TaskStore

router = APIRouter()

VIDEO_STATUS = {
    "queued": "queued",
    "submitting": "in_progress",
    "running": "in_progress",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "failed",
    "timed_out": "failed",
}


def _video_object(state: Any, task: Any) -> dict[str, Any]:
    req = task.request or {}
    error = None
    if task.error:
        error = {
            "code": task.error.get("code") or "generation_failed",
            "message": task.error.get("message") or "generation failed",
            "param": task.error.get("param"),
            "type": task.error.get("type"),
        }
    requested = req.get("requested_model") or req.get("model")
    return {
        "id": task.id,
        "object": "video",
        "created_at": int(task.created_at),
        "completed_at": int(task.finished_at) if task.finished_at else None,
        "expires_at": None,
        # ``model`` is the concrete variant that actually ran; ``requested_model``
        # preserves what the caller asked for (which may be a video family name).
        "model": task.model_alias,
        "requested_model": requested,
        "prompt": task.prompt,
        "seconds": str(req.get("seconds") or ""),
        "size": req.get("size") or "",
        "status": VIDEO_STATUS.get(task.status, "in_progress"),
        "progress": int(task.progress or 0),
        "error": error,
        "remixed_from_video_id": None,
        "litegm": {
            "task_id": task.id,
            "backend": task.backend_id,
            "stage": task.stage,
            "attempts": task.attempts,
        },
    }


def _resolve_video_model(
    cfg: Config,
    model: str | None,
    *,
    input_mode: str,
) -> tuple[str, str]:
    """Resolve ``(task_type, alias)`` for a video request.

    ``input_mode`` is ``text`` (no images), ``image`` (input_reference/first
    frame) or ``reference`` (reference_images).

    A video family name routes to its variant for the supplied input shape; a
    concrete alias is used as-is. Without ``model``, a family's variant for the
    input shape is preferred, then the first configured alias.
    """
    task_cfg = cfg.task("video.generate")
    aliases = {m.alias for m in task_cfg.models}

    if model is None:
        for family in cfg.routing.video_families:
            try:
                return "video.generate", cfg.route_video_request(family, input_mode=input_mode)
            except ConfigError:
                continue
        if input_mode != "text":
            image_capable = [m for m in task_cfg.models if m.image_slots is not None]
            if image_capable:
                return "video.generate", image_capable[0].alias
        return "video.generate", task_cfg.models[0].alias

    if model in aliases:
        return "video.generate", model

    family = cfg.video_family(model)
    if family is not None:
        return family.task, cfg.route_video_request(family, input_mode=input_mode)

    raise NotFoundError(f"model {model!r} is not configured for video.generate",
                        code="model_not_found", param="model")


@router.post("/v1/videos", dependencies=[Depends(_require_api_key)])
async def create_video(
    request: Request,
    prompt: str = Form(...),
    model: str | None = Form(default=None),
    seconds: str | None = Form(default=None),
    size: str | None = Form(default=None),
    input_reference: UploadFile | None = File(default=None),
    first_frame: UploadFile | None = File(default=None),
    reference_images: list[UploadFile] = File(default=[]),
) -> Any:
    """Create a video job.

    ``input_reference`` selects an image-to-video variant; ``first_frame`` is an
    alias for the same thing. ``reference_images`` (repeatable) select a
    reference-to-video variant. Without images a text-to-video variant is used.
    """
    state = request.app.state
    cfg: Config = state.config
    engine: Engine = state.engine

    # Input mode decides routing: OpenAI's ``input_reference``/``first_frame`` is
    # a single guiding image (image-to-video); ``reference_images`` is the litegm
    # extension for reference-to-video.
    reference_refs = list(reference_images or [])
    single_refs: list[UploadFile] = []
    if input_reference is not None:
        single_refs.append(input_reference)
    if first_frame is not None:
        single_refs.append(first_frame)

    if single_refs and reference_refs:
        raise ValidationError(
            "use either input_reference/first_frame (image-to-video) or "
            "reference_images (reference-to-video), not both",
            param="input_reference",
        )
    if reference_refs:
        input_mode = "reference"
        refs = reference_refs
    elif single_refs:
        input_mode = "image"
        refs = single_refs[:1]
    else:
        input_mode = "text"
        refs = []

    task_type, alias = _resolve_video_model(cfg, model, input_mode=input_mode)
    variant = cfg.variant(task_type, alias)

    blobs: list[bytes] = []
    names: list[str] = []
    for up in refs:
        data = await up.read()
        if not data:
            raise ValidationError("empty image upload", param="input_reference")
        if len(data) > 50 * 1024 * 1024:
            raise ValidationError(f"{up.filename} exceeds 50MB", param="input_reference")
        blobs.append(data)
        names.append(up.filename or "reference.png")

    seconds_val: float | None = None
    if seconds is not None and seconds != "":
        try:
            seconds_val = float(seconds)
        except ValueError as exc:
            raise ValidationError("seconds must be a number", param="seconds") from exc

    req = GenerationRequest(
        task_type=task_type,
        model_alias=alias,
        prompt=prompt,
        n=1,
        size=size,
        seconds=seconds_val,
        output_format="mp4",
        background="opaque",
        images=blobs,
        image_names=names,
        requested_model=model,
        input_mode=input_mode,
        extra={},
    )
    task = await engine.submit(req)
    runner = asyncio.create_task(engine.run(task, req))
    state.running[task.id] = runner
    runner.add_done_callback(lambda _t, tid=task.id: state.running.pop(tid, None))
    return JSONResponse(_video_object(state, task), status_code=200)


@router.get("/v1/videos/{video_id}", dependencies=[Depends(_require_api_key)])
async def retrieve_video(video_id: str, request: Request) -> dict[str, Any]:
    state = request.app.state
    task = state.tasks.get_task(video_id)
    if task is None or not task.task_type.startswith("video"):
        raise NotFoundError(f"no such video: {video_id}", code="not_found")
    return _video_object(state, task)


@router.get("/v1/videos", dependencies=[Depends(_require_api_key)])
async def list_videos(
    request: Request,
    after: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    state = request.app.state
    tasks, _total = state.tasks.list_tasks(limit=limit + 1, task_type="video.generate")
    items = [t for t in tasks if t.task_type.startswith("video")]
    if order == "asc":
        items = list(reversed(items))
    data = [_video_object(state, t) for t in items[:limit]]
    payload: dict[str, Any] = {"object": "list", "data": data,
                               "first_id": data[0]["id"] if data else None,
                               "last_id": data[-1]["id"] if data else None,
                               "has_more": len(items) > limit}
    return payload


@router.get("/v1/videos/{video_id}/content", dependencies=[Depends(_require_api_key)])
async def video_content(
    video_id: str,
    request: Request,
    variant: str = Query(default="video", pattern="^(video|thumbnail|spritesheet)$"),
) -> Any:
    state = request.app.state
    task = state.tasks.get_task(video_id)
    if task is None or not task.task_type.startswith("video"):
        raise NotFoundError(f"no such video: {video_id}", code="not_found")
    if task.status != "succeeded":
        raise BadRequestError(
            f"video {video_id} is not ready (status: {VIDEO_STATUS.get(task.status, task.status)})",
            code="video_not_ready",
        )
    arts = [a for a in state.tasks.list_artifacts(video_id) if a.kind == "video"]
    if variant == "thumbnail":
        thumbs = [a for a in state.tasks.list_artifacts(video_id) if a.kind == "image"]
        arts = thumbs or arts
    if not arts:
        raise NotFoundError("no video artifact for this job", code="artifact_not_found")
    art = arts[0]
    path = state.artifacts.artifact_path(art)
    if not path.exists():
        raise NotFoundError("video file is missing from storage", code="artifact_missing")
    return FileResponse(path, media_type=art.mime_type, filename=art.filename)


@router.delete("/v1/videos/{video_id}", dependencies=[Depends(_require_api_key)])
async def delete_video(video_id: str, request: Request) -> dict[str, Any]:
    state = request.app.state
    task = state.tasks.get_task(video_id)
    if task is None or not task.task_type.startswith("video"):
        raise NotFoundError(f"no such video: {video_id}", code="not_found")
    runner = state.running.get(video_id)
    if runner is not None and not runner.done():
        await state.engine.cancel(video_id)
    for art in state.tasks.list_artifacts(video_id):
        try:
            state.artifacts.artifact_path(art).unlink(missing_ok=True)
        except OSError:
            pass
    state.tasks.delete_task(video_id)
    return {"id": video_id, "object": "video.deleted", "deleted": True}
