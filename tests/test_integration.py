"""Integration tests against the real ComfyUI backend from config/litegm.yaml.

Marked ``integration``; run with ``pixi run -e dev test-integration``.
These generate real images and can take tens of seconds each.
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from litegm.app import create_app
from litegm.config import load_config

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "litegm.yaml"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(workdir_module):
    cfg = load_config(CONFIG, base_dir=ROOT)
    # Keep test artifacts away from the real data directory.
    cfg.storage.root = str(workdir_module / "data")
    cfg.server.sync_timeout_s = 900
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def workdir_module():
    base = ROOT / ".test-work"
    base.mkdir(exist_ok=True)
    d = base / f"integration-{uuid.uuid4().hex[:12]}"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="module")
def auth():
    return {"Authorization": f"Bearer {os.environ['LITEGM_MASTER_KEY']}"}


def test_health_reports_backend(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["backends"], "no backends configured"
    assert any(b.get("healthy") for b in body["backends"].values())


def test_models_lists_turbo_aliases(client, auth):
    r = client.get("/v1/models", headers=auth)
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["data"]}
    assert {"qwen-image-2.1-turbo", "qwen-image-2.1-turbo-edit"} <= ids


def test_requires_api_key(client):
    r = client.post("/v1/images/generations", json={"prompt": "x", "model": "qwen-image-2.1-turbo"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_generate_image(client, auth):
    r = client.post(
        "/v1/images/generations",
        headers=auth,
        json={
            "model": "qwen-image-2.1-turbo",
            "prompt": "a small red fox sitting on autumn grass, soft morning light",
            "size": "768x768",
            "n": 1,
            "seed": 20261023,
        },
        timeout=900,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"], "no images returned"
    raw = base64.b64decode(body["data"][0]["b64_json"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image

    im = Image.open(io.BytesIO(raw))
    assert (im.width, im.height) == (768, 768)
    assert body["size"] == "768x768"


def test_edit_image(client, auth, workdir_module):
    from PIL import Image

    src = workdir_module / "source.png"
    Image.new("RGB", (512, 512), (200, 200, 200)).save(src)
    with src.open("rb") as fh:
        r = client.post(
            "/v1/images/edits",
            headers=auth,
            data={"model": "qwen-image-2.1-turbo-edit",
                  "prompt": "make the background dark blue, keep the object unchanged",
                  "seed": "11"},
            files=[("image", ("source.png", fh.read(), "image/png"))],
            timeout=900,
        )
    assert r.status_code == 200, r.text
    assert r.json()["data"]
