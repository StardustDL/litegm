# M8 (v2) — Audio generation (custom extension)

Date: 2026-10-24
Status: completed and verified live

## Scope

Expose MiniMax Music3 through a custom audio endpoint that reuses the same
asynchronous task protocol as video (as agreed in the v2 plan: D3), so callers
poll and download identically.

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/audio/generations` | Create a job: `input` (caption), `lyrics`, `seconds`, `model`, `seed` (JSON or multipart) |
| GET | `/v1/audio/{id}` | Poll: `object:"audio"`, `status`, `progress`, `error`, `duration` |
| GET | `/v1/audio/{id}/content` | Download the FLAC |
| GET | `/v1/audio` | List jobs |
| DELETE | `/v1/audio/{id}` | Delete job and artifacts |

## Configuration

`tasks.audio.generate` → `minimax-music3` with injection onto
`MiniMaxMusic3TextEncode` (caption/lyrics/duration/seed) and
`EmptyMiniMaxMusic3LatentAudio.seconds`, cfg 1.7 and 30 steps fixed. Duration is
clamped to 5–300s with a 30s default (no frame-grid snapping — that is video-only).

## Verification

| Job | Settings | Result |
|-----|----------|--------|
| Music3 | 10s, short caption + lyrics | completed; 747 KB FLAC downloaded via `/content` |

Unit tests: 42 passed (5 new audio tests).

## Issues found and fixed

1. Audio requests were routed through image output validation
   (`output_format` must be png/webp/jpeg) — audio now has its own branch.
2. Audio inherited the video frame-grid snapping; `resolve_duration` now takes
   `snap_frames` and audio only clamps to its limits.
