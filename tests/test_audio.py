"""Tests for the audio API: model routing, duration handling and object shape."""

from __future__ import annotations

import pytest

from litegm.audio import AUDIO_STATUS, _resolve_audio_model
from litegm.requests import GenerationRequest, resolve_duration, validate_request


def test_audio_alias_configured(config):
    assert [m.alias for m in config.task("audio.generate").models] == ["minimax-music3"]


def test_resolve_audio_model(config):
    assert _resolve_audio_model(config, None) == "minimax-music3"
    assert _resolve_audio_model(config, "minimax-music3") == "minimax-music3"
    with pytest.raises(Exception):
        _resolve_audio_model(config, "nope")


def test_audio_duration_limits(config):
    c = config.variant("audio.generate", "minimax-music3").constraints
    assert resolve_duration(1.0, c, snap_frames=False) >= c.duration_min
    assert resolve_duration(9999.0, c, snap_frames=False) <= c.duration_max
    assert resolve_duration(10.0, c, snap_frames=False) == 10.0


def test_audio_request_validation(config):
    variant = config.variant("audio.generate", "minimax-music3")
    req = GenerationRequest(task_type="audio.generate", model_alias=variant.alias,
                            prompt="calm folk", seconds=10.0)
    out = validate_request(req, variant, is_edit=False)
    assert out["seconds"] == 10.0
    assert out["output_format"] == "flac"


def test_audio_status_mapping():
    assert AUDIO_STATUS["succeeded"] == "completed"
    assert AUDIO_STATUS["running"] == "in_progress"
    assert AUDIO_STATUS["failed"] == "failed"
