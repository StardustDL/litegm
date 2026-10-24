"""Admin API: task history, task details, backend health, live events.

Auth: HTTP Basic with the configured username + master key, exchanged for a signed
session cookie. All ``/admin/api/*`` routes require a valid session.

Thumbnails for image/video artifacts and uploaded inputs are generated with
Pillow and cached on disk under ``<storage.root>/.thumbs/``. Video frames are
extracted with ffmpeg when it happens to be on PATH; otherwise a neutral
placeholder is rendered so the UI never shows a broken image.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from .auth import SESSION_COOKIE, Authenticator
from .errors import AuthError, BadRequestError, NotFoundError

router = APIRouter()

# Thumbnail sizing: the query is clamped so a client cannot ask for a 10k px
# JPEG on every gallery row.
THUMB_SIZE_MIN = 64
THUMB_SIZE_MAX = 1024
THUMB_SIZE_DEFAULT = 384
THUMB_CACHE_CONTROL = "public, max-age=86400"
THUMB_DIR_NAME = ".thumbs"
THUMB_QUALITY = 82
VIDEO_KINDS = ("video",)
AUDIO_KINDS = ("audio",)
THUMB_EXTRACT_TIMEOUT_S = 20


def _auth(request: Request) -> Authenticator:
    return request.app.state.auth


def _session_ok(request: Request) -> bool:
    return _auth(request).verify_session(request.cookies.get(SESSION_COOKIE))


def _require_session(request: Request) -> None:
    if not _session_ok(request):
        raise AuthError("Admin session required. Sign in with Basic auth first.")


def _request_base_url(request: Request) -> str:
    """Base URL for signed links, derived from the host the client actually used.

    Hard-coding the configured ``public_base_url`` breaks every deployment that
    listens on another port (local debugging, reverse proxies, several instances
    side by side). Prefer the request's own scheme/host, falling back to the
    configured value only when the request carries no usable host.
    """
    cfg = request.app.state.config
    host = request.headers.get("host")
    if host:
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        return f"{scheme}://{host}"
    return cfg.server.public_base_url


# -- thumbnails --------------------------------------------------------------


def _clamp_size(size: int) -> int:
    return max(THUMB_SIZE_MIN, min(THUMB_SIZE_MAX, size))


def _thumb_cache_dir(state: Any) -> Path:
    """Thumbnail cache lives beside the artifacts, inside the storage root."""
    path = state.artifacts.root / THUMB_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _thumb_cache_key(artifact_id: str, size: int, mtime: float, length: int) -> str:
    # Source mtime/size are part of the key so a regenerated file never serves a
    # stale cached thumbnail.
    raw = f"{artifact_id}:{size}:{int(mtime)}:{length}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _thumb_cache_path(state: Any, cache_key: str) -> Path:
    return _thumb_cache_dir(state) / f"{cache_key}.jpg"


def _placeholder_thumb(size: int, label: str = "") -> bytes:
    """Neutral dark placeholder JPEG, used when no frame can be decoded."""
    from PIL import Image, ImageDraw

    ink = (23, 26, 33)
    hairline = (46, 51, 62)
    amber = (240, 176, 74)
    im = Image.new("RGB", (size, size), ink)
    draw = ImageDraw.Draw(im)
    draw.rectangle([1, 1, size - 2, size - 2], outline=hairline, width=1)
    # A simple film-frame glyph: two sprocket rows and an inner aperture.
    inset = max(4, size // 12)
    bar = max(2, size // 40)
    draw.rectangle([inset, inset, size - inset, inset + bar], fill=hairline)
    draw.rectangle([inset, size - inset - bar, size - inset, size - inset], fill=hairline)
    mid = size // 2
    draw.rectangle([mid - size // 6, mid - size // 8, mid + size // 6, mid + size // 8],
                   outline=amber, width=max(1, size // 96))
    if label:
        draw.text((size // 12, size - size // 6), label, fill=amber)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=THUMB_QUALITY, optimize=True)
    return buf.getvalue()


def _encode_thumb(im: Any, size: int) -> bytes:
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        # Flatten transparency over the darkroom ink colour, not black.
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (23, 26, 33, 255))
        bg.alpha_composite(im)
        im = bg
    if im.mode != "RGB":
        im = im.convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=THUMB_QUALITY, optimize=True)
    return buf.getvalue()


def _image_thumb(path: Path, size: int) -> bytes | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.load()
            return _encode_thumb(im, size)
    except Exception:  # noqa: BLE001 - a broken artifact must not break the gallery
        return None


def _find_ffmpeg() -> str | None:
    """ffmpeg is optional: only used when it is already installed."""
    return shutil.which("ffmpeg")


def _video_frame(path: Path, size: int) -> bytes | None:
    """Extract a frame near the start of the video via ffmpeg, if available."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None
    fd, tmp_name = tempfile.mkstemp(suffix=".png", prefix="litegm-thumb-")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, ffmpeg resolved above
            [ffmpeg, "-v", "error", "-y", "-ss", "0", "-i", str(path),
             "-frames:v", "1", "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
             str(tmp)],
            capture_output=True, timeout=THUMB_EXTRACT_TIMEOUT_S, check=False,
        )
        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            return None
        return _image_thumb(tmp, size)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _video_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Read the display size from an MP4/WebM container header.

    Only the ``tkhd`` box is parsed; codecs are not decoded (no dependency).
    Never raises: a truncated or corrupt file simply yields ``(None, None)``.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(1 << 20)
    except OSError:
        return None, None
    try:
        idx = head.find(b"tkhd")
        if idx < 0:
            return None, None
        # ``tkhd`` payload: version/flags(4), then 80 bytes of v0 fields or
        # 92 bytes of v1 fields; width/height are the last two 16.16 words.
        box = head[idx + 4: idx + 4 + 96]
        if len(box) < 4:
            return None, None
        version = box[0]
        offset = 76 if version == 0 else 88
        if len(box) < offset + 8:
            return None, None
        width = int.from_bytes(box[offset:offset + 4], "big") >> 16
        height = int.from_bytes(box[offset + 4:offset + 8], "big") >> 16
    except (IndexError, ValueError, OverflowError):  # pragma: no cover - defensive
        return None, None
    if width <= 0 or height <= 0:
        return None, None
    return width, height


def _artifact_source_path(state: Any, artifact_id: str) -> tuple[Any, Path] | None:
    art = state.tasks.get_artifact(artifact_id)
    if art is None:
        return None
    return art, state.artifacts.artifact_path(art)


def _cached_thumb(state: Any, cache_key: str, render: Any) -> bytes | None:
    """Return a cached thumbnail, or render and persist it.

    ``render`` is a zero-argument callable returning JPEG bytes or ``None``.
    """
    cached = _thumb_cache_path(state, cache_key)
    if cached.exists():
        try:
            return cached.read_bytes()
        except OSError:
            pass
    data = render()
    if data is None:
        return None
    try:
        # Write-then-rename so a concurrent reader never sees a partial file.
        tmp = cached.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cached)
    except OSError:
        pass
    return data


def artifact_thumb_bytes(state: Any, artifact_id: str, size: int) -> tuple[bytes, str] | None:
    """Return ``(jpeg_bytes, cache_key)`` for an artifact thumbnail, cached on disk.

    Returns ``None`` when the artifact is unknown or its file is gone. Audio and
    other kinds render as the neutral placeholder.
    """
    found = _artifact_source_path(state, artifact_id)
    if found is None:
        return None
    art, path = found
    if not path.exists():
        return None
    stat = path.stat()
    cache_key = _thumb_cache_key(artifact_id, size, stat.st_mtime, stat.st_size)

    def render() -> bytes | None:
        if art.kind == "image" or (art.mime_type or "").startswith("image/"):
            data = _image_thumb(path, size)
            if data is not None:
                return data
        elif art.kind in VIDEO_KINDS or (art.mime_type or "").startswith("video/"):
            data = _video_frame(path, size)
            if data is not None:
                return data
        label = "VIDEO" if art.kind in VIDEO_KINDS else ("AUDIO" if art.kind in AUDIO_KINDS else "")
        return _placeholder_thumb(size, label)

    data = _cached_thumb(state, cache_key, render)
    if data is None:
        return None
    return data, cache_key


def _artifact_dimensions(art: Any) -> tuple[int | None, int | None]:
    if art.width and art.height:
        return art.width, art.height
    if art.kind in VIDEO_KINDS:
        return _video_dimensions(Path(art.path))
    return None, None


def _thumb_url(path: str, size: int) -> str:
    return f"{path}?size={size}"


def artifact_preview(state: Any, art: Any, size: int = THUMB_SIZE_DEFAULT) -> dict[str, Any] | None:
    """Compact preview descriptor for one artifact (``None`` if unusable)."""
    path = state.artifacts.artifact_path(art)
    if not path.exists():
        return None
    width, height = _artifact_dimensions(art)
    return {
        "url": _thumb_url(f"/admin/api/artifacts/{art.id}/thumb", size),
        "kind": art.kind,
        "width": width,
        "height": height,
        "id": art.id,
        "artifact_url": f"/admin/api/artifacts/{art.id}/raw",
    }


def input_preview(state: Any, task_id: str, item: dict[str, Any],
                  size: int = THUMB_SIZE_DEFAULT) -> dict[str, Any] | None:
    """Compact preview descriptor for one uploaded input image."""
    path = Path(item["path"])
    if not path.exists():
        return None
    mime = item.get("mime_type") or ""
    if mime and not mime.startswith("image/"):
        return None
    return {
        "url": _thumb_url(f"/admin/api/tasks/{task_id}/inputs/{item['index']}/thumb", size),
        "kind": "image",
        "width": item.get("width"),
        "height": item.get("height"),
        "index": item["index"],
        "role": item.get("role"),
        "raw_url": f"/admin/api/tasks/{task_id}/inputs/{item['index']}/raw",
    }


def _first_artifact_preview(state: Any, arts: list[Any]) -> dict[str, Any] | None:
    for art in arts:
        preview = artifact_preview(state, art)
        if preview is not None:
            return preview
    return None


def _first_input_preview(state: Any, task_id: str, inputs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in inputs:
        preview = input_preview(state, task_id, item)
        if preview is not None:
            return preview
    return None


def _duration_s(task: Any) -> float | None:
    """Wall-clock execution time; ``None`` while unfinished or unstarted."""
    if not task.started_at or not task.finished_at:
        return None
    return round(max(0.0, task.finished_at - task.started_at), 3)


def _task_dict(state: Any, task: Any, base_url: str | None = None) -> dict[str, Any]:
    arts = state.tasks.list_artifacts(task.id)
    inputs = state.tasks.list_input_images(task.id)
    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "stage": task.stage,
        "progress": task.progress,
        "model_alias": task.model_alias,
        "backend_id": task.backend_id,
        "prompt": task.prompt,
        "request": task.request,
        "comfy_prompt_id": task.comfy_prompt_id,
        "error": task.error,
        "attempts": task.attempts,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        # v4: execution wall time for the detail view; null while unfinished.
        "duration_s": _duration_s(task),
        "cancel_requested": task.cancel_requested,
        "input_images": [
            {
                "index": i["index"],
                "role": i["role"],
                "filename": i["filename"],
                "mime_type": i["mime_type"],
                "size_bytes": i["size_bytes"],
                "width": i["width"],
                "height": i["height"],
                "url": f"/admin/api/tasks/{task.id}/inputs/{i['index']}/raw",
            }
            for i in inputs
        ],
        "artifacts": [
            {
                "id": a.id,
                "kind": a.kind,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "width": a.width,
                "height": a.height,
                "suspicious": a.suspicious,
                "meta": a.meta,
                "url": f"/admin/api/artifacts/{a.id}/raw",
                "signed_url": state.artifacts.download_url(a.id, base_url),
            }
            for a in arts
        ],
        # v4: compact thumbnails so the detail view renders media without
        # requesting every full-size file first.
        "artifact_previews": [
            p for p in (artifact_preview(state, a) for a in arts) if p is not None
        ],
        "input_previews": [
            p for p in (input_preview(state, task.id, i) for i in inputs) if p is not None
        ],
    }


# -- session -----------------------------------------------------------------


@router.post("/admin/api/login")
async def login(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
    auth = _auth(request)
    if not auth.check_basic(authorization):
        raise AuthError("Invalid username or master key.")
    token = auth.issue_session()
    resp = JSONResponse({"ok": True, "username": auth.config.username})
    resp.set_cookie(
        SESSION_COOKIE, token,
        max_age=auth.config.session_ttl_s, httponly=True, samesite="lax", path="/",
    )
    return resp


@router.post("/admin/api/logout")
async def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/admin/api/me")
async def me(request: Request) -> dict[str, Any]:
    auth = _auth(request)
    if not _session_ok(request):
        return {"authenticated": False, "auth_enabled": auth.config.enabled}
    return {"authenticated": True, "username": auth.config.username,
            "auth_enabled": auth.config.enabled}


# -- tasks -------------------------------------------------------------------


@router.get("/admin/api/tasks")
async def list_tasks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    task_type: str | None = None,
    model_alias: str | None = None,
    backend_id: str | None = None,
    since: float | None = None,
    until: float | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    _require_session(request)
    state = request.app.state
    tasks, total = state.tasks.list_tasks(
        limit=limit, offset=offset, status=status, task_type=task_type,
        model_alias=model_alias, backend_id=backend_id, since=since, until=until,
        search=search,
    )
    arts = state.tasks.artifacts_for_tasks([t.id for t in tasks])
    inputs_by_task = state.tasks.input_images_for_tasks([t.id for t in tasks])
    items = []
    for t in tasks:
        task_arts = arts.get(t.id, [])
        inputs = inputs_by_task.get(t.id, [])
        items.append({
            "id": t.id,
            "task_type": t.task_type,
            "status": t.status,
            "stage": t.stage,
            "progress": t.progress,
            "model_alias": t.model_alias,
            "backend_id": t.backend_id,
            "prompt": t.prompt[:200],
            "created_at": t.created_at,
            "finished_at": t.finished_at,
            "error_code": (t.error or {}).get("code"),
            "artifact_count": len(task_arts),
            "suspicious": any(a.suspicious for a in task_arts),
            # v4: first artifact and first uploaded input, so history renders
            # media without one detail request per row.
            "preview": _first_artifact_preview(state, task_arts),
            "input_preview": _first_input_preview(state, t.id, inputs),
        })
    return {"total": total, "items": items}


@router.get("/admin/api/tasks/export")
async def export_tasks(
    request: Request,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    limit: int = Query(default=1000, ge=1, le=10000),
    search: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    since: float | None = None,
    until: float | None = None,
) -> Any:
    _require_session(request)
    state = request.app.state
    tasks, _total = state.tasks.list_tasks(
        limit=limit, status=status, task_type=task_type, since=since, until=until, search=search,
    )
    rows = [
        {
            "id": t.id,
            "task_type": t.task_type,
            "status": t.status,
            "model_alias": t.model_alias,
            "backend_id": t.backend_id,
            "prompt": t.prompt,
            "created_at": t.created_at,
            "finished_at": t.finished_at,
            "error_code": (t.error or {}).get("code"),
            "comfy_prompt_id": t.comfy_prompt_id,
            "requested_model": (t.request or {}).get("requested_model"),
            "n": (t.request or {}).get("n"),
            "size": (t.request or {}).get("size"),
            "seconds": (t.request or {}).get("seconds"),
            "artifacts": len(state.tasks.list_artifacts(t.id)),
        }
        for t in tasks
    ]
    if format == "json":
        return JSONResponse({"total": len(rows), "items": rows})
    import csv
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["id"])
    writer.writeheader()
    writer.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@router.get("/admin/api/tasks/{task_id}")
async def task_detail(request: Request, task_id: str) -> dict[str, Any]:
    _require_session(request)
    state = request.app.state
    task = state.tasks.get_task(task_id)
    if task is None:
        raise NotFoundError(f"no such task: {task_id}", code="task_not_found")
    out = _task_dict(state, task, _request_base_url(request))
    out["workflow"] = task.workflow
    out["events"] = state.tasks.list_events(task_id)
    return out


@router.post("/admin/api/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
    _require_session(request)
    state = request.app.state
    task = state.tasks.get_task(task_id)
    if task is None:
        raise NotFoundError(f"no such task: {task_id}", code="task_not_found")
    runner = state.running.get(task_id)
    ok = await state.engine.cancel(task_id)
    if runner is not None and not runner.done():
        # The engine sees the cancel flag on its next poll and finishes cleanly.
        pass
    return {"ok": ok, "status": state.tasks.get_task(task_id).status}


@router.post("/admin/api/tasks/{task_id}/retry")
async def retry_task(request: Request, task_id: str) -> dict[str, Any]:
    _require_session(request)
    state = request.app.state
    task = state.tasks.get_task(task_id)
    if task is None:
        raise NotFoundError(f"no such task: {task_id}", code="task_not_found")
    from .requests import GenerationRequest

    req = GenerationRequest(
        task_type=task.task_type,
        model_alias=task.model_alias,
        prompt=task.prompt,
        n=int(task.request.get("n") or 1),
        size=task.request.get("size"),
        quality=task.request.get("quality"),
        output_format=task.request.get("output_format") or "png",
        background=task.request.get("background") or "opaque",
        output_compression=task.request.get("output_compression"),
        response_format=task.request.get("response_format"),
        seed=task.request.get("seed"),
    )
    # Retries re-upload the original input images when the task was an edit.
    images = state.tasks.get_task_inputs(task_id)
    if images:
        req.images = [data for _, data in images]
        req.image_names = [name for name, _ in images]
    new_task = await state.engine.submit(req)
    runner = asyncio.create_task(state.engine.run(new_task, req))
    state.running[new_task.id] = runner
    runner.add_done_callback(lambda _t, tid=new_task.id: state.running.pop(tid, None))
    return {"ok": True, "task_id": new_task.id}


@router.get("/admin/api/tasks/{task_id}/inputs/{index}/raw")
async def input_image_raw(request: Request, task_id: str, index: int) -> Any:
    """Serve an uploaded input image (edit target / reference) for preview."""
    _require_session(request)
    state = request.app.state
    if state.tasks.get_task(task_id) is None:
        raise NotFoundError(f"no such task: {task_id}", code="task_not_found")
    item = state.tasks.get_input_image(task_id, index)
    if item is None:
        raise NotFoundError(f"task {task_id} has no input image #{index}", code="input_not_found")
    from pathlib import Path

    path = Path(item["path"])
    if not path.exists():
        raise NotFoundError("input image file is missing from storage", code="input_missing")
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type=item["mime_type"] or "application/octet-stream",
                        filename=item["filename"])


@router.delete("/admin/api/tasks/{task_id}")
async def delete_task(request: Request, task_id: str) -> dict[str, Any]:
    """Delete a task's artifacts and inputs from disk; keep a soft-deleted record."""
    _require_session(request)
    state = request.app.state
    task = state.tasks.get_task(task_id)
    if task is None:
        raise NotFoundError(f"no such task: {task_id}", code="task_not_found")
    runner = state.running.get(task_id)
    if runner is not None and not runner.done():
        await state.engine.cancel(task_id)
    freed = state.artifacts.delete_task_files(task_id)
    state.tasks.soft_delete_task(task_id)
    return {"ok": True, "task_id": task_id, "freed_bytes": freed}


@router.get("/admin/api/storage")
async def storage_stats(request: Request) -> dict[str, Any]:
    _require_session(request)
    state = request.app.state
    cfg = state.config.storage
    usage = state.artifacts.usage()
    return {
        "usage": usage,
        "limits": {
            "max_bytes": cfg.max_bytes,
            "artifact_ttl_days": cfg.artifact_ttl_days,
            "failed_retention_days": cfg.failed_retention_days,
            "sweep_interval_s": cfg.sweep_interval_s,
        },
    }


@router.post("/admin/api/storage/sweep")
async def storage_sweep(request: Request) -> dict[str, Any]:
    _require_session(request)
    state = request.app.state
    return {"ok": True, "removed": state.artifacts.sweep(), "usage": state.artifacts.usage()}


@router.get("/admin/api/artifacts/{artifact_id}/raw")
async def artifact_raw(request: Request, artifact_id: str) -> Any:
    _require_session(request)
    state = request.app.state
    art = state.tasks.get_artifact(artifact_id)
    if art is None:
        raise NotFoundError(f"no such artifact: {artifact_id}", code="artifact_not_found")
    path = state.artifacts.artifact_path(art)
    if not path.exists():
        raise NotFoundError("artifact file is missing", code="artifact_missing")
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type=art.mime_type, filename=art.filename)


@router.get("/admin/api/artifacts/{artifact_id}/thumb")
async def artifact_thumb(
    request: Request,
    artifact_id: str,
    size: int = Query(default=THUMB_SIZE_DEFAULT, ge=THUMB_SIZE_MIN, le=THUMB_SIZE_MAX),
) -> Any:
    """Cached JPEG thumbnail of an image artifact, or a video's first frame.

    Thumbnails are cached under ``<storage.root>/.thumbs``; a neutral placeholder
    is returned for video/audio when no frame can be decoded (ffmpeg optional).
    """
    _require_session(request)
    state = request.app.state
    result = await asyncio.to_thread(artifact_thumb_bytes, state, artifact_id, _clamp_size(size))
    if result is None:
        raise NotFoundError(f"no such artifact: {artifact_id}", code="artifact_not_found")
    data, cache_key = result
    return _thumb_response(data, cache_key)


@router.get("/admin/api/tasks/{task_id}/inputs/{index}/thumb")
async def input_thumb(
    request: Request,
    task_id: str,
    index: int,
    size: int = Query(default=THUMB_SIZE_DEFAULT, ge=THUMB_SIZE_MIN, le=THUMB_SIZE_MAX),
) -> Any:
    """Cached JPEG thumbnail of an uploaded input image."""
    _require_session(request)
    state = request.app.state
    if state.tasks.get_task(task_id) is None:
        raise NotFoundError(f"no such task: {task_id}", code="task_not_found")
    item = state.tasks.get_input_image(task_id, index)
    if item is None:
        raise NotFoundError(f"task {task_id} has no input image #{index}", code="input_not_found")
    path = Path(item["path"])
    if not path.exists():
        raise NotFoundError("input image file is missing from storage", code="input_missing")
    result = await asyncio.to_thread(input_thumb_bytes, state, task_id, item, _clamp_size(size))
    if result is None:
        raise NotFoundError("input image could not be decoded", code="input_unreadable")
    data, cache_key = result
    return _thumb_response(data, cache_key)


def input_thumb_bytes(state: Any, task_id: str, item: dict[str, Any], size: int) -> tuple[bytes, str] | None:
    """Return ``(jpeg_bytes, cache_key)`` for an uploaded input, cached on disk."""
    path = Path(item["path"])
    if not path.exists():
        return None
    stat = path.stat()
    cache_key = _thumb_cache_key(f"input:{task_id}:{item['index']}", size, stat.st_mtime, stat.st_size)
    data = _cached_thumb(state, cache_key, lambda: _image_thumb(path, size))
    if data is None:
        return None
    return data, cache_key


def _thumb_response(data: bytes, cache_key: str) -> Any:
    from fastapi.responses import Response

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": THUMB_CACHE_CONTROL,
            # The key already encodes artifact id, size and source mtime, so it is
            # a safe strong validator for conditional requests.
            "ETag": f'"{cache_key}"',
        },
    )


# -- config / health ---------------------------------------------------------


@router.get("/admin/api/config")
async def config_view(request: Request) -> dict[str, Any]:
    _require_session(request)
    cfg = request.app.state.config
    return {
        "server": {"host": cfg.server.host, "port": cfg.server.port,
                   "public_base_url": cfg.server.public_base_url,
                   "sync_timeout_s": cfg.server.sync_timeout_s,
                   "admin_path": cfg.server.admin_path},
        "backends": request.app.state.backends.describe(),
        "routing": {
            "unified_image_models": [
                {"alias": u.alias, "generate_task": u.generate_task, "edit_task": u.edit_task}
                for u in cfg.routing.unified_image_models
            ]
        },
        "tasks": {
            name: {
                "models": [
                    {
                        "alias": m.alias,
                        "backend": m.backend,
                        "template": m.template,
                        "fallbacks": m.fallbacks,
                        "mask_policy": m.mask_policy,
                        "constraints": m.constraints.model_dump(),
                    }
                    for m in task.models
                ]
            }
            for name, task in cfg.tasks.items()
        },
    }


@router.get("/admin/api/health")
async def health(request: Request) -> dict[str, Any]:
    _require_session(request)
    state = request.app.state
    backends = await state.backends.health_all()
    return {
        "version": state.version,
        # Monotonic clock: wall-clock would jump on NTP/suspend adjustments.
        "uptime_s": max(0.0, time.monotonic() - state.started_monotonic),
        "tasks": state.tasks.counts_by_status(),
        "active": len(state.running),
        "queues": state.engine.queue_stats(),
        "backends": backends,
        "auth_enabled": state.auth.config.enabled,
    }


# -- config hot reload -------------------------------------------------------

RELOADABLE_SECTIONS = ("tasks", "routing", "backends")
RESTART_ONLY_SECTIONS = ("server", "auth", "storage")


def _diff_sections(old: Any, new: Any) -> list[str]:
    changed = []
    for name in ("server", "auth", "storage"):
        if getattr(old, name).model_dump() != getattr(new, name).model_dump():
            changed.append(name)
    return changed


@router.post("/admin/api/config/reload")
async def reload_config(request: Request) -> dict[str, Any]:
    """Reload tasks/routing/backends from the config file.

    The new file is fully validated (including workflow templates and reference
    checks) before anything is swapped in; on failure the running configuration is
    left untouched. Changes to server/auth/storage are reported but require a
    restart.
    """
    _require_session(request)
    state = request.app.state
    path = getattr(state, "config_path", None)
    base_dir = getattr(state, "base_dir", None)
    if not path:
        raise BadRequestError("this process was not started with a config path", code="reload_unavailable")

    from .config import load_config

    try:
        new_cfg = load_config(path, base_dir=base_dir)
    except Exception as exc:  # noqa: BLE001 - validation failure keeps old config
        raise BadRequestError(f"config reload failed, keeping current config: {exc}",
                              code="config_invalid") from exc

    old_cfg = state.config
    restart_required = _diff_sections(old_cfg, new_cfg)

    active_backends = {t.backend_id for t in state.tasks.active_tasks()}
    await state.backends.replace(new_cfg, keep=active_backends)
    state.engine.apply_config(new_cfg)
    state.config = new_cfg
    state._app_state.config = new_cfg  # noqa: SLF001 - shared state object

    return {
        "ok": True,
        "restart_required": restart_required,
        "applied": list(RELOADABLE_SECTIONS),
        "backends": [b.id for b in new_cfg.backends],
        "tasks": {name: [m.alias for m in task.models] for name, task in new_cfg.tasks.items()},
    }


# -- live events -------------------------------------------------------------


@router.get("/admin/api/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent events: task state changes, so the UI stays live."""
    _require_session(request)
    state = request.app.state

    async def gen():
        last: dict[str, tuple[str, int]] = {}
        while True:
            tasks, _ = state.tasks.list_tasks(limit=100)
            for t in tasks:
                cur = (t.status, t.progress)
                if last.get(t.id) != cur:
                    last[t.id] = cur
                    payload = {
                        "id": t.id, "status": t.status, "progress": t.progress,
                        "stage": t.stage, "model_alias": t.model_alias,
                        "error_code": (t.error or {}).get("code"),
                    }
                    yield f"event: task\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield f"event: ping\ndata: {int(time.time())}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(gen(), media_type="text/event-stream")
