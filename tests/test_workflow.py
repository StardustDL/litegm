"""Unit tests for workflow compilation and schema validation."""

from __future__ import annotations

import copy
import json

import pytest

from litegm.errors import GenerationFailedError, ValidationError
from litegm.workflow import (
    compile_workflow,
    inject_values,
    load_image_node_ids,
    validate_against_backend,
    validate_workflow,
    wire_images,
)

T2I_SCHEMA = {
    "TextGenerate": {"input": {"required": {"prompt": ["STRING", {}]}}, "output": ["STRING"]},
    "ComfySwitchNode": {"input": {"required": {"switch": ["BOOLEAN", {}]}}, "output": ["*"]},
    "EmptyLatentImage": {"input": {"required": {"width": ["INT", {}], "height": ["INT", {}]}},
                         "output": ["LATENT"]},
    "RandomNoise": {"input": {"required": {"noise_seed": ["INT", {}]}}, "output": ["NOISE"]},
    "SaveImageAdvanced": {
        "input": {"required": {
            "images": ["IMAGE", {}],
            "filename_prefix": ["STRING", {}],
            "format": ["COMFY_DYNAMICCOMBO_V3", {"options": [
                {"key": "png", "inputs": {"required": {"bit_depth": ["COMBO", {}]}}},
                {"key": "exr", "inputs": {"required": {"bit_depth": ["COMBO", {}]}}},
            ]}],
        }},
        "output": ["IMAGE"],
    },
    "VAEDecode": {"input": {"required": {"samples": ["LATENT", {}], "vae": ["VAE", {}]}},
                  "output": ["IMAGE"]},
    "VAELoader": {"input": {"required": {"vae_name": ["COMBO", {"options": ["vae.safetensors"]}]}},
                  "output": ["VAE"]},
}


def _t2i_template() -> dict:
    return {
        "471": {"class_type": "TextGenerate", "inputs": {"prompt": ""}},
        "474": {"class_type": "ComfySwitchNode", "inputs": {"switch": False}},
        "456": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
        "488": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
        "457": {"class_type": "VAEDecode", "inputs": {"samples": ["456", 0], "vae": ["454", 0]}},
        "454": {"class_type": "VAELoader", "inputs": {"vae_name": "vae.safetensors"}},
        "461": {"class_type": "SaveImageAdvanced", "inputs": {
            "images": ["457", 0], "filename_prefix": "x", "format": "png", "format.bit_depth": "8-bit",
        }},
    }


def test_inject_values_writes_into_inputs(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    wf = copy.deepcopy(_t2i_template())
    applied = inject_values(wf, variant, {"prompt": "hello", "width": 768, "seed": 5})
    assert wf["471"]["inputs"]["prompt"] == "hello"
    assert wf["456"]["inputs"]["width"] == 768
    assert wf["488"]["inputs"]["noise_seed"] == 5
    assert applied["prompt"] == "hello"


def test_inject_keeps_passthrough_in_sync(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    wf = copy.deepcopy(_t2i_template())
    inject_values(wf, variant, {"prompt": "a red fox", "passthrough": "a red fox"})
    assert wf["474"]["inputs"]["on_false"] == "a red fox"


def test_compile_rejects_missing_node(config):
    variant = config.variant("image.generate", "qwen-image-2.1-turbo")
    bad = copy.deepcopy(_t2i_template())
    del bad["456"]
    import litegm.workflow as wfmod

    orig = wfmod.load_template
    wfmod.load_template = lambda cfg, v: bad
    try:
        with pytest.raises(GenerationFailedError):
            compile_workflow(config, variant, {"width": 1024})
    finally:
        wfmod.load_template = orig


def test_validate_workflow_catches_unknown_node_and_bad_combo():
    wf = _t2i_template()
    wf["999"] = {"class_type": "Nope", "inputs": {}}
    wf["461"]["inputs"]["format"] = "tiff"
    problems = validate_workflow(wf, T2I_SCHEMA)
    assert any("unknown class_type" in p for p in problems)
    assert any("format=" in p for p in problems)


def test_validate_workflow_reports_dangling_links():
    wf = _t2i_template()
    wf["457"]["inputs"]["vae"] = ["1234", 0]
    problems = validate_workflow(wf, T2I_SCHEMA)
    assert any("missing node" in p for p in problems)


def test_validate_against_backend_raises_with_problems():
    wf = _t2i_template()
    wf["461"]["inputs"]["format"] = "tiff"
    with pytest.raises(GenerationFailedError) as exc:
        validate_against_backend(wf, T2I_SCHEMA)
    assert exc.value.details["problems"]


def test_wire_images_creates_reference_nodes(config):
    variant = config.variant("image.edit", "qwen-image-2.1-turbo-edit")
    wf = compile_workflow(config, variant, {"prompt": "edit", "passthrough": "edit"}).workflow
    wiring = wire_images(wf, variant, target_image="t.png", reference_images=["a.png", "b.png"])
    assert wf["470"]["inputs"]["image"] == "t.png"
    assert wf["475"]["inputs"]["image"] == "a.png"
    assert wf["510"]["inputs"]["image"] == "b.png"
    # Autogrow links are flat keys, exactly as ComfyUI expects.
    assert wf["474"]["inputs"]["images.image_3"] == ["510", 0]
    assert wf["485"]["inputs"]["images.image2"] == ["510", 0]
    assert len(wiring["references"]) == 2


def test_wire_images_clears_stale_template_links(config):
    variant = config.variant("image.edit", "qwen-image-2.1-turbo-edit")
    wf = compile_workflow(config, variant, {"prompt": "edit", "passthrough": "edit"}).workflow
    wire_images(wf, variant, target_image="only.png", reference_images=[])
    assert {k for k in wf["474"]["inputs"] if k.startswith("images.")} == {"images.image_1"}
    assert {k for k in wf["485"]["inputs"] if k.startswith("images.")} == {"images.image0"}


def test_load_image_node_ids():
    from litegm.config import ImageSlot, ImageSlots, ModelVariant

    v = ModelVariant(alias="x", backend="b", template="t.json", image_slots=ImageSlots(
        target=ImageSlot(node="470"),
        reference=ImageSlot(start_node="475", extra_node_base=510),
        batch=ImageSlot(node="485"),
    ))
    assert load_image_node_ids(v, 1) == {"470"}
    assert load_image_node_ids(v, 3) == {"470", "475", "510"}


def test_optional_reference_slot_dropped_for_single_image(config):
    """A template may ship a reference node that must not be used for 1-image edits."""
    variant = config.variant("image.edit", "qwen-image-2.1-edit")
    assert variant.image_slots.reference.optional is True
    wf = compile_workflow(config, variant, {"prompt": "edit"}).workflow
    wiring = wire_images(wf, variant, target_image="only.png", reference_images=[])
    assert "475" not in wf
    assert wiring["references"] == []
    assert {k for k in wf["474"]["inputs"] if k.startswith("images.")} == {"images.image_1"}
    assert load_image_node_ids(variant, 1) == {"470", "475"}

    wf2 = compile_workflow(config, variant, {"prompt": "edit"}).workflow
    wire_images(wf2, variant, target_image="t.png", reference_images=["r.png"])
    assert wf2["475"]["inputs"]["image"] == "r.png"
    assert wf2["474"]["inputs"]["images.image_2"] == ["475", 0]


def test_config_outside_checkout_uses_bundled_templates(config, workdir):
    """A config kept in ``.config/`` may refer to the bundled ``config/workflows/``."""
    from litegm.config import Config

    raw = config.model_dump(exclude={"base_dir"})
    cfg = Config.model_validate(raw)
    cfg.base_dir = workdir  # no config/workflows/ here
    variant = cfg.variant("image.generate", "qwen-image-2.1-turbo")
    resolved = cfg.resolve_path(variant.template)
    assert resolved.exists()
    assert resolved.parent.name == "workflows"
    # An explicit local copy still wins over the bundled template.
    local = workdir / variant.template
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("{}", encoding="utf-8")
    assert cfg.resolve_path(variant.template) == local
