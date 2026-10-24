"""Check that relative Markdown links in the docs resolve to existing files.

Usage:
    python scripts/check_doc_links.py README.md AGENTS.md docs/**/*.md

Reports broken links; exits non-zero when any are found. External links and
pure ``#anchor`` links are ignored.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#")


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read ({exc})"]
    for target in LINK_RE.findall(text):
        if target.startswith(SKIP_PREFIX):
            continue
        anchorless = target.split("#", 1)[0]
        if not anchorless:
            continue
        resolved = (path.parent / anchorless).resolve()
        if not resolved.exists():
            problems.append(f"{path}: broken link -> {target}")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_doc_links.py <markdown files or directories>")
        return 2
    files: list[Path] = []
    for name in argv:
        p = Path(name)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
        else:
            files.append(p)
    problems: list[str] = []
    for f in files:
        problems.extend(check(f))
    for line in problems:
        print(line)
    print(f"checked {len(files)} file(s), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
