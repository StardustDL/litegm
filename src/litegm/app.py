"""Application wiring: FastAPI app, lifecycle, error handling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError as PydanticValidationError
from starlette.middleware.gzip import GZipMiddleware

from . import __version__, api
from .admin import router as admin_router
from .audio import router as audio_router
from .auth import Authenticator
from .backends import BackendRegistry
from .config import Config, load_config
from .docs_discovery import llms_txt, openapi_extras, swagger_html
from .observability import RequestLoggingMiddleware, router as observability_router
from .video import router as video_router
from .engine import Engine
from .errors import BadRequestError, ConfigError, LiteGMError, ValidationError
from .storage import ArtifactStore
from .store import TaskStore

log = logging.getLogger(__name__)

# Responses at or above this size are gzipped (admin JSON task details are ~16 KB).
# Starlette's gate only skips a body delivered as a single ASGI message, so no
# BaseHTTPMiddleware may sit below the gzip layer (RequestLoggingMiddleware is a
# plain ASGI middleware for exactly that reason).
GZIP_MIN_SIZE = 1024
# Vite emits content-hashed filenames under assets/, so they never change in place.
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
NO_CACHE_CONTROL = "no-cache"


class AdminUIAssets(StaticFiles):
    """StaticFiles with cache headers suited to a hashed SPA build.

    Files under ``assets/`` carry a content hash in their name and are cached
    forever; the HTML entry point and anything else must revalidate so a new
    build is picked up immediately.
    """

    def file_response(
        self,
        full_path: Any,
        stat_result: Any,
        scope: Any,
        status_code: int = 200,
    ) -> Any:
        response = super().file_response(full_path, stat_result, scope, status_code)
        # NotModifiedResponse is a plain Response; its headers are copied, so the
        # cache policy below applies to 304 responses too.
        name = Path(str(full_path)).name.lower()
        if _is_hashed_asset(str(full_path)):
            response.headers["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
        elif name.endswith((".html", ".htm")):
            response.headers["Cache-Control"] = NO_CACHE_CONTROL
        else:
            # Unhashed extras (icons, manifests): cache briefly, revalidate often.
            response.headers["Cache-Control"] = "public, max-age=300"
        return response


def _is_hashed_asset(full_path: str) -> bool:
    """True for content-hashed build output such as ``assets/index-AbC123.js``."""
    parts = Path(full_path).parts
    if "assets" not in parts:
        return False
    name = Path(full_path).name
    stem = name.rsplit(".", 1)[0]
    return "-" in stem and len(stem.rsplit("-", 1)[-1]) >= 6


class AppState:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.auth = Authenticator(config.auth)
        self.tasks = TaskStore(config.storage_root() / "litegm.db")
        self.artifacts = ArtifactStore(config, self.tasks)
        self.backends = BackendRegistry(config)
        self.engine = Engine(config, self.backends, self.tasks, self.artifacts)
        self.running: dict[str, asyncio.Task[Any]] = {}
        self.version = __version__
        self.started_at = 0.0
        self.started_monotonic = time.monotonic()
        self._sweeper: asyncio.Task[Any] | None = None

    async def startup(self) -> None:
        self.started_at = time.time()
        self.started_monotonic = time.monotonic()
        # Anything left running by a previous process is re-checked against ComfyUI.
        n = self.tasks.mark_interrupted()
        if n:
            log.info("resuming %d interrupted task(s)", n)
        for task in self.tasks.active_tasks():
            if task.comfy_prompt_id:
                asyncio.create_task(self._resume(task.id))
        self.artifacts.sweep()
        self._sweeper = asyncio.create_task(self._sweep_loop())

    async def _sweep_loop(self) -> None:
        """Periodic retention sweep (TTL + disk budget)."""
        interval = max(60, self.config.storage.sweep_interval_s)
        while True:
            try:
                await asyncio.sleep(interval)
                result = self.artifacts.sweep()
                if any(result[k] for k in ("artifacts", "input_images")):
                    log.info("retention sweep removed %s", result)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let the sweeper die
                log.exception("retention sweep failed")

    async def _resume(self, task_id: str) -> None:
        """Re-attach to a ComfyUI prompt submitted before a restart."""
        task = self.tasks.get_task(task_id)
        if task is None or not task.comfy_prompt_id:
            return
        client = self.backends.get(task.backend_id)
        try:
            entry = await client.wait_for(task.comfy_prompt_id, timeout_s=self.config.server.sync_timeout_s)
        except LiteGMError as exc:
            self.tasks.update_task(task_id, status="failed", stage="failed",
                                   error={"code": exc.code, "message": exc.message, "status": exc.status})
            return
        from .comfy import iter_output_files

        files = iter_output_files(entry.outputs)
        if entry.failed or not files:
            msg = entry.error_text() if entry.failed else "no output files"
            self.tasks.update_task(task_id, status="failed", stage="failed",
                                   error={"code": "comfy_execution_error", "message": msg, "status": 422})
            return
        for f in files:
            data = await client.download(f)
            kind = "image"
            self.artifacts.save(task_id=task_id, filename=f.filename, data=data, kind=kind,
                                meta={"resumed": True, "prompt_id": task.comfy_prompt_id})
        self.tasks.update_task(task_id, status="succeeded", stage="completed", progress=100)

    async def shutdown(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
        for t in list(self.running.values()):
            t.cancel()
        await self.backends.aclose()
        self.tasks.close()


def create_app(config: Config) -> FastAPI:
    state = AppState(config)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.startup()
        try:
            yield
        finally:
            await state.shutdown()

    app = FastAPI(
        title="litegm",
        version=__version__,
        description="OpenAI-compatible media generation gateway for ComfyUI.",
        lifespan=lifespan,
        # Discovery routes are registered explicitly below (they are generated
        # from live state and must stay outside the static schema).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.auth = state.auth
    app.state.tasks = state.tasks
    app.state.artifacts = state.artifacts
    app.state.backends = state.backends
    app.state.engine = state.engine
    app.state.running = state.running
    app.state.version = state.version
    app.state.started_at = 0.0
    app.state.started_monotonic = time.monotonic()
    app.state.config_path = None
    app.state.base_dir = None
    app.state._app_state = state

    # Middleware order: the last added is the outermost. Request logging is a
    # plain ASGI middleware that forwards bodies untouched, so GZip added after
    # it wraps the whole stack and its minimum_size gate works as documented.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_SIZE)

    @app.exception_handler(LiteGMError)
    async def _litegm_error(request: Request, exc: LiteGMError) -> JSONResponse:
        return await api.litegm_error_handler(request, exc)

    @app.exception_handler(ConfigError)
    async def _config_error(request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(exc.to_openai(), status_code=500)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = [str(p) for p in first.get("loc", []) if p != "body"]
        param = loc[0] if loc else None
        msg = first.get("msg", "invalid request")
        err = ValidationError(f"{'.'.join(loc)}: {msg}" if loc else msg, param=param)
        return JSONResponse(err.to_openai(), status_code=400)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            {"error": {"type": "server_error", "code": "internal_error",
                       "message": f"{type(exc).__name__}: {exc}", "param": None}},
            status_code=500,
        )

    app.include_router(api.router)
    app.include_router(video_router)
    app.include_router(audio_router)
    app.include_router(admin_router)
    app.include_router(observability_router)

    # -- discovery documents for agents -------------------------------------
    # These describe the API rather than act on it, so they need no bearer
    # token; the master key itself is never rendered into them. Requests are
    # answered from the live app state, so a config hot reload is reflected
    # immediately in /llms.txt and /openapi.json.

    @app.get("/llms.txt", include_in_schema=False)
    async def _llms_txt(request: Request) -> PlainTextResponse:
        return PlainTextResponse(
            llms_txt(request.app.state, base_url=_request_base(request)),
            media_type="text/markdown; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/swagger-ui", include_in_schema=False)
    @app.get("/docs", include_in_schema=False)
    async def _swagger_ui() -> HTMLResponse:
        return HTMLResponse(
            swagger_html(openapi_url="/openapi.json", llms_url="/llms.txt"),
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/openapi.json", include_in_schema=False)
    async def _openapi(request: Request) -> JSONResponse:
        doc = openapi_extras(request.app, base_url=_request_base(request))
        return JSONResponse(doc, headers={"Cache-Control": "no-cache"})

    # Static admin UI (built assets), served from the configured path.
    static_dir = _static_dir()
    admin_path = config.server.admin_path
    if static_dir is not None:
        app.mount(admin_path, AdminUIAssets(directory=static_dir, html=True), name="admin-ui")

        @app.get(admin_path)
        async def _admin_root() -> RedirectResponse:  # pragma: no cover - static handles index
            return RedirectResponse(f"{admin_path}/")

    return app


def _request_base(request: Request) -> str:
    """Absolute base URL derived from the request, so links work on any port.

    Mirrors ``admin._request_base_url``: the configured ``public_base_url`` is
    only a fallback, because a deployment reachable under another host/port
    (LAN IP, reverse proxy, several instances) must not hand out unusable links.
    """
    host = request.headers.get("host")
    if host:
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        return f"{scheme}://{host}"
    return str(request.app.state.config.server.public_base_url).rstrip("/")


def _static_dir() -> Path | None:
    env = os.environ.get("LITEGM_WEB_DIR")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(Path(__file__).resolve().parents[2] / "web" / "dist")
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def app_from_env() -> FastAPI:
    """ASGI factory for servers that import an app object directly."""
    cfg_path = os.environ.get("LITEGM_CONFIG")
    if not cfg_path:
        raise ConfigError("LITEGM_CONFIG is not set")
    base_dir = os.environ.get("LITEGM_BASE_DIR") or os.getcwd()
    cfg = load_config(cfg_path, base_dir=base_dir)
    configure_logging(cfg.server.log_level)
    app = create_app(cfg)
    app.state.config_path = cfg_path
    app.state.base_dir = base_dir
    return app
