"""Normalized generation requests and their validation.

The API layer converts OpenAI-shaped input into a :class:`GenerationRequest`,
which is then validated against the configured model constraints. Sizes are
snapped to the model's legal grid, ``n`` is bounded, and unsupported parameters
are rejected explicitly rather than silently ignored.
"""

from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .config import ModelConstraints, ModelVariant
from .errors import UnsupportedParameterError, ValidationError

_SIZE_RE = re.compile(r"^(\d{1,5})x(\d{1,5})$")

QUALITY_VALUES = {"auto", "low", "medium", "high", "xhigh", "max", "standard", "hd"}
OUTPUT_FORMATS = {"png", "jpeg", "webp"}
BACKGROUNDS = {"transparent", "opaque", "auto"}
RESPONSE_FORMATS = {"url", "b64_json"}

# Common aspect ratios used to resolve ``size=auto`` towards the prompt intent.
_ASPECT_HINTS: list[tuple[re.Pattern[str], tuple[int, int]]] = [
    (re.compile(r"16\s*[:x×]\s*9|widescreen|横屏|宽屏", re.I), (16, 9)),
    (re.compile(r"9\s*[:x×]\s*16|portrait|竖屏|竖图|手机", re.I), (9, 16)),
    (re.compile(r"4\s*[:x×]\s*3", re.I), (4, 3)),
    (re.compile(r"3\s*[:x×]\s*4", re.I), (3, 4)),
    (re.compile(r"21\s*[:x×]\s*9|ultrawide|超宽", re.I), (21, 9)),
    (re.compile(r"3\s*[:x×]\s*2", re.I), (3, 2)),
    (re.compile(r"2\s*[:x×]\s*3", re.I), (2, 3)),
]


def snap(value: int, step: int) -> int:
    return max(step, int(round(value / step)) * step)


def parse_size(size: str | None) -> tuple[int, int] | None:
    if not size or size == "auto":
        return None
    m = _SIZE_RE.match(size.strip().lower())
    if not m:
        raise ValidationError(f"size must be 'auto' or 'WIDTHxHEIGHT', got {size!r}", param="size")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        raise ValidationError(f"size must be positive, got {size!r}", param="size")
    return w, h


def _aspect_from_prompt(prompt: str) -> tuple[int, int] | None:
    for pattern, ratio in _ASPECT_HINTS:
        if pattern.search(prompt):
            return ratio
    return None


def resolve_size(
    requested: str | None,
    constraints: ModelConstraints,
    prompt: str,
) -> tuple[int, int]:
    """Return a legal (width, height) for this model."""
    step = max(1, constraints.size_step)
    parsed = parse_size(requested)
    if parsed is None:
        if constraints.size_policy == "explicit":
            parsed = parse_size(constraints.default_size) or (1024, 1024)
        else:
            aspect = _aspect_from_prompt(prompt)
            if aspect is None:
                parsed = parse_size(constraints.default_size) or (1024, 1024)
            else:
                aw, ah = aspect
                # Keep the default area, fit the requested aspect ratio.
                default_w, default_h = parse_size(constraints.default_size) or (1024, 1024)
                area = default_w * default_h
                scale = (area / (aw * ah)) ** 0.5
                parsed = (int(aw * scale), int(ah * scale))
    w, h = parsed
    if constraints.size_policy == "auto":
        # Edit models derive the canvas from the input image; explicit sizes are advisory.
        w = snap(w, step)
        h = snap(h, step)
    w = min(max(snap(w, step), constraints.min_edge), constraints.max_edge)
    h = min(max(snap(h, step), constraints.min_edge), constraints.max_edge)
    if constraints.max_pixels:
        while w * h > constraints.max_pixels:
            w = max(constraints.min_edge, w - step)
            h = max(constraints.min_edge, h - step)
    return w, h


def validate_output_params(
    *,
    quality: str | None,
    output_format: str | None,
    background: str | None,
    output_compression: int | None,
    response_format: str | None,
    constraints: ModelConstraints,
) -> dict[str, Any]:
    """Validate OpenAI image output parameters against model capabilities."""
    if quality is not None and quality not in QUALITY_VALUES:
        raise ValidationError(f"quality must be one of {sorted(QUALITY_VALUES)}", param="quality")
    fmt = (output_format or "png").lower()
    if fmt not in OUTPUT_FORMATS:
        raise ValidationError(f"output_format must be one of {sorted(OUTPUT_FORMATS)}", param="output_format")
    if fmt not in constraints.output_formats:
        raise UnsupportedParameterError(
            f"model does not support output_format={fmt!r}; supported: {constraints.output_formats}",
            param="output_format",
        )
    bg = (background or "opaque").lower()
    if bg not in BACKGROUNDS:
        raise ValidationError(f"background must be one of {sorted(BACKGROUNDS)}", param="background")
    if bg not in constraints.backgrounds:
        raise UnsupportedParameterError(
            f"model does not support background={bg!r}; supported: {constraints.backgrounds}",
            param="background",
        )
    if output_compression is not None:
        if not 0 <= output_compression <= 100:
            raise ValidationError("output_compression must be between 0 and 100", param="output_compression")
        if fmt == "png":
            raise UnsupportedParameterError(
                "output_compression is only supported for webp/jpeg output", param="output_compression"
            )
    rf = response_format
    if rf is not None and rf not in RESPONSE_FORMATS:
        raise ValidationError(f"response_format must be one of {sorted(RESPONSE_FORMATS)}", param="response_format")
    if bg == "transparent" and fmt != "png":
        raise UnsupportedParameterError(
            "transparent background requires output_format=png", param="background"
        )
    return {"output_format": fmt, "background": bg, "quality": quality, "response_format": rf}


@dataclass
class GenerationRequest:
    task_type: str
    model_alias: str
    prompt: str
    n: int = 1
    size: str | None = None
    quality: str | None = None
    output_format: str = "png"
    background: str = "opaque"
    output_compression: int | None = None
    response_format: str | None = None
    seed: int | None = None
    seconds: float | None = None
    requested_model: str | None = None
    """The ``model`` value the caller supplied (may be a family name)."""
    input_mode: str | None = None
    """How the request was routed (``text``/``image``/``reference``) for video."""
    images: list[bytes] = field(default_factory=list)
    image_names: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    created: int = field(default_factory=lambda: int(time.time()))

    def to_audit(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "model": self.model_alias,
            "requested_model": self.requested_model,
            "input_mode": self.input_mode,
            "prompt": self.prompt,
            "n": self.n,
            "size": self.size,
            "quality": self.quality,
            "output_format": self.output_format,
            "background": self.background,
            "output_compression": self.output_compression,
            "response_format": self.response_format,
            "seed": self.seed,
            "seconds": self.seconds,
            "input_images": len(self.images),
            "extra": self.extra,
        }


def resolve_duration(
    seconds: float | None,
    constraints: ModelConstraints,
    *,
    default: float | None = None,
    snap_frames: bool = True,
) -> float:
    """Clamp/quantise a requested duration to what the model supports.

    ``snap_frames`` applies the 17k+5 frame grid used by video models; audio only
    needs clamping.
    """
    value = seconds if seconds is not None else (default or constraints.duration_default or 2.0)
    low = constraints.duration_min or 0.5
    high = constraints.duration_max or 15.0
    step = constraints.duration_step or 0.0
    if snap_frames and step > 0:
        # H3 quantises frame counts to the 17k+5 grid (k >= 1). The step is
        # expressed in frames at 24 fps; the smallest legal clip is 22 frames.
        frames_per_block = max(1, round(step * 24))
        frames = frames_per_block * max(1, round(value * 24 / frames_per_block)) + 5
        if frames / 24.0 < low:
            frames = frames_per_block * max(1, math.ceil(low * 24 / frames_per_block)) + 5
        value = frames / 24.0
    value = max(low, min(high, value))
    return round(value, 3)


def validate_request(
    req: GenerationRequest,
    variant: ModelVariant,
    *,
    is_edit: bool,
) -> dict[str, Any]:
    """Validate the request against the model variant; returns normalized values."""
    constraints = variant.constraints
    if not req.prompt or not req.prompt.strip():
        raise ValidationError("prompt is required and must be non-empty", param="prompt")
    if req.n < 1 or req.n > constraints.n_max:
        raise ValidationError(f"n must be between 1 and {constraints.n_max}", param="n")
    if req.task_type.startswith("video") and req.n != 1:
        raise ValidationError("n must be 1 for video generation", param="n")
    if is_edit:
        if variant.image_slots is None:
            raise ValidationError(f"model {variant.alias!r} does not accept input images", param="image")
        if not req.images:
            raise ValidationError("at least one input image is required", param="image")
        max_images = 16
        if variant.image_slots.reference is None or variant.image_slots.reference.extra_node_base is None:
            max_images = 2 if variant.image_slots.reference is not None else 1
        if len(req.images) > max_images:
            raise ValidationError(f"too many input images ({len(req.images)}); max is {max_images}", param="image")
    elif req.task_type.startswith("video"):
        if variant.image_slots is None and req.images:
            raise UnsupportedParameterError(
                f"model {variant.alias!r} is text-to-video and does not accept input images",
                param="input_reference",
            )
        if variant.image_slots is not None and not req.images:
            raise ValidationError(
                f"model {variant.alias!r} requires an input image", param="input_reference"
            )
    if req.task_type.startswith("video"):
        out: dict[str, Any] = {"output_format": "mp4", "quality_params": {}}
        seconds = resolve_duration(req.seconds, constraints)
        out["seconds"] = seconds
    elif req.task_type.startswith("audio"):
        out = {"output_format": "flac", "quality_params": {}}
        out["seconds"] = resolve_duration(req.seconds, constraints, snap_frames=False)
    else:
        out = validate_output_params(
            quality=req.quality,
            output_format=req.output_format,
            background=req.background,
            output_compression=req.output_compression,
            response_format=req.response_format,
            constraints=constraints,
        )
    width, height = resolve_size(req.size, constraints, req.prompt)
    out.update({"width": width, "height": height})
    seed = req.seed
    if seed is None:
        seed = random.randrange(0, 2**62)
    out["seed"] = int(seed)
    out["n"] = req.n
    # Map the OpenAI ``quality`` value onto concrete workflow parameters.
    quality_key = (req.quality or "auto").lower()
    mapped = constraints.quality_map.get(quality_key)
    if mapped is None and quality_key in ("standard", "hd"):
        mapped = constraints.quality_map.get("high" if quality_key == "hd" else "auto")
    out["quality_params"] = dict(mapped or {})
    return out
