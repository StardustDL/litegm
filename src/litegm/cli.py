"""Command line entry point.

``litegm serve --config <path>`` starts the gateway. The app object is exposed at
``litegm.app:create_app`` for ASGI servers, configured through ``LITEGM_CONFIG``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .app import configure_logging, create_app
from .config import load_config


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="litegm", description="OpenAI-compatible media gateway for ComfyUI")
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the gateway")
    serve.add_argument("--config", required=True, help="path to litegm.yaml")
    serve.add_argument("--base-dir", default=None,
                       help="directory that relative config paths resolve against (default: cwd)")
    serve.add_argument("--host", default=None, help="override server.host")
    serve.add_argument("--port", type=int, default=None, help="override server.port")

    check = sub.add_parser("check", help="validate a config and the backend workflow schemas")
    check.add_argument("--config", required=True)
    check.add_argument("--base-dir", default=None)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    base_dir = args.base_dir or os.environ.get("LITEGM_BASE_DIR") or os.getcwd()
    try:
        cfg = load_config(args.config, base_dir=base_dir)
    except Exception as exc:  # noqa: BLE001 - config errors must be readable
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        return _check(cfg)

    configure_logging(cfg.server.log_level)
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    os.environ["LITEGM_CONFIG"] = str(Path(args.config).resolve())
    os.environ.setdefault("LITEGM_BASE_DIR", str(Path(base_dir).resolve()))

    import uvicorn

    app = create_app(cfg)
    # Remember where the config came from so it can be hot-reloaded later.
    app.state.config_path = str(Path(args.config).resolve())
    app.state.base_dir = str(Path(base_dir).resolve())
    uvicorn.run(app, host=host, port=port, log_level=cfg.server.log_level)
    return 0


def _check(cfg) -> int:
    """Validate every model variant against its backend's node schemas."""
    import asyncio

    from .backends import BackendRegistry
    from .workflow import (
        compile_workflow,
        load_image_node_ids,
        validate_against_backend,
        validate_workflow,
    )

    async def run() -> int:
        registry = BackendRegistry(cfg)
        rc = 0
        try:
            for task_name, task in cfg.tasks.items():
                for m in task.models:
                    client = registry.get(m.backend)
                    try:
                        info = await client.object_info()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[{task_name}/{m.alias}] backend {m.backend} unreachable: {exc}")
                        rc = 1
                        continue
                    compiled = compile_workflow(cfg, m, {"prompt": "check", "passthrough": "check"})
                    # Image slots and their batch feeder hold runtime upload names;
                    # their own inputs are skipped, but link targets are still checked.
                    skip = load_image_node_ids(m, 3)
                    if m.image_slots and m.image_slots.batch and m.image_slots.batch.node:
                        skip.add(m.image_slots.batch.node)
                    if m.image_slots and m.image_slots.target.node:
                        # Downstream nodes consume the LoadImage output; their required
                        # inputs are satisfied at runtime, not in the raw template.
                        skip |= _downstream_nodes(compiled.workflow, m.image_slots.target.node)
                        # Image-derived inputs (e.g. the first frame's size) are not
                        # present in the template at all; skip nodes with missing
                        # image-typed inputs on the same chain.
                        skip |= _nodes_missing_inputs(compiled.workflow, info, {"IMAGE"})
                    for node_id in m.image_targets.values():
                        skip |= _downstream_nodes(compiled.workflow, node_id)
                    try:
                        validate_against_backend(compiled.workflow, info, skip_nodes=skip)
                        print(f"[{task_name}/{m.alias}] ok")
                    except Exception as exc:  # noqa: BLE001
                        rc = 1
                        print(f"[{task_name}/{m.alias}] INVALID: {exc}")
                        for p in (getattr(exc, "details", {}) or {}).get("problems", []):
                            print(f"    - {p}")
        finally:
            await registry.aclose()
        return rc

    return asyncio.run(run())


def _downstream_nodes(workflow: dict, source_node: str) -> set[str]:
    """Nodes that consume ``source_node``'s output, transitively.

    During ``check`` the image input is not yet uploaded, so nodes fed from the
    image-loading chain are validated for links only, not for required inputs.
    """
    out: set[str] = set()
    frontier = {source_node}
    while frontier:
        nxt: set[str] = set()
        for node_id, node in workflow.items():
            if node_id in out or node_id == source_node:
                continue
            inputs = (node.get("inputs") or {}) if isinstance(node, dict) else {}
            if any(
                isinstance(v, list) and len(v) == 2 and v[0] in frontier
                for v in inputs.values()
            ):
                nxt.add(node_id)
        out |= nxt
        frontier = nxt
    return out


def _nodes_missing_inputs(workflow: dict, object_info: dict, types: set[str]) -> set[str]:
    from .workflow import nodes_missing_inputs

    return nodes_missing_inputs(workflow, object_info, types)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
