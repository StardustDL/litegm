"""Tests for the v4 admin UI support endpoints: thumbnails, previews, gzip.

These are pure unit tests: no ComfyUI is contacted. The app is built from the
``config`` fixture and artifacts are written through ``ArtifactStore`` so the
real storage layout (and its on-disk thumbnail cache) is exercised.
"""

from __future__ import annotations

import base64
import asyncio
import gzip
import io
import json
import struct
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from litegm import admin
from litegm.app import GZIP_MIN_SIZE, create_app
from litegm.storage import ArtifactStore

ROOT = Path(__file__).resolve().parents[1]


# -- helpers -----------------------------------------------------------------


def _png(width: int = 320, height: int = 200, color=(200, 60, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _minimal_mp4(width: int = 640, height: int = 360) -> bytes:
    """A tiny MP4 header: ftyp + moov/mvhd + moov/trak/tkhd (no media data).

    Enough for ``_video_dimensions`` and for the placeholder path when ffmpeg is
    absent; no codec is decoded here.
    """
    ftyp = struct.pack(">I", 32) + b"ftypisom" + b"\x00\x00\x02\x00" + b"isomiso2avc1mp41"
    mvhd_payload = b"\x00" * 100
    mvhd = struct.pack(">I", 8 + len(mvhd_payload)) + b"mvhd" + mvhd_payload
    # tkhd payload: version/flags(4) + creation(4) + modification(4) + track id(4)
    # + reserved(4) + duration(4) + reserved(8) + layer(2) + alt group(2)
    # + volume(2) + reserved(2) + matrix(36) + width(4) + height(4) = 84 bytes.
    tkhd_payload = (
        b"\x00" * 4 + b"\x00" * 4 + b"\x00" * 4 + b"\x00\x00\x00\x01"
        + b"\x00" * 4 + b"\x00" * 4 + b"\x00" * 8 + b"\x00" * 2
        + b"\x00" * 2 + b"\x00" * 2 + b"\x00" * 2 + b"\x00" * 36
        + struct.pack(">I", width << 16) + struct.pack(">I", height << 16)
    )
    assert len(tkhd_payload) == 84
    tkhd = struct.pack(">I", 8 + len(tkhd_payload)) + b"tkhd" + tkhd_payload
    trak = struct.pack(">I", 8 + len(tkhd)) + b"trak" + tkhd
    moov = struct.pack(">I", 8 + len(mvhd) + len(trak)) + b"moov" + mvhd + trak
    return ftyp + moov


@pytest.fixture
def app_state(config, workdir):
    """Build the real app (auth disabled so admin routes are session-free).

    The app opens the store at ``<storage.root>/litegm.db``; the fixtures below
    use that same database so data written by a test is visible to the app.
    """
    config.auth.enabled = False
    app = create_app(config)
    return app


@pytest.fixture
def client(app_state):
    with TestClient(app_state) as c:
        yield c


@pytest.fixture
def store_and_arts(config, workdir):
    from litegm.store import TaskStore

    store = TaskStore(config.storage_root() / "litegm.db")
    arts = ArtifactStore(config, store)
    try:
        yield store, arts
    finally:
        store.close()


def _make_task(store, *, status="succeeded", started_at=None, finished_at=None):
    task = store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                             prompt="a red fox", request={}, status=status)
    updates = {}
    if started_at is not None:
        updates["started_at"] = started_at
    if finished_at is not None:
        updates["finished_at"] = finished_at
    if updates:
        store.update_task(task.id, **updates)
    return task


def _add_input(store, arts, task_id: int, index: int = 0) -> dict:
    data = _png(160, 120, (40, 120, 200))
    path = arts.uploads_dir / f"{task_id}_in_{index}.png"
    path.write_bytes(data)
    store.add_input_image(task_id, index, f"in_{index}.png", str(path), len(data),
                          mime_type="image/png", width=160, height=120, role="target")
    return store.get_input_image(task_id, index)


# -- thumbnail endpoint ------------------------------------------------------


def test_image_artifact_thumb_is_jpeg_and_cached(client, store_and_arts, config):
    store, arts = store_and_arts
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.png", data=_png(320, 200), kind="image")

    r = client.get(f"/admin/api/artifacts/{art.id}/thumb")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert r.content[:2] == b"\xff\xd8", "not a JPEG"
    im = Image.open(io.BytesIO(r.content))
    assert max(im.size) <= admin.THUMB_SIZE_DEFAULT

    # The cache file must exist under the storage root, not in a temp directory.
    cache_dir = config.storage_root() / admin.THUMB_DIR_NAME
    cached = list(cache_dir.glob("*.jpg"))
    assert cached, "thumbnail was not cached on disk"
    assert cached[0].read_bytes() == r.content

    # A second request is served from the cache: identical bytes and ETag.
    r2 = client.get(f"/admin/api/artifacts/{art.id}/thumb")
    assert r2.status_code == 200
    assert r2.content == r.content
    assert r2.headers["etag"] == r.headers["etag"]


def test_thumb_size_is_bounded(client, store_and_arts):
    store, arts = store_and_arts
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.png", data=_png(800, 600), kind="image")

    r = client.get(f"/admin/api/artifacts/{art.id}/thumb?size=96")
    assert r.status_code == 200
    im = Image.open(io.BytesIO(r.content))
    assert max(im.size) <= 96

    # Out-of-range sizes are rejected by validation rather than silently clamped.
    assert client.get(f"/admin/api/artifacts/{art.id}/thumb?size=16").status_code == 400
    assert client.get(f"/admin/api/artifacts/{art.id}/thumb?size=4096").status_code == 400


def test_video_artifact_thumb_uses_placeholder_without_ffmpeg(
    client, store_and_arts, config, monkeypatch
):
    store, arts = store_and_arts
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.mp4", data=_minimal_mp4(), kind="video")
    # ffmpeg is optional; pretend it is not installed so the placeholder path runs.
    monkeypatch.setattr(admin, "_find_ffmpeg", lambda: None)

    r = client.get(f"/admin/api/artifacts/{art.id}/thumb?size=128")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    assert max(im.size) <= 128
    # The placeholder is neutral (near-uniform ink), not a random frame. The
    # film-frame glyph is a small fraction of the canvas, so the corners carry
    # the flat background colour.
    corners = [im.getpixel((2, 2)), im.getpixel((im.width - 3, 2)),
               im.getpixel((2, im.height - 3)), im.getpixel((im.width - 3, im.height - 3))]
    for c in corners:
        assert all(abs(a - b) <= 6 for a, b in zip(c, corners[0])), corners
    assert max(corners[0]) < 60, "placeholder should be dark ink, not a video frame"
    assert any((config.storage_root() / admin.THUMB_DIR_NAME).glob("*.jpg"))


def test_video_artifact_thumb_uses_ffmpeg_when_available(client, store_and_arts, monkeypatch):
    """When ffmpeg is present, its frame is used instead of the placeholder."""
    store, arts = store_and_arts
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.mp4", data=_minimal_mp4(), kind="video")

    monkeypatch.setattr(admin, "_find_ffmpeg", lambda: "ffmpeg")
    # Stand in for the ffmpeg process: write a recognisable frame to the output path.
    def fake_run(argv, **_kw):
        out = Path(argv[-1])
        Image.new("RGB", (64, 64), (10, 240, 10)).save(out, format="PNG")
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr(admin.subprocess, "run", fake_run)
    r = client.get(f"/admin/api/artifacts/{art.id}/thumb")
    assert r.status_code == 200
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    r0, g0, b0 = im.getpixel((im.width // 2, im.height // 2))
    assert g0 > 200 and r0 < 60, "ffmpeg frame was not used"


def test_audio_artifact_thumb_is_placeholder(client, store_and_arts):
    store, arts = store_and_arts
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.flac", data=b"fLaC" + b"\x00" * 64, kind="audio")
    r = client.get(f"/admin/api/artifacts/{art.id}/thumb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"


def test_thumb_404_for_unknown_artifact_and_missing_file(client, store_and_arts):
    assert client.get("/admin/api/artifacts/art_doesnotexist/thumb").status_code == 404

    store, arts = store_and_arts
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.png", data=_png(), kind="image")
    Path(art.path).unlink()
    r = client.get(f"/admin/api/artifacts/{art.id}/thumb")
    assert r.status_code == 404


def test_thumb_requires_session(config, workdir, master_key):
    config.auth.enabled = True
    config.auth.master_key = master_key
    from litegm.store import TaskStore

    store = TaskStore(config.storage_root() / "litegm.db")
    arts = ArtifactStore(config, store)
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.png", data=_png(), kind="image")
    basic = base64.b64encode(f"admin:{master_key}".encode()).decode()
    try:
        app = create_app(config)
        with TestClient(app) as c:
            assert c.get(f"/admin/api/artifacts/{art.id}/thumb").status_code == 401
            assert c.get(f"/admin/api/tasks/{task.id}/inputs/0/thumb").status_code == 401
            login = c.post("/admin/api/login", headers={"Authorization": f"Basic {basic}"})
            assert login.status_code == 200, login.text
            assert c.get(f"/admin/api/artifacts/{art.id}/thumb").status_code == 200
            # The input route is gated too: no inputs -> 404, not 401.
            assert c.get(f"/admin/api/tasks/{task.id}/inputs/0/thumb").status_code == 404
    finally:
        store.close()


def test_video_dimensions_parses_real_mp4_samples(workdir):
    """Exercise the tkhd parser against real MP4s from data/artifacts, if present."""
    samples = sorted((ROOT / "data" / "artifacts").rglob("*.mp4"))
    if not samples:
        pytest.skip("no real MP4 samples under data/artifacts")
    for sample in samples[:4]:
        width, height = admin._video_dimensions(sample)  # noqa: SLF001
        assert width and height, f"no dimensions parsed from {sample.name}"
        # The samples are 864x480; assert on the plausible range rather than a
        # hard-coded size so a different generation is not a test failure.
        assert 64 <= width <= 4096 and 64 <= height <= 4096


def test_video_dimensions_handles_corrupt_and_short_files(workdir):
    cases = {
        "empty.mp4": b"",
        "short.mp4": b"\x00\x00\x00\x08tkhd",
        "garbage.mp4": b"not an mp4 at all" * 100,
        "truncated.mp4": _minimal_mp4()[:20],
        # tkhd present but the box payload is too short for width/height.
        "stub_tkhd.mp4": b"\x00\x00\x00\x08tkhd" + b"\x00" * 40,
    }
    for name, data in cases.items():
        p = workdir / name
        p.write_bytes(data)
        assert admin._video_dimensions(p) == (None, None), name  # noqa: SLF001
    assert admin._video_dimensions(workdir / "missing.mp4") == (None, None)  # noqa: SLF001


def test_video_preview_falls_back_when_dimensions_unparseable(client, store_and_arts):
    store, arts = store_and_arts
    task = _make_task(store)
    arts.save(task_id=task.id, filename="out.mp4", data=b"\x00" * 64, kind="video")
    r = client.get("/admin/api/tasks")
    item = next(i for i in r.json()["items"] if i["id"] == task.id)
    assert item["preview"]["kind"] == "video"
    assert item["preview"]["width"] is None and item["preview"]["height"] is None
    # The thumbnail endpoint still answers with a placeholder.
    assert client.get(item["preview"]["url"]).status_code == 200


def test_list_previews_batch_query_and_stay_fast(client, store_and_arts):
    """The list view must not issue per-task queries; 100 rows stay well under 100 ms."""
    store, arts = store_and_arts
    png = _png(64, 64)
    for i in range(100):
        task = _make_task(store, started_at=time.time() - i, finished_at=time.time())
        arts.save(task_id=task.id, filename=f"out_{i}.png", data=png, kind="image")
        _add_input(store, arts, task.id, 0)

    queries: list[str] = []
    from sqlalchemy import event

    engine = store._engine  # noqa: SLF001 - test-only instrumentation

    def _record(_conn, _cursor, statement, _params, _ctx, _many):  # noqa: ANN001
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        started = time.perf_counter()
        r = client.get("/admin/api/tasks?limit=100")
        elapsed = time.perf_counter() - started
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 100
    assert all(i["preview"] and i["input_preview"] for i in items)
    # One query for the task page, one for artifacts, one for input images.
    assert len(queries) <= 4, queries
    assert elapsed < 0.1, f"list of 100 rows took {elapsed * 1000:.1f} ms"


# -- input thumb endpoint ----------------------------------------------------


def test_input_thumb(client, store_and_arts):
    store, arts = store_and_arts
    task = _make_task(store)
    _add_input(store, arts, task.id, 0)

    r = client.get(f"/admin/api/tasks/{task.id}/inputs/0/thumb?size=64")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=86400"
    im = Image.open(io.BytesIO(r.content))
    assert max(im.size) <= 64
    assert client.get(f"/admin/api/tasks/{task.id}/inputs/3/thumb").status_code == 404
    assert client.get("/admin/api/tasks/task_nope/inputs/0/thumb").status_code == 404


# -- list previews -----------------------------------------------------------


def test_list_items_gain_preview_fields(client, store_and_arts):
    store, arts = store_and_arts
    task = _make_task(store, started_at=time.time() - 30, finished_at=time.time())
    art = arts.save(task_id=task.id, filename="out.png", data=_png(300, 150), kind="image")
    _add_input(store, arts, task.id, 0)

    r = client.get("/admin/api/tasks")
    assert r.status_code == 200
    body = r.json()
    item = next(i for i in body["items"] if i["id"] == task.id)

    # Existing keys are untouched.
    for key in ("id", "task_type", "status", "stage", "progress", "model_alias",
                "backend_id", "prompt", "created_at", "finished_at", "error_code",
                "artifact_count", "suspicious"):
        assert key in item
    assert item["artifact_count"] == 1

    preview = item["preview"]
    assert preview["kind"] == "image"
    assert preview["url"].startswith(f"/admin/api/artifacts/{art.id}/thumb?size=")
    assert preview["width"] == 300 and preview["height"] == 150

    inp = item["input_preview"]
    assert inp["kind"] == "image"
    assert inp["url"].startswith(f"/admin/api/tasks/{task.id}/inputs/0/thumb?size=")
    assert inp["width"] == 160 and inp["height"] == 120

    # The advertised URLs actually resolve.
    assert client.get(preview["url"]).status_code == 200
    assert client.get(inp["url"]).status_code == 200


def test_list_previews_are_null_without_media(client, store_and_arts):
    store, _arts = store_and_arts
    task = _make_task(store, status="failed")
    r = client.get("/admin/api/tasks")
    item = next(i for i in r.json()["items"] if i["id"] == task.id)
    assert item["preview"] is None
    assert item["input_preview"] is None


def test_list_video_preview_reports_dimensions(client, store_and_arts):
    store, arts = store_and_arts
    task = _make_task(store)
    art = arts.save(task_id=task.id, filename="out.mp4", data=_minimal_mp4(640, 360), kind="video")
    r = client.get("/admin/api/tasks")
    item = next(i for i in r.json()["items"] if i["id"] == task.id)
    assert item["preview"]["kind"] == "video"
    assert item["preview"]["width"] == 640
    assert item["preview"]["height"] == 360
    assert item["preview"]["url"].startswith(f"/admin/api/artifacts/{art.id}/thumb")


# -- task detail -------------------------------------------------------------


def test_task_detail_duration_and_previews(client, store_and_arts):
    store, arts = store_and_arts
    started = time.time() - 42.5
    finished = time.time()
    task = _make_task(store, started_at=started, finished_at=finished)
    art = arts.save(task_id=task.id, filename="out.png", data=_png(), kind="image")

    r = client.get(f"/admin/api/tasks/{task.id}")
    assert r.status_code == 200
    body = r.json()
    # Existing keys kept.
    for key in ("id", "task_type", "status", "stage", "progress", "model_alias",
                "backend_id", "prompt", "request", "comfy_prompt_id", "error",
                "attempts", "created_at", "started_at", "finished_at",
                "cancel_requested", "input_images", "artifacts", "workflow", "events"):
        assert key in body
    assert abs(body["duration_s"] - (finished - started)) < 0.01
    assert body["artifact_previews"][0]["id"] == art.id
    assert body["artifact_previews"][0]["artifact_url"] == f"/admin/api/artifacts/{art.id}/raw"


def test_task_detail_duration_null_while_unfinished(client, store_and_arts):
    store, _arts = store_and_arts
    running = _make_task(store, status="running", started_at=time.time())
    body = client.get(f"/admin/api/tasks/{running.id}").json()
    assert body["duration_s"] is None

    queued = _make_task(store, status="queued")
    body = client.get(f"/admin/api/tasks/{queued.id}").json()
    assert body["duration_s"] is None
    assert body["artifact_previews"] == []


def test_signed_url_follows_request_host_not_configured_public_url(client, store_and_arts, config):
    """Signed links must work on whatever host/port the operator actually serves.

    ``public_base_url`` is a single configured value; using it verbatim breaks
    local debugging on another port and multi-instance setups. The detail
    endpoint therefore derives the base from the request's own Host header.
    """
    store, arts = store_and_arts
    task = _make_task(store, started_at=time.time() - 3, finished_at=time.time())
    art = arts.save(task_id=task.id, filename="out.flac", data=b"fLaC" + b"\x00" * 64, kind="audio")
    # A configured value that does not match the host the client uses.
    config.server.public_base_url = "http://192.0.2.10:9999"

    r = client.get(f"/admin/api/tasks/{task.id}", headers={"Host": "127.0.0.1:8081"})
    assert r.status_code == 200
    signed = r.json()["artifacts"][0]["signed_url"]
    assert signed.startswith("http://127.0.0.1:8081/v1/files/"), signed
    assert art.id in signed
    assert "expires=" in signed and "sig=" in signed
    assert "192.0.2.10" not in signed


def test_signed_url_honours_forwarded_proto(client, store_and_arts):
    """Behind a TLS-terminating proxy the link must use https, not http."""
    store, arts = store_and_arts
    task = _make_task(store)
    arts.save(task_id=task.id, filename="out.png", data=_png(), kind="image")

    r = client.get(
        f"/admin/api/tasks/{task.id}",
        headers={"Host": "gm.example.com", "X-Forwarded-Proto": "https"},
    )
    signed = r.json()["artifacts"][0]["signed_url"]
    assert signed.startswith("https://gm.example.com/v1/files/"), signed


def test_signed_url_falls_back_to_config_without_host(config):
    """No Host header at all: the configured public URL is still used."""
    from litegm.store import TaskStore

    config.auth.enabled = False
    store = TaskStore(config.storage_root() / "litegm.db")
    arts = ArtifactStore(config, store)
    task = _make_task(store)
    arts.save(task_id=task.id, filename="out.png", data=_png(), kind="image")
    try:
        app = create_app(config)
        # ASGI scope with an empty Host header.
        body = asyncio.run(_raw_asgi(app, f"/admin/api/tasks/{task.id}",
                                     host=None))
        signed = json.loads(body["body"])["artifacts"][0]["signed_url"]
        assert signed.startswith(config.server.public_base_url.rstrip("/") + "/v1/files/"), signed
    finally:
        store.close()


# -- gzip / static cache headers --------------------------------------------


def test_gzip_compresses_large_admin_json(client, store_and_arts):
    store, arts = store_and_arts
    task = _make_task(store, started_at=time.time() - 5, finished_at=time.time())
    arts.save(task_id=task.id, filename="out.png", data=_png(), kind="image")
    # Pad the payload well past the 1 KB threshold.
    store.update_task(task.id, workflow={"nodes": {str(i): {"class_type": "X"} for i in range(300)}})

    r = client.get(f"/admin/api/tasks/{task.id}", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert "accept-encoding" in r.headers.get("vary", "").lower()
    # The decoded body is the real JSON.
    assert r.json()["id"] == task.id
    raw = client.get(f"/admin/api/tasks/{task.id}", headers={"Accept-Encoding": "identity"})
    assert raw.headers.get("content-encoding") is None
    assert len(raw.content) > GZIP_MIN_SIZE
    # The TestClient transparently decodes gzip, so compare against a
    # gzip-compressed copy of the same body instead of the response headers.
    compressed = gzip.compress(raw.content)
    assert len(compressed) < len(raw.content) / 2


def test_gzip_leaves_small_responses_alone(config):
    # This Starlette's TestClient negotiates gzip itself, so assert on the raw ASGI
    # messages instead of the client's normalised headers.
    config.auth.enabled = False
    app = create_app(config)
    with TestClient(app) as c:
        assert len(c.get("/admin/api/me").content) < GZIP_MIN_SIZE

    small = asyncio.run(_raw_asgi(app, "/admin/api/me"))
    assert small["status"] == 200
    assert json.loads(small["body"])["authenticated"] is True
    assert len(small["body"]) < GZIP_MIN_SIZE
    assert small["headers"].get("content-encoding") is None

    big = asyncio.run(_raw_asgi(app, "/admin/api/config"))
    assert big["status"] == 200
    assert big["headers"].get("content-encoding") == "gzip"
    assert len(big["body"]) > GZIP_MIN_SIZE
    assert json.loads(big["body"])["server"]["admin_path"] == "/admin"


async def _raw_asgi(app: Any, path: str, *, host: str | None = "127.0.0.1") -> dict[str, Any]:
    """Drive the ASGI app directly so response headers are not normalised."""
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    headers = [(b"accept-encoding", b"gzip")]
    if host is not None:
        headers.insert(0, (b"host", host.encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "app": app,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8080),
        "headers": headers,
    }
    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    if headers.get("content-encoding") == "gzip":
        body = gzip.decompress(body)
    return {"status": start["status"], "headers": headers, "body": body}


def test_static_assets_cache_policy(config, workdir, monkeypatch):
    dist = workdir / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>litegm</title>", encoding="utf-8")
    (dist / "assets" / "index-AbCdEf12.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "assets" / "index-Zz09Yy87.css").write_text("body{}", encoding="utf-8")
    config.auth.enabled = False
    # _static_dir() honours LITEGM_WEB_DIR, so create_app mounts the test build.
    monkeypatch.setenv("LITEGM_WEB_DIR", str(dist))
    app = create_app(config)
    with TestClient(app) as c:
        js = c.get("/admin/assets/index-AbCdEf12.js")
        assert js.status_code == 200
        assert js.headers["cache-control"] == "public, max-age=31536000, immutable"
        css = c.get("/admin/assets/index-Zz09Yy87.css")
        assert css.headers["cache-control"] == "public, max-age=31536000, immutable"
        idx = c.get("/admin/")
        assert idx.status_code == 200
        assert idx.headers["cache-control"] == "no-cache"
        assert "immutable" not in idx.headers["cache-control"]
