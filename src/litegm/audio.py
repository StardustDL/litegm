"""Audio generation API (custom extension).

OpenAI has no stable audio-generation endpoint, so litegm exposes one shaped like
its video protocol:

* ``POST /v1/audio/generations`` — create a job (JSON or multipart)
* ``GET  /v1/audio/{id}``        — poll status/progress
* ``GET  /v1/audio/{id}/content`` — download the audio file
* ``GET  /v1/audio``             — list jobs
* ``DELETE /v1/audio/{id}``      — delete a job

Long songs can take a long time on ComfyUI, so jobs are asynchronous like video.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from .api import _require_api_key
from .config import Config
from .engine import Engine
from .errors import NotFoundError, ValidationError
from .requests import GenerationRequest

router = APIRouter()

AUDIO_STATUS = {
    "queued": "queued",
    "submitting": "in_progress",
    "running": "in_progress",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "failed",
    "timed_out": "failed",
}


def _audio_object(state: Any, task: Any) -> dict[str, Any]:
    req = task.request or {}
    error = None
    if task.error:
        error = {
            "code": task.error.get("code") or "generation_failed",
            "message": task.error.get("message") or "generation failed",
            "param": task.error.get("param"),
        }
    arts = state.tasks.list_artifacts(task.id)
    return {
        "id": task.id,
        "object": "audio",
        "created_at": int(task.created_at),
        "completed_at": int(task.finished_at) if task.finished_at else None,
        "model": task.model_alias,
        "input": task.prompt,
        "lyrics": (req.get("extra") or {}).get("lyrics") or "",
        "seconds": req.get("seconds"),
        "status": AUDIO_STATUS.get(task.status, "in_progress"),
        "progress": int(task.progress or 0),
        "error": error,
        "duration": (arts[0].meta or {}).get("duration") if arts else None,
        "litegm": {"task_id": task.id, "backend": task.backend_id, "stage": task.stage},
    }


def _resolve_audio_model(cfg: Config, model: str | None) -> str:
    models = cfg.task("audio.generate").models
    if not models:
        raise ValidationError("no audio models configured")
    if model is None:
        return models[0].alias
    if model not in {m.alias for m in models}:
        raise NotFoundError(f"model {model!r} is not configured for audio.generate",
                            code="model_not_found", param="model")
    return model


@router.post("/v1/audio/generations", dependencies=[Depends(_require_api_key)])
async def create_audio(request: Request) -> Any:
    """Create an audio job.

    JSON body: ``{"model", "input", "lyrics", "seconds", "seed"}``.
    Multipart is also accepted with the same field names.
    """
    state = request.app.state
    cfg: Config = state.config
    engine: Engine = state.engine

    payload: dict[str, Any]
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload = {k: v for k, v in form.items() if isinstance(v, str)}
    else:
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"invalid JSON body: {exc}") from exc
        if not isinstance(body, dict):
            raise ValidationError("request body must be a JSON object")
        payload = body

    caption = payload.get("input") or payload.get("prompt") or payload.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        raise ValidationError("input (caption) is required", param="input")
    alias = _resolve_audio_model(cfg, payload.get("model"))

    seconds: float | None = None
    raw_seconds = payload.get("seconds") or payload.get("duration")
    if raw_seconds not in (None, ""):
        try:
            seconds = float(raw_seconds)
        except (TypeError, ValueError) as exc:
            raise ValidationError("seconds must be a number", param="seconds") from exc

    seed: int | None = None
    if payload.get("seed") not in (None, ""):
        try:
            seed = int(payload["seed"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("seed must be an integer", param="seed") from exc

    req = GenerationRequest(
        task_type="audio.generate",
        model_alias=alias,
        prompt=caption,
        n=1,
        seconds=seconds,
        seed=seed,
        output_format="flac",
        background="opaque",
        extra={"lyrics": str(payload.get("lyrics") or "")},
    )
    task = await engine.submit(req)
    runner = asyncio.create_task(engine.run(task, req))
    state.running[task.id] = runner
    runner.add_done_callback(lambda _t, tid=task.id: state.running.pop(tid, None))
    return JSONResponse(_audio_object(state, task), status_code=200)


@router.get("/v1/audio/{audio_id}", dependencies=[Depends(_require_api_key)])
async def retrieve_audio(audio_id: str, request: Request) -> dict[str, Any]:
    state = request.app.state
    task = state.tasks.get_task(audio_id)
    if task is None or not task.task_type.startswith("audio"):
        raise NotFoundError(f"no such audio job: {audio_id}", code="not_found")
    return _audio_object(state, task)


@router.get("/v1/audio", dependencies=[Depends(_require_api_key)])
async def list_audio(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    state = request.app.state
    tasks, _ = state.tasks.list_tasks(limit=limit, task_type="audio.generate")
    data = [_audio_object(state, t) for t in tasks]
    return {"object": "list", "data": data,
            "first_id": data[0]["id"] if data else None,
            "last_id": data[-1]["id"] if data else None,
            "has_more": False}


@router.get("/v1/audio/{audio_id}/content", dependencies=[Depends(_require_api_key)])
async def audio_content(audio_id: str, request: Request) -> Any:
    state = request.app.state
    task = state.tasks.get_task(audio_id)
    if task is None or not task.task_type.startswith("audio"):
        raise NotFoundError(f"no such audio job: {audio_id}", code="not_found")
    if task.status != "succeeded":
        raise ValidationError(f"audio {audio_id} is not ready ({task.status})", param="id")
    arts = [a for a in state.tasks.list_artifacts(audio_id) if a.kind == "audio"]
    if not arts:
        raise NotFoundError("no audio artifact for this job", code="artifact_not_found")
    art = arts[0]
    path = state.artifacts.artifact_path(art)
    if not path.exists():
        raise NotFoundError("audio file is missing from storage", code="artifact_missing")
    return FileResponse(path, media_type=art.mime_type, filename=art.filename)


@router.delete("/v1/audio/{audio_id}", dependencies=[Depends(_require_api_key)])
async def delete_audio(audio_id: str, request: Request) -> dict[str, Any]:
    state = request.app.state
    task = state.tasks.get_task(audio_id)
    if task is None or not task.task_type.startswith("audio"):
        raise NotFoundError(f"no such audio job: {audio_id}", code="not_found")
    runner = state.running.get(audio_id)
    if runner is not None and not runner.done():
        await state.engine.cancel(audio_id)
    for art in state.tasks.list_artifacts(audio_id):
        try:
            state.artifacts.artifact_path(art).unlink(missing_ok=True)
        except OSError:
            pass
    state.tasks.delete_task(audio_id)
    return {"id": audio_id, "object": "audio.deleted", "deleted": True}
