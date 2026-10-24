# v4 — Admin console redesign (Darkroom)

Date: 2026-10-24
Status: completed and verified live against the running gateway (127 real tasks:
images, videos, audio, failures)

## Goal

A second pass on the admin console, this time driven by aesthetics and usability:
a deliberate visual language, information architecture built around how operators
actually work, and the interaction affordances (keyboard, bulk actions, live
progress, constraint-driven forms) that make the console pleasant to use rather
than merely functional.

## Design direction — "Darkroom"

A dark photographic darkroom: ink surfaces, a warm safelight accent, film grain,
hairline structure, and media presented as framed prints. The typographic voice
is split between technical mono (ids, seeds, node graphs, seeds) and a calm
reading voice. The palette and spacing live in one place so the look can be
retuned centrally:

| Layer | Where |
|-------|-------|
| Colour tokens (`ink`, `amber`, `jade`, `coral`, `azure`, `violet`, `fg`), type scale, shadows, animations | `web/tailwind.config.js` |
| Base surfaces, grain, safelight wash, `.surface`, `.btn*`, `.field`, `.pill*`, `.data-table`, `.print-frame`, `.checker`, `.kbd`, `.eyebrow`, `.display` | `web/src/index.css` |
| Hand-drawn icon family (50 glyphs) | `web/src/icons.tsx` |
| UI kit: toasts, dialogs, lightbox, JSON viewer, media thumbs, progress, skeletons | `web/src/ui.tsx` |
| Formatting and status vocabulary | `web/src/format.ts`, `web/src/components.tsx` |
| Shell, rail navigation, command palette, shortcuts, login | `web/src/Shell.tsx`, `web/src/App.tsx` |

## Information architecture

Addressable routes via the URL hash (`#tasks`, `#studio`, `#system`,
`#tasks/<task_id>`):

- **概览 (Overview)** — a live pulse: in-flight/failed counters, a 24-hour
  submission histogram, backend and queue lanes, storage budget, a recent-media
  strip, a failure digest with per-row retry and error distribution, routing
  summary.
- **任务库 (Task history)** — a gallery of framed prints (uniform 4-column grid,
  typographic covers for tasks with no media, small play chip for videos) and a
  dense sortable table; facets for status/type/model/backend/time window/date
  range plus text search; bulk select → retry/delete/export; pagination;
  designed empty/loading/error states.
- **创作台 (Studio)** — mode switcher driven by the live model catalog and the
  per-model constraints from the gateway config: aspect-ratio size presets
  computed from `size_step`/`min_edge`/`max_edge`, n stepper capped at `n_max`,
  format/quality chips from `output_formats`/`quality_map`, duration slider
  bounded by `duration_min/max/step`, drag-to-reorder reference tray with role
  labels, submit at the end of the parameter column, live stage progress, framed
  results, open-detail/again actions.
- **系统 (System)** — backend health with queue lanes and RAM/VRAM meters,
  storage budget and retention policy, server config, routing/model/capability
  tabs, hot reload with explicit restart-required reporting, guarded manual
  sweep.
- **Task detail** — a print-style artifact mount with lightbox, input-vs-output
  comparison with role labels, structured request parameters, model constraints,
  execution panel with attempts, a reverse-chronological event timeline with
  kind-specific rendering, workflow JSON, and a sticky action bar.

## Usability work

- Keyboard: ⌘K// command palette (navigation, actions, task search with media
  thumbs), `g`+`o`/`t`/`s`/`y` jumps, `?` shortcut sheet, Esc to close overlays,
  ←/→ in the lightbox.
- Destructive actions go through inline confirmation dialogs with explicit copy;
  every mutation reports through toasts.
- Live SSE-driven refresh with a visible stream indicator and a pause switch.
- Responsive: the desktop rail collapses to a bottom bar under 768 px; the top
  bar sheds breadcrumb and live badge on narrow screens; grids reflow.
- Accessibility: focus-visible rings, aria labels on icon-only controls,
  keyboard-reachable dialogs, text equivalents for charts, ≥4.5:1 secondary text,
  `prefers-reduced-motion` respected.

## Backend support (additive, backwards compatible)

- `GET /admin/api/artifacts/{id}/thumb?size=64..1024` and
  `GET /admin/api/tasks/{id}/inputs/{idx}/thumb` — Pillow-rendered JPEG
  thumbnails cached on disk under `<storage.root>/.thumbs` keyed on artifact id,
  size and source mtime/size; video frames via ffmpeg when installed, otherwise a
  neutral film-frame placeholder; `Cache-Control: public, max-age=86400` + strong
  ETag; 404 for unknown/missing.
- Task list items gain `preview` / `input_preview` (first artifact and first
  uploaded input) so the gallery renders without N+1 detail calls; a batch
  `input_images_for_tasks` keeps `limit=100` at 4 queries and ~11 ms.
- Task detail gains `duration_s`, `artifact_previews`, `input_previews`.
- GZip for responses ≥ 1 KB (config JSON 8.4 KB → 903 B; task detail 16–17 KB
  compressed) and immutable cache headers for content-hashed `/admin/assets/*`
  while `index.html` stays `no-cache`.
- The request-logging middleware was rewritten as ASGI-native because
  `BaseHTTPMiddleware` re-emits bodies as `more_body=True`, which silently
  defeated Starlette's gzip size gate. Logging, request-id echo, metrics and the
  SSE exclusion behave identically.

## Tooling

- `scripts/ui_shot.py` now captures `overview`, `tasks`, `studio`, `system`,
  `detail` (auto-resolves a media task) and raw hashes such as
  `#tasks/task_...`; supports full-page capture and viewport overrides.
- `scripts/ui_shot_auth.py` logs in, injects the session cookie and captures the
  console for deployments that keep authentication enabled.
- `scripts/fix_utf8.py` detects and repairs UTF-8 files whose CJK characters were
  truncated by a non-UTF-8 console (reports each repair).
- `scripts/check_doc_links.py` validates that relative Markdown links resolve.

## Documentation (added in this milestone)

- `README.md` — user-facing overview: capabilities, quick start, Docker
  deployment, configuration summary, documentation map and limitations.
- `docs/development.md` — developer guide: toolchain, repository layout,
  server and frontend module indexes, key-mechanism change points, testing and
  scripts, extension guide, and commit conventions.
- `docs/README.md` — documentation index grouped by audience.
- `AGENTS.md` — agent guide: code map, mandatory conventions, verification
  commands, Windows pitfalls (UTF-8 truncation, PATH, container healthcheck),
  and common change recipes.
- `docs/usage.md` and `docs/api.md` updated for the containerised deployment
  (port, mounts, healthcheck) and the v4 admin API additions.

## Deployment (production stack)

- `docker-compose.yml` runs a single published port (8080), overrides
  `--host/--port` so `server.port` matches the published port, mounts
  `./config` and `./data`, and reads `LITEGM_MASTER_KEY` from `.env`
  (git-ignored).
- The container healthcheck goes through `pixi run`: the runtime image has no
  `python` on PATH, which previously made the probe fail with
  `executable file not found`.
- Verified live: container healthy, API auth enforced, 16 model aliases listed,
  real 512×512 generation succeeded, thumbnails served, config mount matches
  the host file byte-for-byte.

## Verification

| Check | Result |
|-------|--------|
| TypeScript strict type-check (`tsc -b`) | clean |
| Production build (`vite build`) | 42 modules; 420 kB JS (120 kB gzip), 57 kB CSS (10 kB gzip) |
| Unit tests (`pytest -m "not integration"`) | 78 passed |
| Live gzip / cache headers | config gzip'd; small `/me` untouched; hashed assets `immutable`; index `no-cache` |
| Live previews | task list items carry artifact/input previews; detail exposes `duration_s` |
| Visual QA (headless Edge, live data) | overview, tasks (gallery + facets), detail (image and video), studio, system captured and reviewed; narrow viewport verified |
| Login screen | dark split layout renders when auth is enabled |
| Documentation links | 24 Markdown files, 0 broken relative links |
| Container deployment | healthy; API and admin auth enforced; real generation verified |

## Known limitations

- Video thumbnails fell back to the placeholder frame where ffmpeg was not on PATH;
  the later v4.1 milestone ships ffmpeg in the runtime environment, so real
  first-frame thumbnails need no code change.
- Real step-level progress still uses the v3 estimated model (`/ws` deferred).
- The console is a single-admin tool: no multi-user roles.
