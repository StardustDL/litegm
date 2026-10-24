"""Create a video job with an arbitrary number of reference images (r2v test)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path


def call(url, key, method="GET", data=None, headers=None, timeout=60):
    h = {"Authorization": f"Bearer {key}"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--key", required=True)
    ap.add_argument("--model", default="minimax-h3-r2v")
    ap.add_argument("--size", default="384x256")
    ap.add_argument("--seconds", default="1")
    ap.add_argument("--ref", action="append", default=[])
    ap.add_argument("--timeout", type=float, default=900)
    args = ap.parse_args()

    boundary = "----litegmrefs"
    parts = []
    for name, value in {"prompt": "two characters meet on a quiet pier at sunrise",
                        "model": args.model, "size": args.size, "seconds": args.seconds}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for path in args.ref:
        p = Path(path)
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="reference_images"; filename="{p.name}"\r\n'
            f"Content-Type: image/png\r\n\r\n".encode() + p.read_bytes() + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())

    status, body, _ = call(f"{args.base_url}/v1/videos", args.key, method="POST",
                           data=b"".join(parts),
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    job = json.loads(body)
    print(f"create ({len(args.ref)} refs) -> {status}: {json.dumps({k: job.get(k) for k in ('id','status','model')}, ensure_ascii=False)}")
    if status != 200:
        print(json.dumps(job, ensure_ascii=False)[:500])
        return 1

    vid = job["id"]
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        st, body, _ = call(f"{args.base_url}/v1/videos/{vid}", args.key)
        obj = json.loads(body)
        print(f"poll: status={obj['status']} progress={obj['progress']}")
        if obj["status"] in ("completed", "failed"):
            break
        time.sleep(5)
    if obj["status"] != "completed":
        print("FAILED:", json.dumps(obj.get("error"), ensure_ascii=False))
        return 1
    st, data, headers = call(f"{args.base_url}/v1/videos/{vid}/content", args.key, timeout=300)
    print(f"content -> {st}, {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
