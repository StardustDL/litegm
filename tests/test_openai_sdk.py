"""Compatibility check with the official OpenAI SDK (integration only).

Starts the gateway on a local port and drives it with ``openai`` exactly as a real
client would: ``client.images.generate`` and ``client.images.edit``.
"""

from __future__ import annotations

import base64
import io
import os
import socket
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn

from litegm.app import create_app
from litegm.config import load_config

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "litegm.yaml"

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(workdir_module):
    cfg = load_config(CONFIG, base_dir=ROOT)
    cfg.storage.root = str(workdir_module / "sdk-data")
    cfg.server.sync_timeout_s = 900
    app = create_app(cfg)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not srv.started and time.time() < deadline:
        time.sleep(0.1)
    assert srv.started, "gateway did not start"
    yield f"http://127.0.0.1:{port}/v1"
    srv.should_exit = True
    thread.join(timeout=15)


@pytest.fixture(scope="module")
def workdir_module():
    base = ROOT / ".test-work"
    base.mkdir(exist_ok=True)
    d = base / f"sdk-{uuid.uuid4().hex[:12]}"
    d.mkdir()
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


def test_openai_sdk_generate(server):
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["LITEGM_MASTER_KEY"], base_url=server)
    result = client.images.generate(
        model="qwen-image-2.1-turbo",
        prompt="a lone lighthouse at dusk, calm sea, painterly",
        size="768x768",
        n=1,
        extra_body={"seed": 7},
        timeout=900,
    )
    assert result.data
    raw = base64.b64decode(result.data[0].b64_json)
    from PIL import Image

    im = Image.open(io.BytesIO(raw))
    assert (im.width, im.height) == (768, 768)
    assert result.size == "768x768"


def test_openai_sdk_edit(server, workdir_module):
    from openai import OpenAI
    from PIL import Image

    src = workdir_module / "in.png"
    Image.new("RGB", (384, 384), (90, 120, 150)).save(src)
    client = OpenAI(api_key=os.environ["LITEGM_MASTER_KEY"], base_url=server)
    with src.open("rb") as fh:
        result = client.images.edit(
            model="qwen-image-2.1-turbo-edit",
            image=fh,
            prompt="turn the background into warm sunset tones",
            timeout=900,
        )
    assert result.data
    assert base64.b64decode(result.data[0].b64_json)[:4] == b"\x89PNG"


def test_openai_sdk_error_shape(server):
    import openai
    from openai import OpenAI

    client = OpenAI(api_key="wrong-key", base_url=server)
    with pytest.raises(openai.AuthenticationError) as exc:
        client.images.generate(model="qwen-image-2.1-turbo", prompt="x")
    assert exc.value.status_code == 401
