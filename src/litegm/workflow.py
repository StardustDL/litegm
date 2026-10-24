"""Workflow compilation.

Takes a normalized generation request plus a configured model variant and produces
a concrete ComfyUI API-format workflow. All node ids and input paths come from
configuration (``inject`` / ``static`` / ``image_slots``), so the same code serves
any workflow.

Before submission the compiled workflow is validated against the backend's
``/object_info`` schemas: required inputs present, combo values legal, and link
targets existing. Invalid workflows fail fast with HTTP 422 instead of burning
GPU time.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .config import Config, ImageSlot, ModelVariant
from .errors import GenerationFailedError, ValidationError

COMFY_AUTOGROW_PREFIX = "COMFY_AUTOGROW"
COMFY_DYNAMICCOMBO_PREFIX = "COMFY_DYNAMICCOMBO"


@dataclass
class CompiledWorkflow:
    workflow: dict[str, Any]
    alias: str
    backend_id: str
    uploads: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)


def load_template(cfg: Config, variant: ModelVariant) -> dict[str, Any]:
    path = cfg.resolve_path(variant.template)
    return json.loads(path.read_text(encoding="utf-8"))


def _split_dotted(key: str) -> tuple[str, str]:
    """``"474.inputs.switch"`` -> ``("474", "inputs.switch")``."""
    node, _, rest = key.partition(".")
    return node, rest


def _set_path(workflow: dict[str, Any], node: str, path: str, value: Any) -> None:
    if node not in workflow:
        raise GenerationFailedError(f"workflow has no node {node!r} (inject target)", code="template_mismatch")
    target = workflow[node]
    if path.startswith("inputs."):
        inputs = target.setdefault("inputs", {})
        inputs[path[len("inputs."):]] = value
        return
    parts = path.split(".")
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def apply_static(workflow: dict[str, Any], variant: ModelVariant) -> None:
    for key, value in variant.static.items():
        node, path = _split_dotted(key)
        _set_path(workflow, node, path, value)


def inject_values(workflow: dict[str, Any], variant: ModelVariant, values: dict[str, Any]) -> dict[str, Any]:
    """Write normalized values into their configured injection points.

    Returns the subset actually applied, for the audit snapshot.
    """
    applied: dict[str, Any] = {}
    for name, mapping in variant.inject.items():
        if name not in values:
            continue
        value = values[name]
        if value is None:
            continue
        _set_path(workflow, mapping.node, mapping.path, value)
        applied[name] = value
    # The switch feeds the encoder from the user's own prompt; keep it in sync so
    # the pass-through branch cannot silently emit the template's empty string.
    if "prompt" in applied and "passthrough" in variant.inject:
        _set_path(
            workflow,
            variant.inject["passthrough"].node,
            variant.inject["passthrough"].path,
            applied["prompt"],
        )
        applied["passthrough"] = applied["prompt"]
    return applied


# -- image slot wiring ------------------------------------------------------


def _load_image_node(name: str, title: str) -> dict[str, Any]:
    return {
        "class_type": "LoadImage",
        "inputs": {"image": name, "upload": "image"},
        "_meta": {"title": title},
    }


def wire_images(
    workflow: dict[str, Any],
    variant: ModelVariant,
    *,
    target_image: str,
    reference_images: list[str],
) -> dict[str, Any]:
    """Place uploaded images into the configured slots and connect them.

    Layout (mirrors the reference scripts for the Qwen edit workflow):
    ``target`` -> ``LoadImage.image``; the first reference goes to
    ``reference.start_node``; further references create ``LoadImage`` nodes at
    ``reference.extra_node_base`` + i; every image is then wired into the encoder
    (``images.image_N``) and the PE batch node (``images.imageN``).

    ``image_targets`` additionally links images onto arbitrary node inputs, e.g.
    ``{"ref_images.ref_image_0": "137"}`` (first image) or
    ``{"ref_images.ref_image_1": "139"}`` (second image).
    """
    slots = variant.image_slots
    if slots is None:
        raise ValidationError("this model does not accept input images", param="image")
    tgt = slots.target
    if not tgt.node:
        raise GenerationFailedError("image_slots.target.node is required", code="config_error")
    if len(reference_images) > 15:
        raise ValidationError(f"too many input images ({len(reference_images)}); max is 16", param="image")

    all_nodes = [tgt.node] + list(variant.image_targets.values())
    for node_id in all_nodes:
        if node_id in workflow:
            _set_path(workflow, node_id, "inputs.image", target_image)    # Start from a clean slate: templates ship with placeholder reference images.
    for node in list(workflow.values()):
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        for k in list(node["inputs"]):
            if k.startswith("images.image") and _is_link(node["inputs"][k]):
                del node["inputs"][k]

    ref_nodes: list[str] = []
    ref_slot = slots.reference
    if ref_slot is not None and ref_slot.start_node and ref_slot.optional and not reference_images:
        # Optional reference node: drop it and any inputs pointing at it.
        workflow.pop(ref_slot.start_node, None)
        for node in workflow.values():
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            for k in list(node["inputs"]):
                v = node["inputs"][k]
                if _is_link(v) and v[0] == ref_slot.start_node:
                    del node["inputs"][k]
                elif k.startswith("ref_images.") and _is_link(v) and v[0] not in workflow:
                    del node["inputs"][k]
    if reference_images:
        if ref_slot is None or not ref_slot.start_node:
            raise ValidationError("model has no reference-image slot", param="image")
        if len(reference_images) > 1 and ref_slot.extra_node_base is None:
            raise ValidationError(
                f"model accepts at most 1 reference image, got {len(reference_images)}", param="image"
            )
        _set_path(workflow, ref_slot.start_node, "inputs.image", reference_images[0])
        ref_nodes.append(ref_slot.start_node)
        for i, name in enumerate(reference_images[1:], start=1):
            assert ref_slot.extra_node_base is not None
            node_id = str(ref_slot.extra_node_base + i - 1)
            if node_id in workflow:
                raise GenerationFailedError(
                    f"generated reference node id {node_id!r} already exists in template", code="config_error"
                )
            workflow[node_id] = _load_image_node(name, f"LoadImage (reference {i + 1})")
            ref_nodes.append(node_id)

    nodes = [tgt.node, *ref_nodes]
    if variant.encoder_node:
        for i, node_id in enumerate(nodes, start=1):
            _set_path(workflow, variant.encoder_node, f"inputs.images.image_{i}", [node_id, 0])
    batch_node = slots.batch.node if slots.batch else None
    if batch_node:
        for i, node_id in enumerate(nodes):
            _set_path(workflow, batch_node, f"inputs.images.image{i}", [node_id, 0])
    # Explicit targets: Nth image (1-based) -> node input.
    for path, node_id in variant.image_targets.items():
        if not path.startswith("inputs."):
            continue
        m = re.search(r"(\d+)$", path)
        idx = int(m.group(1)) if m else 0
        if idx >= len(nodes):
            raise ValidationError(
                f"too many input images ({len(nodes)}); model has {len(variant.image_targets)} slots",
                param="image",
            )
        _set_path(workflow, node_id, path, [nodes[idx], 0])

    return {
        "target": {"node": tgt.node, "image": target_image},
        "references": [{"node": n, "image": img} for n, img in zip(ref_nodes, reference_images, strict=True)],
    }


# -- validation -------------------------------------------------------------


def _option_list(spec: Any) -> list[Any] | None:
    """Extract allowed values from a COMBO-style input spec.

    Handles plain COMBO options, dynamic combos (``key``/``inputs`` objects) and
    autogrow slots. Returns ``None`` when the value space is not enumerable.
    """
    if not isinstance(spec, list) or not spec:
        return None
    head = spec[0]
    if isinstance(head, list):
        return head
    if isinstance(head, str) and head.startswith((COMFY_AUTOGROW_PREFIX, COMFY_DYNAMICCOMBO_PREFIX)):
        return None
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    options = opts.get("options")
    if isinstance(options, list):
        if options and isinstance(options[0], dict) and "key" in options[0]:
            return [o["key"] for o in options]
        return options
    return None


def _dynamic_combo(spec: Any) -> dict[str, Any] | None:
    """Return the ``key -> inputs`` map for a dynamic combo, if the input is one."""
    if not isinstance(spec, list) or not spec:
        return None
    head = spec[0]
    if not (isinstance(head, str) and head.startswith(COMFY_DYNAMICCOMBO_PREFIX)):
        return None
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    options = opts.get("options")
    if not isinstance(options, list):
        return None
    return {o["key"]: o.get("inputs", {}) for o in options if isinstance(o, dict) and "key" in o}


def _autogrow_prefix(spec: Any) -> str | None:
    """Autogrow slots take flat ``<prefix>N`` keys; the prefix comes from the
    template (or the slot name when the template omits it)."""
    if not isinstance(spec, list) or not spec:
        return None
    head = spec[0]
    if not (isinstance(head, str) and head.startswith(COMFY_AUTOGROW_PREFIX)):
        return None
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    template = opts.get("template") or {}
    prefix = template.get("prefix")
    if prefix is None:
        names = template.get("names") or []
        if names:
            prefix = re.sub(r"\d+$", "", str(names[0]))
    return prefix


def _autogrow_keys(spec: Any) -> list[str]:
    """All flat key names an autogrow slot may take.

    Templates may declare an explicit ``names`` list (``a``..``z``), a numeric
    ``prefix`` (``image`` -> ``image0``, ``image1``, ...), or nest the input in a
    ``template.input.required`` mapping (``values.a`` style dotted keys).
    """
    if not isinstance(spec, list) or not spec:
        return []
    head = spec[0]
    if not (isinstance(head, str) and head.startswith(COMFY_AUTOGROW_PREFIX)):
        return []
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    template = opts.get("template") or {}
    names = template.get("names")
    if isinstance(names, list) and names:
        return [str(n) for n in names]
    prefix = template.get("prefix")
    if prefix:
        return [f"{prefix}{i}" for i in range(50)]
    nested = (template.get("input") or {}).get("required")
    if isinstance(nested, dict):
        return list(nested)
    return []


def _autogrow_min(spec: Any) -> int:
    if not isinstance(spec, list) or len(spec) < 2 or not isinstance(spec[1], dict):
        return 0
    return int((spec[1].get("template") or {}).get("min", 0))


def _autogrow_max(spec: Any) -> int | None:
    if not isinstance(spec, list) or len(spec) < 2 or not isinstance(spec[1], dict):
        return None
    value = (spec[1].get("template") or {}).get("max")
    return int(value) if value is not None else None


def _is_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def validate_workflow(
    workflow: dict[str, Any],
    object_info: dict[str, Any],
    *,
    skip_nodes: set[str] | None = None,
) -> list[str]:
    """Validate against node schemas. Returns a list of problems (empty == valid).

    ``skip_nodes`` are validated for existence and links only; their inputs are
    supplied at runtime (e.g. from nodes whose wiring is not schema-checkable).
    """
    problems: list[str] = []
    if not isinstance(workflow, dict) or not workflow:
        return ["workflow is empty"]
    skip_nodes = skip_nodes or set()
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            problems.append(f"node {node_id}: missing class_type")
            continue
        ct = node["class_type"]
        schema = object_info.get(ct)
        if not schema:
            problems.append(f"node {node_id}: unknown class_type {ct!r} on this backend")
            continue
        if node_id in skip_nodes:
            continue
        inputs = node.get("inputs", {}) or {}
        schema_input = schema.get("input", {}) or {}
        required = schema_input.get("required", {}) or {}
        optional = schema_input.get("optional", {}) or {}
        # ``hidden`` inputs are injected by ComfyUI at execution time
        # (e.g. PreviewImage's prompt/extra_pnginfo) and must not be required here.
        hidden = schema_input.get("hidden", {}) or {}
        required = {k: v for k, v in required.items() if k not in hidden}

        # Autogrow slots: at least ``template.min`` entries must be present, using
        # the slot's declared names (``a``..``z``) or numeric prefix.
        for name, spec in required.items():
            keys = _autogrow_keys(spec)
            if not keys:
                continue
            minimum = _autogrow_min(spec)
            maximum = _autogrow_max(spec)
            # Autogrow entries may be supplied directly (``a``), dotted under the
            # slot name (``values.a``), or nested (``values: {a: ...}``).
            nested = inputs.get(name)
            nested = nested if isinstance(nested, dict) else {}
            present = [k for k in inputs if k in keys or k.split(".", 1)[-1] in keys]
            present += [k for k in nested if k in keys]
            if len(present) < minimum:
                problems.append(
                    f"node {node_id} ({ct}): needs at least {minimum} '{keys[0]}'-style inputs, "
                    f"found {len(present)}"
                )
            if maximum is not None and len(present) > maximum:
                problems.append(
                    f"node {node_id} ({ct}): allows at most {maximum} '{keys[0]}'-style inputs, "
                    f"found {len(present)}"
                )

        for name, spec in {**required, **optional}.items():
            keys = _autogrow_keys(spec)
            if keys:
                # Dotted form (``values.a``) satisfies the slot without the bare name.
                dotted = any(k.startswith(f"{name}.") for k in inputs)
                if name not in inputs and not dotted and _autogrow_min(spec) > 0:
                    problems.append(f"node {node_id} ({ct}): missing required input {name!r}")
                continue
            if name not in inputs:
                if name in required:
                    problems.append(f"node {node_id} ({ct}): missing required input {name!r}")
                continue
            value = inputs[name]
            if _is_link(value):
                src, slot = value
                if src not in workflow:
                    problems.append(f"node {node_id}.{name}: links to missing node {src!r}")
                else:
                    src_schema = object_info.get(workflow[src].get("class_type", ""))
                    if src_schema is not None:
                        out_types = src_schema.get("output") or []
                        if slot >= len(out_types):
                            problems.append(f"node {node_id}.{name}: slot {slot} out of range on node {src}")
                continue
            allowed = _option_list(spec)
            if allowed is not None and isinstance(value, (str, int, float, bool)):
                if value not in allowed:
                    problems.append(f"node {node_id} ({ct}): {name}={value!r} not allowed; expected one of {allowed[:12]}")
                continue
            dynamic = _dynamic_combo(spec)
            if dynamic is not None and isinstance(value, str):
                if value not in dynamic:
                    problems.append(
                        f"node {node_id} ({ct}): {name}={value!r} not allowed; expected one of {list(dynamic)}"
                    )
                    continue
                # Flat sub-keys for the selected option must satisfy its own required inputs.
                sub_req = (dynamic.get(value, {}) or {}).get("required", {}) or {}
                for sub_name in sub_req:
                    if f"{name}.{sub_name}" not in inputs:
                        problems.append(
                            f"node {node_id} ({ct}): missing '{name}.{sub_name}' required by {name}={value!r}"
                        )
    return problems


def validate_against_backend(
    workflow: dict[str, Any],
    object_info: dict[str, Any],
    *,
    skip_nodes: set[str] | None = None,
) -> None:
    """Validate a compiled workflow; ``skip_nodes`` holds nodes whose inputs are
    runtime values (e.g. uploaded image names) that the schema cannot predict.

    Link targets are always checked against the *full* workflow, so a skipped node
    is still a valid source for other nodes.
    """
    if skip_nodes:
        problems = validate_workflow(workflow, object_info, skip_nodes=skip_nodes)
        problems += _check_links_all(workflow)
    else:
        problems = validate_workflow(workflow, object_info)
    if problems:
        raise GenerationFailedError(
            "compiled workflow failed validation: " + "; ".join(problems[:8]),
            code="workflow_invalid",
            details={"problems": problems},
        )


def _check_links_all(workflow: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for node_id, node in workflow.items():
        for name, value in ((node.get("inputs") or {}) if isinstance(node, dict) else {}).items():
            if _is_link(value) and value[0] not in workflow:
                problems.append(f"node {node_id}.{name}: links to missing node {value[0]!r}")
    return problems


def nodes_missing_inputs(workflow: dict[str, Any], object_info: dict[str, Any],
                         types: set[str]) -> set[str]:
    """Nodes whose required inputs of the given types are absent from the template.

    Runtime wiring (uploaded images) may supply them, so validation skips these
    nodes' own inputs while still checking that their links resolve.
    """
    out: set[str] = set()
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        schema = object_info.get(node.get("class_type", ""))
        if not schema:
            continue
        required = (schema.get("input", {}) or {}).get("required", {}) or {}
        inputs = node.get("inputs") or {}
        for name, spec in required.items():
            if name in inputs:
                continue
            head = spec[0] if isinstance(spec, list) and spec else None
            if isinstance(head, str) and head in types:
                out.add(node_id)
                break
    return out


def compile_workflow(
    cfg: Config,
    variant: ModelVariant,
    values: dict[str, Any],
) -> CompiledWorkflow:
    """Load, copy, apply static overrides and inject normalized values."""
    workflow = copy.deepcopy(load_template(cfg, variant))
    apply_static(workflow, variant)
    applied = inject_values(workflow, variant, values)
    return CompiledWorkflow(
        workflow=workflow,
        alias=variant.alias,
        backend_id=variant.backend,
        notes={"applied": applied},
    )


def load_image_node_ids(variant: ModelVariant, n_images: int) -> set[str]:
    """Ids of LoadImage nodes that will hold runtime upload names.

    ``n_images`` is the total number of input images (target + references).
    Optional reference nodes are only included when a reference is supplied.
    """
    slots = variant.image_slots
    if slots is None:
        return set()
    ids: set[str] = set()
    if slots.target.node:
        ids.add(slots.target.node)
    ref = slots.reference
    if n_images > 1:
        if ref and ref.start_node:
            ids.add(ref.start_node)
        if ref and ref.extra_node_base is not None:
            for i in range(1, n_images - 1):
                ids.add(str(ref.extra_node_base + i - 1))
    elif ref and ref.optional and ref.start_node:
        # Single-image request with an optional reference slot: the node was dropped.
        ids.add(ref.start_node)
    ids.update(variant.image_targets.values())
    return ids
