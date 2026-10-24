"""Smoke-test a running litegm gateway against a small set of aliases.

Default behaviour is deliberately cheap: it verifies only the essential paths
(one text-to-image alias, one edit alias, and the unified model's routing) using a
small image size, because larger images dominate the wall-clock time on the
backend.

Usage:
    python scripts/verify_aliases.py --key <master key>
    python scripts/verify_aliases.py --key <key> --size 512x512 --aliases moss-image,qwen-image-2.1
    python scripts/verify_aliases.py --key <key> --all          # every configured alias

Checks status, timing and pixel statistics so all-black or empty results are caught.
Requests run sequentially because the backend is configured with concurrency=1.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import time
import urllib.request
from pathlib import Path

# Essential aliases: enough to cover text-to-image, editing and unified routing
# without regenerating every configured model on each run.
ESSENTIAL = ["qwen-image-2.1-turbo", "qwen-image-2.1-turbo-edit"]
SMALL_EDIT_SOURCE = 256


def post_json(url: str, payload: dict, key: str, timeout: float) -> tuple[int, dict, float]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp), time.time() - start
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body), time.time() - start
        except json.JSONDecodeError:
            return exc.code, {"raw": body}, time.time() - start


def post_edit(url: str, fields: dict, image_path: Path, key: str, timeout: float):
    boundary = "----litegmverify"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode() + image_path.read_bytes() + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp), time.time() - start
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body), time.time() - start
        except json.JSONDecodeError:
            return exc.code, {"raw": body}, time.time() - start


def _tasks(model: dict) -> list[str]:
    """Model capabilities list ``task`` either as a string or as a list (unified models)."""
    task = model.get("capabilities", {}).get("task")
    if isinstance(task, list):
        return task
    return [task] if task else []


def describe(b64: str) -> dict:
    from PIL import Image

    raw = base64.b64decode(b64)
    im = Image.open(io.BytesIO(raw))
    im.load()
    rgb = im.convert("RGB")
    total = count = 0
    step = max(1, (im.width * im.height) // 1024)
    for i in range(0, im.width * im.height, step):
        x, y = i % im.width, i // im.width
        r, g, b = rgb.getpixel((x, y))
        total += r + g + b
        count += 1
    return {
        "bytes": len(raw),
        "width": im.width,
        "height": im.height,
        "mode": im.mode,
        "mean": round(total / (count * 3), 1) if count else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--key", required=True)
    ap.add_argument("--size", default="512x512", help="output size for generation (default 512x512)")
    ap.add_argument("--aliases", default=",".join(ESSENTIAL),
                    help="comma-separated aliases to test; 'unified' expands to unified models")
    ap.add_argument("--all", action="store_true", help="test every configured alias (slow)")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--outdir", default=".cache/alias-verify")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(f"{base}/v1/models", headers={"Authorization": f"Bearer {args.key}"})
    models = json.load(urllib.request.urlopen(req, timeout=30))["data"]
    by_alias = {m["id"]: m for m in models}
    unified_ids = [m["id"] for m in models if m["capabilities"].get("unified")]

    if args.all:
        selected = [m["id"] for m in models]
    else:
        selected = [a.strip() for a in args.aliases.split(",") if a.strip()]
        expanded: list[str] = []
        for a in selected:
            if a == "unified":
                expanded.extend(unified_ids)
            else:
                expanded.append(a)
        selected = expanded
    unknown = [a for a in selected if a not in by_alias]
    if unknown:
        print(f"unknown aliases: {unknown}", flush=True)
        return 2

    print(f"selected={selected} size={args.size} unified={unified_ids}", flush=True)
    prompt = "a quiet harbor at dawn, small wooden boats, soft golden light"
    results: list[dict] = []

    from PIL import Image

    src = outdir / f"edit-source-{SMALL_EDIT_SOURCE}.png"
    if not src.exists():
        Image.new("RGB", (SMALL_EDIT_SOURCE, SMALL_EDIT_SOURCE), (60, 90, 130)).save(src)

    def record(alias: str, kind: str, status: int, body: dict, elapsed: float, out_name: str) -> None:
        row = {"alias": alias, "kind": kind, "status": status, "elapsed_s": round(elapsed, 1)}
        if status == 200 and body.get("data"):
            raw = base64.b64decode(body["data"][0]["b64_json"])
            row.update(describe(body["data"][0]["b64_json"]))
            (outdir / out_name).write_bytes(raw)
        else:
            row["error"] = body.get("error") or body
        results.append(row)
        print(f"       -> {row}", flush=True)

    for alias in selected:
        caps = by_alias[alias]["capabilities"]
        tasks = _tasks(by_alias[alias])

        if "image.generate" in tasks:
            label = "unified-generate" if caps.get("unified") else "generate"
            url = f"{base}/v1/images" if caps.get("unified") else f"{base}/v1/images/generations"
            print(f"[{label}] {alias} ...", flush=True)
            status, body, elapsed = post_json(
                url, {"model": alias, "prompt": prompt, "size": args.size, "seed": 4242},
                args.key, args.timeout,
            )
            record(alias, label, status, body, elapsed, f"{alias}-gen.png")

        if "image.edit" in tasks:
            label = "unified-edit" if caps.get("unified") else "edit"
            url = f"{base}/v1/images" if caps.get("unified") else f"{base}/v1/images/edits"
            print(f"[{label}] {alias} ...", flush=True)
            status, body, elapsed = post_edit(
                url,
                {"model": alias, "prompt": "change the background to a warm sunset sky, "
                                          "keep the foreground object unchanged", "seed": "99"},
                src, args.key, args.timeout,
            )
            record(alias, label, status, body, elapsed, f"{alias}-edit.png")

    (outdir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [r for r in results if r["status"] != 200 or (r.get("mean") or 0) < 3]
    print(f"\n{len(results) - len(failures)}/{len(results)} succeeded")
    for r in failures:
        print("FAILED:", r)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
