# v4 UI redesign — internal design brief (working document)

> Scope: visual + usability overhaul of the admin console (`web/`). Backend changes
> are limited to additive, read-only helpers the UI needs (thumbnails, gzip, list
> enrichments). No behaviour of the generation API changes.

## Product read

The console is the operator-facing control room for a private, self-hosted
ComfyUI generation gateway. Its real users are the person who runs the GPU box
and the people who generate media on it. They need to:

1. see what is running, what failed and why — fast;
2. find an earlier result and compare inputs against outputs;
3. iterate on prompts in a studio-like composer without leaving the console;
4. trust the box: backend, queue, disk budget, config routing.

## Design language — "Darkroom"

A dark, photographic darkroom aesthetic: deep ink surfaces, warm amber accent
(the safelight), film grain texture, thin hairlines, and typographic contrast
between a technical mono voice (ids, seeds, node graphs) and a calm reading
voice. Media is the hero: generated images/videos are presented in framed,
light-tight mounts so they read like prints on a wall, not like table cells.

- Palette: ink #08090c → #171a21 surfaces; amber #f0b04a accent; teal #45d6c4
  and rose #ff6b81 only for status semantics; neutral greys for secondary text.
- Type: system UI sans for copy (Inter/Segoe/PingFang), mono for identifiers.
  Scale: 11/12/13/14/16/20/28/40 with tight tracking on large sizes.
- Motion: 120–220 ms ease-out; no bounce; progress shimmer only while running.
- Texture: 2–3 % opacity grain overlay on the app background, 1 px hairline
  dividers, inset highlights on glass surfaces. No heavy shadows.
- Density: comfortable by default, compact mode for the history table.

## Information architecture

Left icon rail (72 px) with labelled tooltips + a collapsible detail panel:
Overview · History · Studio · System. Top bar carries breadcrumb, global search
(⌘K command palette), live-stream indicator and the session menu. Content uses a
12-column grid with a sticky right-hand inspector where relevant.

Views:

- **Overview**: live pulse (running tasks, queue, backend, storage), recent
  gallery strip, failure digest with one-click retry, routing summary.
- **History**: gallery (masonry of media thumbnails) and table (dense, sortable)
  modes; facets for status/type/model/time; bulk select → retry/delete/export;
  row hover reveals inline actions; detail opens as a full page.
- **Task detail**: print-style artifact viewer with lightbox, input-vs-output
  comparison, request parameters as structured cards, execution timeline, raw
  JSON viewer with syntax colouring, sticky action bar.
- **Studio**: mode switcher (t2i / edit / video / audio) driven by the live model
  catalog and per-model constraints (sizes, durations, n_max, formats); prompt
  composer with token counter and quick presets; reference tray with drag-drop
  reordering and role labels; live progress card with stage timeline; results
  gallery with download/copy seed/open-detail.
- **System**: backend health cards with queue sparkline, storage budget ring,
  retention policy, routing tables, config hot-reload with diff summary.

## Usability requirements

- Full keyboard: ⌘K palette, `g h`/`g s`/`g y` jumps, `?` shortcuts sheet, Esc
  closes overlays, `/` focuses search.
- Every destructive action confirms inline (not window.confirm) with undo-safe
  wording; toasts report results.
- Empty, loading and error states designed for each surface; skeletons instead
  of spinners.
- Responsive: rail collapses to bottom bar under 768 px; grids reflow.
- Accessibility: focus rings, aria labels, ≥4.5:1 contrast on body text,
  prefers-reduced-motion respected.

## Backend additions (additive only)

- `GET /admin/api/artifacts/{id}/thumb` — cached JPEG/PNG thumbnails for image
  and video artifacts (Pillow already a dependency; ffmpeg not required).
- `GET /admin/api/tasks` list items gain `preview` (first artifact thumbnail URL,
  kind) and `input_preview` (first uploaded input thumbnail URL) so history can
  render media without N+1 detail calls.
- `GET /admin/api/tasks/{id}` gains `duration_s` and a compact `artifact_previews`.
- GZip middleware for JSON/HTML/text responses ≥ 1 KB (no new dependency) and
  immutable cache headers for hashed `/admin/assets/*`.
