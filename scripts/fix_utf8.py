"""Repair UTF-8 files whose multi-byte characters were truncated.

When a writer (e.g. a Windows console using a non-UTF-8 code page) emits only
part of a CJK character, the trailing bytes are lost and the file becomes
invalid UTF-8. Every such character here is exactly three bytes in UTF-8
(``1110xxxx 10xxxxxx 10xxxxxx``); a two-byte prefix followed by ASCII means the
third byte was dropped.

This tool reports what it finds; with ``--write`` it re-encodes a best-effort
repair: each truncated sequence is completed by guessing the missing
continuation bytes from the most likely characters. Because guessing is lossy,
it also prints every repair so a human can verify the text.

Usage:
    python scripts/fix_utf8.py web/src/TaskList.tsx [--write]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Characters that commonly appear in this UI's copy; used to pick the most
# plausible completion for a truncated three-byte character.
CANDIDATES = (
    "部成中行队交败消超时完生排提已取态类图文视频音图频"
    "全筛选中已重试删导查页记条近过天小时分秒"
    "无有加载错误数据任务模型提示词"
    "确认取消关闭打开查看详情复制下载"
    "个张次共总上限设置"
)


def scan(data: bytes) -> list[tuple[int, bytes]]:
    """Return ``(offset, prefix)`` for each truncated three-byte sequence."""
    out: list[tuple[int, bytes]] = []
    i = 0
    while i < len(data):
        b = data[i]
        if b < 0x80:
            i += 1
            continue
        if 0xC0 <= b < 0xE0:
            need, n = 2, 1
        elif 0xE0 <= b < 0xF0:
            need, n = 3, 2
        elif 0xF0 <= b < 0xF8:
            need, n = 4, 3
        else:
            raise ValueError(f"invalid lead byte 0x{b:02x} at {i}")
        prefix = data[i : i + n]
        have = sum(1 for x in prefix[1:] if 0x80 <= x < 0xC0)
        if have < need - 1:
            out.append((i, prefix))
            i += 1 + have
        else:
            i += need
    return out


def repair(text: str) -> tuple[str, list[str]]:
    """Return repaired text and a log of each replacement (guessed char)."""
    data = text.encode("utf-8", errors="surrogateescape")
    log: list[str] = []
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b < 0x80:
            out.append(b)
            i += 1
            continue
        if 0xC0 <= b < 0xE0:
            need = 2
        elif 0xE0 <= b < 0xF0:
            need = 3
        elif 0xF0 <= b < 0xF8:
            need = 4
        else:
            raise ValueError(f"invalid lead byte 0x{b:02x} at {i}")
        chunk = data[i : i + need]
        have = sum(1 for x in chunk[1:] if 0x80 <= x < 0xC0)
        if have == need - 1:
            out += chunk
            i += need
            continue
        # Truncated: try every candidate completion and keep the first that
        # decodes; otherwise fall back to U+FFFD.
        prefix = bytes(chunk[: 1 + have])
        chosen = None
        for cand in CANDIDATES:
            cb = cand.encode("utf-8")
            if len(cb) == need and cb[: 1 + have] == prefix:
                chosen = cand
                break
        if chosen is None:
            out += "�".encode("utf-8")
            log.append(f"offset {i}: {prefix.hex()} -> U+FFFD")
        else:
            out += chosen.encode("utf-8")
            log.append(f"offset {i}: {prefix.hex()} -> {chosen}")
        i += 1 + have
    return out.decode("utf-8"), log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    bad_total = 0
    for name in args.files:
        path = Path(name)
        data = path.read_bytes()
        try:
            data.decode("utf-8")
            print(f"OK   {path}")
            continue
        except UnicodeDecodeError as exc:
            print(f"BAD  {path}: {exc}")
        bad_total += 1
        if not args.write:
            continue
        text = data.decode("utf-8", errors="surrogateescape")
        fixed, log = repair(text)
        path.write_text(fixed, encoding="utf-8", newline="\n")
        print(f"  repaired {len(log)} sequences")
        for line in log:
            print("   ", line)
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
