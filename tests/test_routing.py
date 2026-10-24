"""Tests for unified image-model routing and input-image bookkeeping."""

from __future__ import annotations

import pytest

from litegm.config import Config


def test_config_declares_unified_model(config):
    u = config.unified("qwen-image-2.1-turbo")
    assert u is not None
    assert u.generate_task == "image.generate"
    assert u.edit_task == "image.edit"
    assert config.unified("qwen-image-2.1-turbo-pe") is None


def test_route_image_request_by_images(config):
    assert config.route_image_request("qwen-image-2.1-turbo", has_images=True) == "image.edit"
    assert config.route_image_request("qwen-image-2.1-turbo", has_images=False) == "image.generate"
    # Non-unified aliases fall back to the endpoint-implied task.
    assert config.route_image_request("moss-image", has_images=False) == "image.generate"
    assert config.route_image_request("qwen-image-2.1-turbo-edit", has_images=True) == "image.edit"


def test_unified_alias_defined_in_both_tasks(config):
    gen = config.variant("image.generate", "qwen-image-2.1-turbo")
    edit = config.variant("image.edit", "qwen-image-2.1-turbo")
    assert gen.image_slots is None
    assert edit.image_slots is not None
    assert edit.image_slots.reference.optional is True


def test_unified_model_validation_rejects_missing_edit_variant(config):
    raw = config.model_dump(exclude={"base_dir"})
    raw["tasks"]["image.edit"]["models"] = [
        m for m in raw["tasks"]["image.edit"]["models"] if m["alias"] != "qwen-image-2.1-turbo"
    ]
    with pytest.raises(Exception):
        Config.model_validate(raw)


def test_unified_model_validation_rejects_generate_with_image_slots(config):
    raw = config.model_dump(exclude={"base_dir"})
    for m in raw["tasks"]["image.generate"]["models"]:
        if m["alias"] == "qwen-image-2.1-turbo":
            m["image_slots"] = {"target": {"node": "470"}}
    with pytest.raises(Exception):
        Config.model_validate(raw)


def test_input_image_metadata_roundtrip(store, workdir):
    img = workdir / "t.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    task = store.create_task(
        task_type="image.edit", model_alias="qwen-image-2.1-turbo", backend_id="gpu-1",
        prompt="x", request={},
    )
    store.add_input_image(task.id, 0, "target.png", str(img), img.stat().st_size,
                          mime_type="image/png", width=512, height=512, role="target")
    store.add_input_image(task.id, 1, "ref.png", str(img), img.stat().st_size,
                          mime_type="image/png", width=256, height=256, role="reference")
    items = store.list_input_images(task.id)
    assert [i["role"] for i in items] == ["target", "reference"]
    assert items[0]["width"] == 512
    assert store.get_input_image(task.id, 1)["filename"] == "ref.png"
    assert store.get_input_image(task.id, 5) is None
