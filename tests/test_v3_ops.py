"""Tests for v3 auth switch, uptime reporting and progress estimation."""

from __future__ import annotations

import time

import pytest

from litegm.auth import Authenticator
from litegm.config import AuthConfig
from litegm.engine import Engine
from litegm.observability import ESTIMATE_FULL_S
from litegm.storage import ArtifactStore


def test_auth_enabled_by_default(master_key):
    cfg = AuthConfig(username="admin", master_key=master_key)
    assert cfg.enabled is True


def test_auth_env_override_disables(monkeypatch, master_key):
    monkeypatch.setenv("LITEGM_AUTH_DISABLED", "1")
    cfg = AuthConfig(username="admin", master_key=master_key)
    assert cfg.enabled is False
    monkeypatch.setenv("LITEGM_AUTH_DISABLED", "false")
    assert AuthConfig(username="admin", master_key=master_key).enabled is True


def test_disabled_auth_accepts_everything(master_key):
    auth = Authenticator(AuthConfig(username="admin", master_key=master_key, enabled=False))
    auth.require_bearer(None)  # must not raise
    auth.require_bearer("Bearer wrong-key")
    assert auth.check_basic(None) is True
    assert auth.verify_session(None) is True


def test_enabled_auth_still_rejects(master_key):
    from litegm.errors import AuthError

    auth = Authenticator(AuthConfig(username="admin", master_key=master_key))
    with pytest.raises(AuthError):
        auth.require_bearer("Bearer nope")
    assert auth.check_basic(None) is False
    assert auth.verify_session(None) is False
    assert auth.check_bearer(f"Bearer {master_key}") is True


def test_estimated_progress_moves_but_is_capped(config, workdir):
    from litegm.store import TaskStore

    store = TaskStore(workdir / "litegm.db")
    arts = ArtifactStore(config, store)
    engine = Engine(config, None, store, arts)  # type: ignore[arg-type]
    task = store.create_task(task_type="video.generate", model_alias="m", backend_id="b",
                             prompt="x", request={}, status="running")
    store.update_task(task.id, progress=20)

    # At the start of the stage nothing changes (the engine already set 20).
    engine._advance_estimated_progress(task.id, time.monotonic())  # noqa: SLF001
    assert store.get_task(task.id).progress == 20

    # Halfway through the budget the estimate advances.
    engine._advance_estimated_progress(task.id, time.monotonic() - ESTIMATE_FULL_S / 2)  # noqa: SLF001
    mid = store.get_task(task.id).progress
    assert 20 < mid <= 88

    # Long-running work never reports completion; downloading does that.
    engine._advance_estimated_progress(task.id, time.monotonic() - 10 * ESTIMATE_FULL_S)  # noqa: SLF001
    assert store.get_task(task.id).progress == 88
    store.close()


def test_estimated_progress_never_decreases(config, workdir):
    from litegm.store import TaskStore

    store = TaskStore(workdir / "litegm.db")
    arts = ArtifactStore(config, store)
    engine = Engine(config, None, store, arts)  # type: ignore[arg-type]
    task = store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                             prompt="x", request={}, status="running")
    store.update_task(task.id, progress=70)
    engine._advance_estimated_progress(task.id, time.monotonic())  # noqa: SLF001
    assert store.get_task(task.id).progress == 70
    store.close()
