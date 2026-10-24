# M7 (v2) — OpenAI-compatible video generation API

Date: 2026-10-24
Status: completed and verified live

## Scope

Implement OpenAI's native asynchronous video protocol on top of the task engine,
and wire the three MiniMax H3 workflows (T2V / I2V / R2V) through configuration.

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/videos` | Create a job (multipart: `prompt`, `model`, `seconds`, `size`, `input_reference` / `first_frame` / `reference_images`) |
| GET | `/v1/videos/{id}` | Poll: `object:"video"`, `status` (`queued`/`in_progress`/`completed`/`failed`), `progress`, `error` |
| GET | `/v1/videos/{id}/content` | Download (`variant=video`), Bearer auth |
| GET | `/v1/videos` | List recent jobs (cursor-style fields `first_id`/`last_id`/`has_more`) |
| DELETE | `/v1/videos/{id}` | Delete the job, its artifacts and record |

Routing is configuration-driven: `input_reference`/`first_frame` selects an
image-to-video alias, `reference_images` a reference-to-video alias, otherwise a
text-to-video alias.

## Configuration (H3)

Added `tasks.video.generate` with three aliases:
`minimax-h3-t2v`, `minimax-h3-i2v` (single input image), `minimax-h3-r2v`
(two reference images via the new `image_targets` mapping). Templates copied into
`config/workflows/`.

Duration is clamped and quantised to H3's 17k+5 frame grid at 24 fps
(`duration_step: 17/24`), with a configurable maximum (15s) and default (2s).
Resolution defaults to 864×480; the I2V path derives its size from the uploaded
frame.

## Platform capabilities added

* `image_targets` (config): map the Nth uploaded image onto arbitrary node inputs
  (`ref_images.ref_image_0` → `137`, `ref_images.ref_image_1` → `139`).
* Autogrow validation now understands nested (`template.input.required`) slots and
  dotted (`values.a`) inputs.
* `check` / runtime validation skip nodes fed by runtime image wiring (an i2v
  pipeline's `ImageScaleToTotalPixels` has no template input at all).

## Verification (tiny clips only, per project rules)

| Job | Settings | Result |
|-----|----------|--------|
| T2V | 384×256, 1s | completed, mp4 631 KB downloaded via `/content` |
| I2V | 384×256, 1s, reference PNG | completed, mp4 568 KB |
| List / delete | — | list returns jobs with OpenAI shape; delete → 200, then GET → 404 |

Unit tests: 37 passed (8 new video tests covering routing, duration snapping,
image requirements and status mapping).

## Issues found and fixed during verification

1. `output_format` missing from the video normalization path (KeyError).
2. t2v was configured to fall back to the i2v variant, which requires an image —
   fallback removed.
3. `compiled` referenced before assignment in the multi-image loop (broke i2v).
4. DELETE left the task row behind; now removes the record (OpenAI semantics).
5. Duration snapping produced off-grid frame counts; now always 17k+5 with k ≥ 1.

Note: the backend returned transient 502s while loading the H3 weights (and the
service was restarted once by the operator due to VRAM pressure); retries
succeeded. The gateway surfaced these as `backend_unavailable`.
