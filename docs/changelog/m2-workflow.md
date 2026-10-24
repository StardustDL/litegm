# M2 — Workflow compilation and pre-submit validation

Date: 2026-10-23
Status: completed

## Scope

Compile a configured workflow template plus a normalized request into a concrete
ComfyUI API workflow, wire uploaded images into configured slots, and validate the
result against the backend's real node schemas before anything is queued.

## What was built

| File | Purpose |
|------|---------|
| `src/litegm/workflow.py` | Template loading, `static` overrides, `inject` mapping (node id + inputs path), passthrough synchronization, image slot wiring (target / reference / dynamically created nodes / batch feeder), schema validation |
| `src/litegm/requests.py` | Normalized request model; size snapping to the model's step/bounds, prompt-driven aspect inference for `size=auto`, `n` bounds, output parameter validation |
| `src/litegm/engine.py` | Task execution: upload → compile → validate → submit → poll → download → record, with configured fallback chains and cancellation |
| `config/litegm.yaml` | One ComfyUI backend and four model aliases: `qwen-image-2.1-turbo`, `qwen-image-2.1-turbo-pe` (fallback to the first), `qwen-image-2.1-turbo-edit`, `qwen-image-2.1-turbo-edit-pe` |
| `config/workflows/*.json` | Copies of the turbo t2i and turbo edit API-format templates |
| `tests/test_requests.py`, `tests/test_workflow.py` | 17 unit tests (all passing) |
| `src/litegm/cli.py` (`check`) | Validates every alias against the live backend's `/object_info` |

## Validation model

`validate_workflow()` checks, against `/object_info`:

* unknown `class_type`;
* missing required inputs;
* combo / dynamic-combo values (including flat sub-keys required by the selected option);
* autogrow slots: required `min`/`max` counts of `<prefix>N` keys;
* dangling links and out-of-range output slots (nested autogrow links included).

Nodes whose inputs are runtime values (uploaded image names, and the batch feeder
that receives them) are skipped for their own inputs but still checked as link
sources — that distinction was needed because the Qwen edit workflow's PE node links
to the batch node.

## Verified against the live server

`litegm check --config config/litegm.yaml --base-dir .`:

```
[image.generate/qwen-image-2.1-turbo] ok
[image.generate/qwen-image-2.1-turbo-pe] ok
[image.edit/qwen-image-2.1-turbo-edit] ok
[image.edit/qwen-image-2.1-turbo-edit-pe] ok
```

The shipped templates themselves also validate (the `TextEncodeQwenImage21.images`
autogrow slot is declared required with `min: 0`, so an empty slot is legal).

## Problems found and fixed during implementation

1. **Passthrough could emit an empty prompt.** The t2i template's `ComfySwitchNode`
   `on_false` default is `""`; injecting only the PE prompt left the pass-through path
   blank. `inject_values()` now mirrors `prompt` into the configured `passthrough`
   mapping whenever both exist.
2. **Autogrow prefix detection.** `TextEncodeQwenImage21.images` has no `template.prefix`
   (it uses `names: ["image_1", ...]`), so the prefix is derived from the first name.
3. **Skip semantics.** Filtering skipped nodes out of the dict before validation broke
   link checks from other nodes; validation now takes an explicit skip set and always
   checks links against the full workflow.
4. **Image slot wiring** matches the reference script's layout: `470` target, `475`
   first reference, additional `LoadImage` nodes from `510`, and `images.image_N` /
   `images.imageN` links into the encoder (`474`) and PE batch (`485`), clearing stale
   template links first.

## Configuration surface exercised

* `inject` (prompt, passthrough, width, height, seed, filename prefix)
* `static` (switch/thinking flags, custom-size switch)
* `image_slots` + `encoder_node` (edit variants)
* `mask_policy: unsupported`
* `fallbacks` (PE variants fall back to the non-PE variant)

## Known limitations

* No mask / inpainting node is wired; `mask` requests are rejected with
  `unsupported_parameter` (per the approved design).
* Edit output canvas follows the input image (`custom_size=false`); the OpenAI `size`
  parameter is accepted but advisory for edit models (`size_policy: auto`).
