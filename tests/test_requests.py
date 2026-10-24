"""Unit tests for request normalization and validation."""

from __future__ import annotations

import pytest

from litegm.config import ModelConstraints
from litegm.errors import UnsupportedParameterError, ValidationError
from litegm.requests import (
    GenerationRequest,
    parse_size,
    resolve_size,
    validate_output_params,
    validate_request,
)


def test_parse_size_auto_and_explicit():
    assert parse_size("auto") is None
    assert parse_size(None) is None
    assert parse_size("1024x768") == (1024, 768)
    with pytest.raises(ValidationError):
        parse_size("1024*768")


def test_resolve_size_snaps_to_step_and_bounds():
    c = ModelConstraints(size_step=32, min_edge=256, max_edge=2048, default_size="1024x1024")
    w, h = resolve_size("1000x700", c, "a cat")
    assert w % 32 == 0 and h % 32 == 0
    assert 256 <= w <= 2048 and 256 <= h <= 2048


def test_resolve_size_from_prompt_aspect():
    c = ModelConstraints(size_step=32, default_size="1024x1024")
    w, h = resolve_size("auto", c, "a cinematic 16:9 landscape")
    assert w > h
    w2, h2 = resolve_size("auto", c, "竖屏 9:16 手机壁纸")
    assert h2 > w2


def test_output_params_reject_unsupported_background():
    c = ModelConstraints(backgrounds=["opaque", "auto"])
    with pytest.raises(UnsupportedParameterError) as exc:
        validate_output_params(quality=None, output_format="png", background="transparent",
                               output_compression=None, response_format=None, constraints=c)
    assert exc.value.param == "background"


def test_output_compression_only_for_webp():
    c = ModelConstraints(output_formats=["png", "webp"])
    with pytest.raises(UnsupportedParameterError):
        validate_output_params(quality=None, output_format="png", background="opaque",
                               output_compression=80, response_format=None, constraints=c)
    out = validate_output_params(quality=None, output_format="webp", background="opaque",
                                 output_compression=80, response_format=None, constraints=c)
    assert out["output_format"] == "webp"


def test_validate_request_rejects_bad_n(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    req = GenerationRequest(task_type="image.generate", model_alias=variant.alias,
                            prompt="x", n=99)
    with pytest.raises(ValidationError) as exc:
        validate_request(req, variant, is_edit=False)
    assert exc.value.param == "n"


def test_validate_request_seed_is_derived_when_absent(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    req = GenerationRequest(task_type="image.generate", model_alias=variant.alias, prompt="x")
    out = validate_request(req, variant, is_edit=False)
    assert isinstance(out["seed"], int)


def test_edit_requires_images(config):
    variant = config.variant("image.edit", "qwen-image-2.1-turbo-edit")
    req = GenerationRequest(task_type="image.edit", model_alias=variant.alias, prompt="x")
    with pytest.raises(ValidationError) as exc:
        validate_request(req, variant, is_edit=True)
    assert exc.value.param == "image"


def test_quality_maps_to_steps(config):
    variant = config.variant("image.generate", "qwen-image-2.1")
    req = GenerationRequest(task_type="image.generate", model_alias=variant.alias,
                            prompt="x", quality="high")
    out = validate_request(req, variant, is_edit=False)
    assert out["quality_params"] == {"steps": 40}

    req_low = GenerationRequest(task_type="image.generate", model_alias=variant.alias,
                                prompt="x", quality="low")
    assert validate_request(req_low, variant, is_edit=False)["quality_params"] == {"steps": 12}


def test_turbo_has_no_quality_map(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    req = GenerationRequest(task_type="image.generate", model_alias=variant.alias,
                            prompt="x", quality="high")
    # Turbo steps are fixed by ManualSigmas; quality is accepted but inert.
    assert validate_request(req, variant, is_edit=False)["quality_params"] == {}


def test_n_multiples_accepted(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    req = GenerationRequest(task_type="image.generate", model_alias=variant.alias,
                            prompt="x", n=3, seed=100)
    out = validate_request(req, variant, is_edit=False)
    assert out["n"] == 3
    assert out["seed"] == 100


def test_webp_and_jpeg_supported(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    for fmt in ("webp", "jpeg"):
        req = GenerationRequest(task_type="image.generate", model_alias=variant.alias,
                                prompt="x", output_format=fmt, output_compression=70)
        out = validate_request(req, variant, is_edit=False)
        assert out["output_format"] == fmt


def test_transparent_requires_png(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    req = GenerationRequest(task_type="image.generate", model_alias=variant.alias,
                            prompt="x", output_format="jpeg", background="transparent")
    with pytest.raises(UnsupportedParameterError):
        validate_request(req, variant, is_edit=False)
