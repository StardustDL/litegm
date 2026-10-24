"""Tests for the video API: model routing, duration clamping and object shape."""

from __future__ import annotations

import pytest

from litegm.config import Config
from litegm.errors import UnsupportedParameterError, ValidationError
from litegm.requests import GenerationRequest, resolve_duration, validate_request
from litegm.video import VIDEO_STATUS, _resolve_video_model


def test_video_aliases_configured(config):
    aliases = [m.alias for m in config.task("video.generate").models]
    assert aliases == ["minimax-h3-t2v", "minimax-h3-i2v", "minimax-h3-r2v"]


def test_resolve_video_model_by_reference(config):
    assert _resolve_video_model(config, None, input_mode="text")[1] == "minimax-h3-t2v"
    assert _resolve_video_model(config, None, input_mode="image")[1] == "minimax-h3-i2v"
    assert _resolve_video_model(config, None, input_mode="reference")[1] == "minimax-h3-r2v"
    assert _resolve_video_model(config, "minimax-h3-r2v", input_mode="reference")[1] == "minimax-h3-r2v"


def test_video_family_routes_by_input_mode(config):
    family = config.video_family("minimax-h3")
    assert family is not None
    assert _resolve_video_model(config, "minimax-h3", input_mode="text")[1] == "minimax-h3-t2v"
    assert _resolve_video_model(config, "minimax-h3", input_mode="image")[1] == "minimax-h3-i2v"
    assert _resolve_video_model(config, "minimax-h3", input_mode="reference")[1] == "minimax-h3-r2v"
    # A concrete alias overrides the family routing.
    assert _resolve_video_model(config, "minimax-h3-t2v", input_mode="text")[1] == "minimax-h3-t2v"


def test_video_family_validation(config):
    raw = config.model_dump(exclude={"base_dir"})
    raw["routing"]["video_families"][0]["image_to_video"] = "does-not-exist"
    with pytest.raises(Exception):
        Config.model_validate(raw)


def test_resolve_video_model_unknown(config):
    with pytest.raises(Exception) as exc:
        _resolve_video_model(config, "nope", input_mode="text")
    assert "not configured" in str(exc.value)


def test_duration_clamped_to_limits(config):
    variant = config.variant("video.generate", "minimax-h3-t2v")
    c = variant.constraints
    assert resolve_duration(99.0, c) <= c.duration_max
    assert resolve_duration(0.1, c) >= c.duration_min
    # H3 quantises frame counts to the 17k+5 grid at 24 fps.
    for requested in (0.5, 1.0, 2.0, 5.0):
        snapped = resolve_duration(requested, c)
        frames = round(snapped * 24)
        assert frames >= 22
        assert (frames - 5) % 17 == 0


def test_t2v_rejects_input_images(config):
    variant = config.variant("video.generate", "minimax-h3-t2v")
    req = GenerationRequest(task_type="video.generate", model_alias=variant.alias,
                            prompt="x", images=[b"png"])
    with pytest.raises(UnsupportedParameterError):
        validate_request(req, variant, is_edit=False)


def test_i2v_requires_input_image(config):
    variant = config.variant("video.generate", "minimax-h3-i2v")
    req = GenerationRequest(task_type="video.generate", model_alias=variant.alias, prompt="x")
    with pytest.raises(ValidationError):
        validate_request(req, variant, is_edit=False)


def test_i2v_accepts_single_image(config):
    variant = config.variant("video.generate", "minimax-h3-i2v")
    req = GenerationRequest(task_type="video.generate", model_alias=variant.alias,
                            prompt="x", images=[b"png"], seconds=1.0)
    out = validate_request(req, variant, is_edit=False)
    assert out["seconds"] > 0
    assert out["output_format"] == "mp4"


def test_video_status_mapping():
    assert VIDEO_STATUS["succeeded"] == "completed"
    assert VIDEO_STATUS["running"] == "in_progress"
    assert VIDEO_STATUS["queued"] == "queued"
    assert VIDEO_STATUS["failed"] == "failed"
