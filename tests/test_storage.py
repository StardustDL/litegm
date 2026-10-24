"""Tests for storage retention and observability helpers (v3)."""

from __future__ import annotations

import time

import pytest

from litegm.config import Config, StorageConfig
from litegm.observability import Metrics, _route_label
from litegm.storage import ArtifactStore
from litegm.store import Artifact, TaskStore, new_id


@pytest.fixture
def artifacts_cfg(workdir, config_dict):
    data = dict(config_dict)
    data["storage"] = {"root": str(workdir / "data"), "artifact_ttl_days": 1,
                       "download_url_ttl_s": 60, "max_bytes": 10_000,
                       "failed_retention_days": 3, "sweep_interval_s": 900}
    cfg = Config.model_validate(data)
    cfg.base_dir = workdir
    return cfg


def test_sweep_removes_old_artifacts(artifacts_cfg, workdir):
    store = TaskStore(workdir / "litegm.db")
    arts = ArtifactStore(artifacts_cfg, store)
    task = store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                             prompt="x", request={}, status="succeeded")
    art = arts.save(task_id=task.id, filename="a.png", data=b"x" * 100, kind="image")
    # Age the artifact beyond the TTL.
    with store._sessionmaker() as s:  # noqa: SLF001
        from litegm.store import ArtifactRow

        row = s.get(ArtifactRow, art.id)
        row.created_at = time.time() - 2 * 86400
        s.commit()
    result = arts.sweep()
    assert result["artifacts"] == 1
    assert store.get_artifact(art.id) is None
    store.close()


def test_sweep_keeps_failed_tasks_longer(artifacts_cfg, workdir):
    store = TaskStore(workdir / "litegm.db")
    arts = ArtifactStore(artifacts_cfg, store)
    task = store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                             prompt="x", request={}, status="failed")
    art = arts.save(task_id=task.id, filename="a.png", data=b"x" * 100, kind="image")
    with store._sessionmaker() as s:  # noqa: SLF001
        from litegm.store import ArtifactRow

        row = s.get(ArtifactRow, art.id)
        row.created_at = time.time() - 2 * 86400  # older than TTL, younger than failed TTL
        s.commit()
    arts.sweep()
    assert store.get_artifact(art.id) is not None
    store.close()


def test_sweep_enforces_disk_budget(artifacts_cfg, workdir):
    store = TaskStore(workdir / "litegm.db")
    arts = ArtifactStore(artifacts_cfg, store)
    ids = []
    for _ in range(3):
        task = store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                                 prompt="x", request={}, status="succeeded")
        art = arts.save(task_id=task.id, filename="a.png", data=b"y" * 8000, kind="image")
        ids.append(art.id)
        time.sleep(0.01)
    result = arts.sweep()
    assert result["artifacts"] >= 1
    assert arts.usage()["total_bytes"] <= artifacts_cfg.storage.max_bytes
    store.close()


def test_soft_delete_hides_task(store):
    task = store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                             prompt="x", request={}, status="succeeded")
    assert store.list_tasks()[1] == 1
    store.soft_delete_task(task.id)
    assert store.list_tasks()[1] == 0
    assert store.list_tasks(include_deleted=True)[1] == 1
    assert store.get_task(task.id) is not None


def test_search_matches_prompt_and_id(store):
    store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                      prompt="a quiet HARBOR at dawn", request={}, status="succeeded")
    store.create_task(task_type="image.generate", model_alias="m", backend_id="b",
                      prompt="a red fox", request={}, status="succeeded")
    assert store.list_tasks(search="harbor")[1] == 1
    assert store.list_tasks(search="FOX")[1] == 1


def test_route_label_collapses_ids():
    assert _route_label("/v1/videos/task_abc123def456/content") == "/v1/videos/{id}/content"
    assert _route_label("/v1/images/generations") == "/v1/images/generations"


def test_metrics_observe():
    m = Metrics()
    m.observe_request("GET", "/v1/models", 200, 0.1)
    m.observe_task("image.generate", "succeeded", 5.0)
    assert m.requests_total[("GET", "/v1/models", 200)] == 1
    assert m.task_finished[("image.generate", "succeeded")] == 1


def test_storage_config_defaults():
    cfg = StorageConfig()
    assert cfg.max_bytes is None
    assert cfg.sweep_interval_s == 900
