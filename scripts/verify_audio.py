"""Smoke-test the audio API with a short clip.

Per project rules, tests stay small: default 10 seconds of music (not a full song).

Usage:
    python scripts/verify_audio.py --key <master key> [--seconds 10]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def _call(url: str, key: str, method: str = "GET", data: bytes | None = None,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--key", required=True)
    ap.add_argument("--model", default="minimax-music3")
    ap.add_argument("--seconds", default="10")
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--outdir", default=".cache/audio-verify")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    payload = {
        "model": args.model,
        "input": "Global Metadata: calm acoustic folk, 90 BPM, A minor, warm and intimate. "
                 "Vocal Details: soft female vocals, gentle breathy delivery. "
                 "Arrangement: fingerpicked guitar intro, light percussion, strings in the chorus.",
        "lyrics": "[Intro]\n[Verse] Morning light on quiet water\n[Chorus] Let it drift away",
        "seconds": float(args.seconds),
    }
    status, body, _ = _call(f"{base}/v1/audio/generations", args.key, method="POST",
                            data=json.dumps(payload).encode(),
                            headers={"Content-Type": "application/json"})
    job = json.loads(body)
    print(f"create -> {status}: {json.dumps({k: job.get(k) for k in ('id','status','seconds','model')}, ensure_ascii=False)}", flush=True)
    if status != 200:
        print(json.dumps(job, ensure_ascii=False)[:500])
        return 1

    jid = job["id"]
    deadline = time.time() + args.timeout
    obj = job
    while time.time() < deadline:
        st, body, _ = _call(f"{base}/v1/audio/{jid}", args.key)
        obj = json.loads(body)
        print(f"poll: status={obj['status']} progress={obj['progress']}", flush=True)
        if obj["status"] in ("completed", "failed"):
            break
        time.sleep(5)
    if obj["status"] != "completed":
        print("FAILED:", json.dumps(obj, ensure_ascii=False)[:600])
        return 1

    st, data, headers = _call(f"{base}/v1/audio/{jid}/content", args.key, timeout=300)
    out = outdir / f"{jid}.flac"
    out.write_bytes(data)
    print(f"content -> {st}, {len(data)} bytes, type={headers.get('content-type')}, saved {out}")
    return 0 if st == 200 and data else 1


if __name__ == "__main__":
    raise SystemExit(main())
