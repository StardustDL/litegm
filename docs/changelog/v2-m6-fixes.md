# M6 (v2) — Pre-requisite fixes: n, quality, output formats, queueing

Date: 2026-10-23
Status: completed and verified live

## Scope

Close the v1 gaps identified in the v2 plan review before adding video/audio:

* G1 — `n` produced only one image;
* G2 — `quality` was accepted but had no effect;
* G3 — only PNG output was possible;
* G4 — the configured per-backend concurrency limit was not enforced;
* G5 — no gateway-side queueing or backpressure.

## Changes

### G1 — multiple images

The engine now submits the workflow `n` times with distinct seeds
(`seed, seed+1, …`) inside a single task, collecting one artifact per run. The
templates do not support batching, so this is the reliable path; it runs within the
backend's concurrency slot, so it does not multiply GPU load.

Verified: `n=2` → 2 images (512×512, 5.3s total).

### G2 — quality mapping

New configuration field `constraints.quality_map` maps OpenAI `quality` values to
workflow parameters. Applied through inject mappings named `quality_steps`, so a
template exposes its sampling node once and the map sets concrete values:

```yaml
quality_map:
  low: {steps: 12}
  medium: {steps: 25}
  high: {steps: 40}
```

Configured for `qwen-image-2.1` and `moss-image` (KSampler-based; the Z-Image
family was configured the same way at the time but is no longer part of the
shipped example). The turbo variants have no map — their step count is
fixed by `ManualSigmas` — so `quality` is accepted and inert there (documented).
`standard` maps to `auto`, `hd` maps to `high`.

Verified: `qwen-image-2.1` with `quality=low` compiled a workflow with
`KSampler.steps = 12`.

### G3 — output formats

`output_formats` now includes `png`, `webp` and `jpeg`. ComfyUI saves PNG; when the
request asks for `webp`/`jpeg`, the artifact is converted with Pillow honouring
`output_compression` (default quality 90). `background=transparent` requires PNG and
is rejected otherwise. The response `size` is derived from the produced artifact.

Verified: `output_format=webp` returned a RIFF/WebP payload (39 KB).

### G4/G5 — queueing and backpressure

`Engine` now owns a bounded per-backend queue:

* at most `backends[].concurrency` tasks execute concurrently;
* at most `backends[].queue_max` (new, default 20) tasks may wait;
* beyond that, submissions fail fast with HTTP 429
  (`rate_limit_exceeded`) before any GPU work;
* tasks report `queued`/`waiting` while waiting for a slot.

Queue depth is exposed in `/v1/health` and the admin health panel (`queues`).

Verified: 30 concurrent requests against `concurrency=1, queue_max=20` → 20 × 200,
10 × 429 with a clear message. A separate 4-request burst was serialized
correctly.

## Files

* `src/litegm/engine.py` — bounded queue, multi-image execution, quality injection,
  format conversion
* `src/litegm/config.py` — `quality_map`, `queue_max`
* `src/litegm/requests.py` — quality mapping, transparent/webp rule
* `src/litegm/api.py`, `src/litegm/admin.py` — queue stats in health
* `config/litegm.yaml` — quality maps, multi-format, `quality_steps` inject
* `web/src/App.tsx` — queue display
* `tests/test_requests.py` — 5 new tests (quality, n, formats, transparent)

Unit tests: 29 passed. Essential live verification: 3/3 (unified generate/edit,
dedicated edit).
