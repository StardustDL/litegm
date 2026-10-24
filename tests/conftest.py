"""Shared test fixtures.

Unit tests never touch a real ComfyUI instance. Integration tests are marked
``integration`` and run against the backend declared in the project config.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
# Tests exercise the committed example config (``config/``); a real deployment
# keeps its own config in the git-ignored ``.config/`` directory.
CONFIG = ROOT / "config" / "litegm.yaml"

os.environ.setdefault("LITEGM_MASTER_KEY", "test-master-key-0123456789")


@pytest.fixture
def workdir():
    """A disposable directory inside the workspace.

    pytest's own tmpdir plugin is disabled (see pyproject.toml) because its base
    directory handling is unreliable under restrictive Windows ACLs. ``mkdtemp``
    is avoided too: mode 0700 directories do not inherit the workspace ACLs on
    Windows, which can make them unreadable to the process that later opens them.
    """
    base = ROOT / ".test-work"
    base.mkdir(exist_ok=True)
    d = base / f"case-{uuid.uuid4().hex[:12]}"
    d.mkdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _config_dict(**overrides) -> dict:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw.update(overrides)
    return raw


@pytest.fixture(scope="session")
def master_key() -> str:
    return os.environ["LITEGM_MASTER_KEY"]


@pytest.fixture
def config_dict() -> dict:
    return _config_dict()


@pytest.fixture
def config(workdir, config_dict):
    from litegm.config import Config

    data = dict(config_dict)
    data["storage"] = {"root": str(workdir / "data"), "artifact_ttl_days": 30, "download_url_ttl_s": 60}
    cfg = Config.model_validate(data)
    cfg.base_dir = ROOT
    return cfg


@pytest.fixture
def store(workdir):
    from litegm.store import TaskStore

    s = TaskStore(workdir / "litegm.db")
    yield s
    s.close()
