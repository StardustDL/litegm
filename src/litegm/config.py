"""Configuration loading and validation.

The whole gateway is driven by one YAML file. Nothing about a specific ComfyUI
server, workflow or model name is hard-coded in Python: backends, model aliases,
workflow templates and injection points all come from configuration.

Secrets may be written as ``env:NAME`` to be resolved from the environment at
load time, so they need not live in the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .errors import ConfigError

_ENV_RE = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")

# Repository root of this package (``src/litegm/config.py`` → three levels up).
_BUNDLED_ROOT = Path(__file__).resolve().parents[2]

SizePolicy = Literal["auto", "explicit", "auto_or_explicit"]
MaskPolicy = Literal["unsupported", "supported"]


def _resolve_secret(value: str, field_name: str) -> str:
    m = _ENV_RE.match(value)
    if not m:
        return value
    env_name = m.group(1)
    resolved = os.environ.get(env_name)
    if not resolved:
        raise ConfigError(f"{field_name} references environment variable {env_name!r} which is not set")
    return resolved


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    public_base_url: str = "http://127.0.0.1:8080"
    sync_timeout_s: float = 600.0
    admin_path: str = "/admin"
    log_level: str = "info"

    @field_validator("admin_path")
    @classmethod
    def _admin_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("admin_path must start with '/'")
        return v.rstrip("/") or "/admin"


class AuthConfig(BaseModel):
    username: str
    master_key: str
    session_ttl_s: int = 12 * 3600
    enabled: bool = True
    """Set to false for local development / screenshots: no Bearer or session
    check is performed. Never disable it on a shared or public deployment."""

    @field_validator("master_key")
    @classmethod
    def _master_key(cls, v: str) -> str:
        resolved = _resolve_secret(v, "auth.master_key")
        if len(resolved) < 8:
            raise ValueError("master_key must be at least 8 characters")
        return resolved

    @model_validator(mode="after")
    def _env_override(self) -> "AuthConfig":
        flag = os.environ.get("LITEGM_AUTH_DISABLED")
        if flag is not None:
            self.enabled = flag.strip().lower() not in ("1", "true", "yes", "on")
        return self


class StorageConfig(BaseModel):
    root: str = "./data"
    artifact_ttl_days: int = 30
    download_url_ttl_s: int = 3600
    max_bytes: int | None = None
    """Optional disk budget for artifacts/uploads; oldest items are evicted (LRU)
    once usage exceeds it."""
    failed_retention_days: int | None = None
    """Failed/cancelled tasks keep their artifacts longer (defaults to 2x the TTL)."""
    sweep_interval_s: int = 900
    """How often the background retention sweep runs."""


class BackendConfig(BaseModel):
    id: str
    base_url: str
    concurrency: int = Field(default=1, ge=1)
    timeout_s: float = 1800.0
    tags: list[str] = Field(default_factory=list)
    auth_header: str | None = None  # optional raw Authorization header value
    verify_tls: bool = True
    queue_max: int = Field(default=20, ge=0)
    """Maximum tasks waiting for this backend before new requests get 429."""

    @field_validator("base_url")
    @classmethod
    def _base_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/")


class InjectMapping(BaseModel):
    """Where a normalized request value is written into the workflow."""

    node: str
    path: str = "inputs"


class ImageSlot(BaseModel):
    node: str | None = None
    start_node: str | None = None
    extra_node_base: int | None = None
    optional: bool = False
    """When true, the node is only wired (and validated) if a reference image is
    supplied; it is dropped from the workflow for single-image edits."""


class ImageSlots(BaseModel):
    target: ImageSlot
    reference: ImageSlot | None = None
    batch: ImageSlot | None = None


class ModelConstraints(BaseModel):
    size_policy: SizePolicy = "auto_or_explicit"
    size_step: int = 32
    min_edge: int = 256
    max_edge: int = 4096
    max_pixels: int | None = None
    default_size: str = "1024x1024"
    n_max: int = 4
    output_formats: list[str] = Field(default_factory=lambda: ["png"])
    backgrounds: list[str] = Field(default_factory=lambda: ["opaque", "auto"])
    quality_map: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Maps OpenAI ``quality`` values to workflow parameters, e.g.
    ``{"high": {"steps": 40}, "low": {"steps": 8}}``. Applied through the
    ``steps``/``cfg``/``sigmas`` inject mappings when configured."""
    duration_min: float | None = None
    duration_max: float | None = None
    duration_default: float | None = None
    duration_step: float | None = None
    """Video duration limits in seconds; ``duration_step`` quantises requests.
    A string step such as ``"17/24"`` (frames per second grid) is accepted."""

    @field_validator("duration_step", mode="before")
    @classmethod
    def _duration_step(cls, v: Any) -> Any:
        if isinstance(v, str):
            if "/" in v:
                num, _, den = v.partition("/")
                try:
                    return float(num) / float(den)
                except ValueError as exc:
                    raise ValueError(f"invalid duration_step {v!r}") from exc
            try:
                return float(v)
            except ValueError as exc:
                raise ValueError(f"invalid duration_step {v!r}") from exc
        return v


class ModelVariant(BaseModel):
    alias: str
    backend: str
    template: str
    inject: dict[str, InjectMapping] = Field(default_factory=dict)
    static: dict[str, Any] = Field(default_factory=dict)
    """Static values applied first, keyed as ``"<node>.<path>"`` (e.g. ``"474.inputs.switch": true``)."""
    defaults: dict[str, Any] = Field(default_factory=dict)
    constraints: ModelConstraints = Field(default_factory=ModelConstraints)
    image_slots: ImageSlots | None = None
    encoder_node: str | None = None
    """Node that receives ``images.image_1..N`` links (e.g. the Qwen image encoder)."""
    image_targets: dict[str, str] = Field(default_factory=dict)
    """Maps uploaded images onto arbitrary node inputs, e.g.
    ``{"ref_images.ref_image_0": "137", "ref_images.ref_image_1": "139"}``."""
    mask_policy: MaskPolicy = "unsupported"
    fallbacks: list[str] = Field(default_factory=list)


class TaskConfig(BaseModel):
    models: list[ModelVariant]

    @model_validator(mode="after")
    def _unique_aliases(self) -> TaskConfig:
        seen: set[str] = set()
        for m in self.models:
            if m.alias in seen:
                raise ValueError(f"duplicate model alias {m.alias!r}")
            seen.add(m.alias)
        for m in self.models:
            for fb in m.fallbacks:
                if fb not in seen:
                    raise ValueError(f"model {m.alias!r} falls back to unknown alias {fb!r}")
                if fb == m.alias:
                    raise ValueError(f"model {m.alias!r} cannot fall back to itself")
        return self


class UnifiedImageModel(BaseModel):
    """A single model alias that serves both text-to-image and image editing.

    The variant for each operation lives under ``tasks.<op>`` with the same alias;
    requests are routed by whether the caller supplied input images.
    """

    alias: str
    generate_task: str = "image.generate"
    edit_task: str = "image.edit"


class VideoFamily(BaseModel):
    """A named group of video variants selectable by the request's input shape.

    Callers may pass the family name as ``model``; the concrete alias is chosen
    from the fields actually supplied:

    * no images                     -> ``text_to_video``
    * ``input_reference``/first frame -> ``image_to_video``
    * ``reference_images``          -> ``reference_to_video``
    """

    family: str
    task: str = "video.generate"
    text_to_video: str | None = None
    image_to_video: str | None = None
    reference_to_video: str | None = None
    default: str | None = None


class RoutingConfig(BaseModel):
    unified_image_models: list[UnifiedImageModel] = Field(default_factory=list)
    video_families: list[VideoFamily] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> RoutingConfig:
        seen: set[str] = set()
        for u in self.unified_image_models:
            if u.alias in seen:
                raise ValueError(f"duplicate unified model alias {u.alias!r}")
            seen.add(u.alias)
        families: set[str] = set()
        for f in self.video_families:
            if f.family in families:
                raise ValueError(f"duplicate video family {f.family!r}")
            families.add(f.family)
        return self


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig
    storage: StorageConfig = Field(default_factory=StorageConfig)
    backends: list[BackendConfig]
    tasks: dict[str, TaskConfig]
    routing: RoutingConfig = Field(default_factory=RoutingConfig)

    base_dir: Path = Field(default_factory=Path.cwd, exclude=True)
    """Directory that relative paths (templates, storage root) resolve against."""

    @model_validator(mode="after")
    def _check_refs(self) -> Config:
        backend_ids = {b.id for b in self.backends}
        if len(backend_ids) != len(self.backends):
            raise ValueError("duplicate backend id")
        for task_name, task in self.tasks.items():
            for m in task.models:
                if m.backend not in backend_ids:
                    raise ValueError(f"task {task_name!r} model {m.alias!r} references unknown backend {m.backend!r}")
        for u in self.routing.unified_image_models:
            for op in (u.generate_task, u.edit_task):
                if op not in self.tasks:
                    raise ValueError(f"unified model {u.alias!r} references unknown task {op!r}")
            gen = [m for m in self.tasks[u.generate_task].models if m.alias == u.alias]
            edit = [m for m in self.tasks[u.edit_task].models if m.alias == u.alias]
            if not gen:
                raise ValueError(
                    f"unified model {u.alias!r} must be defined in tasks.{u.generate_task}"
                )
            if not edit:
                raise ValueError(f"unified model {u.alias!r} must be defined in tasks.{u.edit_task}")
            if edit[0].image_slots is None:
                raise ValueError(
                    f"unified model {u.alias!r}: edit variant requires image_slots"
                )
            if gen[0].image_slots is not None:
                raise ValueError(
                    f"unified model {u.alias!r}: generate variant must not define image_slots"
                )
        for f in self.routing.video_families:
            if f.task not in self.tasks:
                raise ValueError(f"video family {f.family!r} references unknown task {f.task!r}")
            aliases = {m.alias for m in self.tasks[f.task].models}
            for field_name in ("text_to_video", "image_to_video", "reference_to_video", "default"):
                alias = getattr(f, field_name)
                if alias is not None and alias not in aliases:
                    raise ValueError(
                        f"video family {f.family!r}: {field_name}={alias!r} is not configured "
                        f"in tasks.{f.task}"
                    )
            if not any((f.text_to_video, f.image_to_video, f.reference_to_video, f.default)):
                raise ValueError(f"video family {f.family!r} has no variants configured")
        return self
    # -- helpers ---------------------------------------------------------

    def backend(self, backend_id: str) -> BackendConfig:
        for b in self.backends:
            if b.id == backend_id:
                return b
        raise ConfigError(f"unknown backend {backend_id!r}")

    def task(self, name: str) -> TaskConfig:
        try:
            return self.tasks[name]
        except KeyError as exc:
            raise ConfigError(f"unknown task type {name!r}") from exc

    def variant(self, task_name: str, alias: str) -> ModelVariant:
        for m in self.task(task_name).models:
            if m.alias == alias:
                return m
        raise ConfigError(f"unknown model alias {alias!r} for task {task_name!r}")

    def resolve_path(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        resolved = self.base_dir / p
        if resolved.exists():
            return resolved
        # Configs kept outside the checkout (for example ``.config/litegm.yaml``)
        # refer to templates as ``config/workflows/...`` — relative to the
        # repository root, like the committed example. Fall back to the bundled
        # copy so a deployment config and the example share one template layout.
        fallback = _BUNDLED_ROOT / p
        return fallback if fallback.exists() else resolved

    # -- unified image models -------------------------------------------

    def unified(self, alias: str) -> UnifiedImageModel | None:
        for u in self.routing.unified_image_models:
            if u.alias == alias:
                return u
        return None

    def video_family(self, name: str) -> VideoFamily | None:
        for f in self.routing.video_families:
            if f.family == name:
                return f
        return None

    def route_video_request(self, family: VideoFamily, *, input_mode: str) -> str:
        """Resolve the concrete alias for a video family request.

        ``input_mode`` is ``text``, ``image`` (input_reference/first frame) or
        ``reference`` (reference_images).
        """
        chosen = {
            "text": family.text_to_video,
            "image": family.image_to_video,
            "reference": family.reference_to_video,
        }.get(input_mode)
        if chosen is None:
            chosen = family.default
        if chosen is None:
            raise ConfigError(
                f"video family {family.family!r} has no variant for input mode {input_mode!r}"
            )
        return chosen

    def route_image_request(self, alias: str, *, has_images: bool) -> str:
        """Resolve which task handles an image request for ``alias``.

        Unified aliases route by the presence of input images: with images the
        request is an edit, without images it is a generation. Other aliases keep
        the task implied by the endpoint.
        """
        u = self.unified(alias)
        if u is None:
            return "image.edit" if has_images else "image.generate"
        return u.edit_task if has_images else u.generate_task

    def storage_root(self) -> Path:
        p = Path(self.storage.root)
        return p if p.is_absolute() else (self.base_dir / p)

    def public_url(self, path: str) -> str:
        return self.server.public_base_url.rstrip("/") + "/" + path.lstrip("/")


def load_config(path: str | Path, *, base_dir: str | Path | None = None) -> Config:
    """Load and validate a configuration file.

    Relative paths inside the config (workflow templates, storage root) resolve
    against ``base_dir`` — the project root by default, or the config file's
    directory when ``base_dir`` is omitted and the config lives in that root.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")
    try:
        cfg = Config.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(f"invalid config {p}: {exc}") from exc
    cfg.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
    _validate_templates(cfg)
    return cfg


def _validate_templates(cfg: Config) -> None:
    """Fail fast on missing workflow templates; schema-level checks happen in the workflow layer."""
    import json

    for task_name, task in cfg.tasks.items():
        for m in task.models:
            tpl = cfg.resolve_path(m.template)
            if not tpl.exists():
                raise ConfigError(f"task {task_name!r} model {m.alias!r}: template not found: {tpl}")
            try:
                data = json.loads(tpl.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ConfigError(f"template {tpl} is not valid JSON: {exc}") from exc
            if not isinstance(data, dict) or not data:
                raise ConfigError(f"template {tpl} must be a non-empty JSON object (API format)")
