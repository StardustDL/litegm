"""Smoke-test the video API with a deliberately tiny clip.

Per project rules, test videos must use low resolution and under 2 seconds so the
GPU is not tied up. Defaults: 384x256, 1 second.

Usage:
    python scripts/verify_video.py --key <master key> [--model minimax-h3-t2v]
                                   [--size 384x256] [--seconds 1]
                                   [--reference path/to.png]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def _request(url: str, key: str, method: str = "GET", data: bytes | None = None,
             headers: dict | None = None, timeout: float = 60):
    h = {"Authorization": f"Bearer {key}"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def create(base: str, key: str, fields: dict, files: dict[str, tuple[str, bytes]]) -> tuple[int, dict]:
    boundary = "----litegmvideo"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, content) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n".encode() + content + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    status, body, _ = _request(
        f"{base}/v1/videos", key, method="POST", data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return status, json.loads(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--key", required=True)
    ap.add_argument("--model", default="minimax-h3-t2v")
    ap.add_argument("--size", default="384x256")
    ap.add_argument("--seconds", default="1")
    ap.add_argument("--reference", default=None, help="PNG for i2v/r2v")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--outdir", default=".cache/video-verify")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    files: dict[str, tuple[str, bytes]] = {}
    if args.reference:
        ref = Path(args.reference)
        field = "input_reference"
        if "r2v" in args.model:
            field = "reference_images"
        files[field] = (ref.name, ref.read_bytes())

    fields = {"prompt": "a slow camera push across a calm harbor at sunrise",
              "model": args.model, "size": args.size, "seconds": args.seconds}
    status, job = create(base, args.key, fields, files)
    print(f"create -> {status}: {json.dumps({k: job.get(k) for k in ('id','status','seconds','size','model')}, ensure_ascii=False)}", flush=True)
    if status != 200:
        print(json.dumps(job, ensure_ascii=False))
        return 1

    vid = job["id"]
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        st, body, _ = _request(f"{base}/v1/videos/{vid}", args.key)
        obj = json.loads(body)
        print(f"poll: status={obj['status']} progress={obj['progress']}", flush=True)
        if obj["status"] in ("completed", "failed"):
            break
        time.sleep(5)
    if obj["status"] != "completed":
        print("FAILED:", json.dumps(obj, ensure_ascii=False)[:600])
        return 1

    st, data, headers = _request(f"{base}/v1/videos/{vid}/content", args.key, timeout=300)
    print(f"content -> {st}, {len(data)} bytes, type={headers.get('content-type')}")
    out = outdir / f"{vid}.mp4"
    out.write_bytes(data)
    print("saved", out)
    return 0 if st == 200 and len(data) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
