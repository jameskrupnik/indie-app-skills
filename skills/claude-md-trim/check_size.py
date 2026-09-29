#!/usr/bin/env python3
"""Measure a CLAUDE.md against the 150k-character limit, and check its links.

    check_size.py [path]            size, headroom, per-heading breakdown
    check_size.py [path] --links    the above, plus every link that no longer resolves

Exit code is 1 if the file is over the limit or any link is broken, so this can
gate a commit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LIMIT = 150_000
TARGET = 135_000  # 10% headroom: these files grow every build

HEADING = re.compile(r"^(#{2,4})\s+(.*)$")
INTERNAL = re.compile(r"\]\(#([^)]+)\)")
CROSSFILE = re.compile(r"\]\((docs/[^)#]+\.md)(?:#([^)]+))?\)")
FENCE = re.compile(r"^\s*```")


def slug(text: str) -> str:
    """GitHub's anchor slug: lowercase, drop punctuation but keep _ and -."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 _-]", "", text)
    return text.strip().replace(" ", "-")


def headings(path: Path) -> list[str]:
    out, in_fence = [], False
    for line in path.read_text().splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if m:
            out.append(m.group(2))
    return out


def breakdown(path: Path) -> list[tuple[int, str]]:
    sizes, current, count, in_fence = [], None, 0, False
    for line in path.read_text().splitlines(keepends=True):
        if FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else HEADING.match(line.rstrip("\n"))
        if m:
            if current is not None:
                sizes.append((count, current))
            current, count = f"{m.group(1)} {m.group(2)}", 0
        count += len(line)
    if current is not None:
        sizes.append((count, current))
    return sorted(sizes, reverse=True)


def check_links(path: Path) -> list[str]:
    text = path.read_text()
    broken = []

    own = {slug(h) for h in headings(path)}
    for anchor in INTERNAL.findall(text):
        if anchor not in own:
            broken.append(f"  #{anchor}  (no such heading in {path.name})")

    for target, anchor in CROSSFILE.findall(text):
        dest = path.parent / target
        if not dest.exists():
            broken.append(f"  {target}  (file does not exist)")
            continue
        if anchor and anchor not in {slug(h) for h in headings(dest)}:
            broken.append(f"  {target}#{anchor}  (no such heading)")

    return broken


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else Path("CLAUDE.md")
    if not path.exists():
        print(f"no such file: {path}")
        return 1

    size = len(path.read_text())
    over = size - LIMIT
    print(f"{path}: {size:,} chars")
    if over > 0:
        print(f"  OVER the {LIMIT:,} limit by {over:,} — it is being truncated")
        print(f"  move at least {size - TARGET:,} chars to reach the {TARGET:,} target")
    else:
        print(f"  under the limit, {-over:,} to spare (target {TARGET:,})")

    print("\nbiggest sections:")
    for count, heading in breakdown(path)[:15]:
        print(f"  {count:7,}  {heading}")

    failed = over > 0
    if "--links" in sys.argv:
        broken = check_links(path)
        print(f"\nlinks: {'BROKEN' if broken else 'all resolve'}")
        for line in broken:
            print(line)
        failed = failed or bool(broken)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
