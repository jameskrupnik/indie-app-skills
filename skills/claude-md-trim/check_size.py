#!/usr/bin/env python3
"""Measure Claude Code instruction files against the size warning, and check links.

With no paths, measures the project instruction files in the current directory:
CLAUDE.md, .claude/CLAUDE.md and CLAUDE.local.md (or AGENTS.md if there is no
CLAUDE.md), plus every file they @-import and every .claude/rules/*.md file that
loads at launch.

Sizes are counted the way Claude Code has been observed to count them: string
length in UTF-16 code units, after YAML frontmatter and block-level HTML comments
are stripped. That is close to, but not the same as, `wc -c` (bytes).

Exit code is 1 if any file is over --limit, the launch set is over
--total-limit, or (with --links) any link is broken, so this can gate a commit.
Standard library only; Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
HTML_COMMENT_BLOCK = re.compile(r"^[ \t]*<!--.*?-->[ \t]*\n?", re.S | re.M)
IMPORT = re.compile(r"(?<![\w`])@((?:\\ |[^\s`])+)")
LINK = re.compile(r"(?<!!)\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'(][^)]*)?\)")
HTML_ID = re.compile(r"""<[a-z]+[^>]*\s(?:id|name)\s*=\s*["']([^"']+)["']""", re.I)
MAX_IMPORT_DEPTH = 4


# ---------------------------------------------------------------- reading


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n") or text.startswith("---\r\n"):
        end = re.search(r"^---[ \t]*$", text[3:], re.M)
        if end:
            return text[3 + end.end():].lstrip("\r\n")
    return text


def loaded_text(text: str) -> str:
    """The text Claude Code is observed to measure: no frontmatter, no block comments."""
    return HTML_COMMENT_BLOCK.sub("", strip_frontmatter(text))


def prose_lines(text: str):
    """Yield (line, in_fence) for every line, tracking ``` and ~~~ fences properly."""
    fence = None
    for line in text.splitlines(keepends=True):
        m = FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)
            yield line, True
        elif fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and not line.strip()[len(m.group(1)):].strip():
                fence = None
            yield line, True
        else:
            yield line, False


def without_code_spans(line: str) -> str:
    return CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)


# ---------------------------------------------------------------- headings


def slug(heading: str) -> str:
    """GitHub's anchor slug (github-slugger) for the rendered heading text."""
    parts = re.split(r"(`+[^`]*`+)", heading)
    out = []
    for i, part in enumerate(parts):
        if i % 2:  # code span: keep the literal text
            out.append(part.strip("`"))
            continue
        part = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", part)  # links -> text
        part = re.sub(r"<[^>]+>", "", part)                       # inline html
        part = re.sub(r"(?<!\w)_+|_+(?!\w)", "", part)            # _emphasis_
        out.append(part)
    text = "".join(out).lower()
    kept = "".join(
        c for c in text
        if c in " -" or unicodedata.category(c)[0] in "LMN" or unicodedata.category(c) == "Pc"
    )
    return kept.replace(" ", "-")


def headings(text: str) -> list[tuple[int, int, str]]:
    """(line index, level, text) for ATX and setext headings outside code fences."""
    out, prev = [], None
    lines = list(prose_lines(text))
    for i, (line, in_fence) in enumerate(lines):
        raw = line.rstrip("\r\n")
        if in_fence:
            prev = None
            continue
        m = ATX.match(raw)
        if m:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", m.group(2) or "").strip()
            if title == "#" * len(title):
                title = ""
            out.append((i, len(m.group(1)), title))
            prev = None
            continue
        s = SETEXT.match(raw)
        if s and prev is not None:
            out.append((i - 1, 1 if s.group(1)[0] == "=" else 2, prev.strip()))
            prev = None
            continue
        is_para = raw.strip() and not re.match(r"^ {0,3}([-*+>|]|\d+[.)]|<)", raw)
        prev = raw if is_para else None
    return out


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    found = set()
    for _, _, title in headings(text):
        base = slug(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    found.update(a.lower() for a in HTML_ID.findall(text))
    return found


def breakdown(text: str) -> list[dict]:
    lines = text.splitlines(keepends=True)
    marks = {i: (lvl, t) for i, lvl, t in headings(text)}
    sections, name, count = [], "(before the first heading)", 0
    for i, line in enumerate(lines):
        if i in marks:
            if count:
                sections.append({"heading": name, "chars": count})
            lvl, t = marks[i]
            name, count = f"{'#' * lvl} {t}", 0
        count += utf16_len(line)
    if count:
        sections.append({"heading": name, "chars": count})
    return sorted(sections, key=lambda s: -s["chars"])


# ---------------------------------------------------------------- imports


def imports(path: Path, text: str) -> list[Path]:
    found = []
    for line, in_fence in prose_lines(text):
        if in_fence:
            continue
        for m in IMPORT.finditer(without_code_spans(line)):
            raw = m.group(1).replace("\\ ", " ")
            for candidate in (raw, raw.rstrip(".,;:!?)]}'\"")):
                p = Path(candidate).expanduser()
                p = p if p.is_absolute() else path.parent / p
                if p.is_file():
                    found.append(p.resolve())
                    break
    return found


def launch_set(roots: list[Path]) -> list[dict]:
    """Every root plus its @-imports (up to four hops), each file once."""
    out, seen = [], set()

    def visit(p: Path, depth: int, via: str | None) -> None:
        key = p.resolve()
        if key in seen:
            return
        seen.add(key)
        text = p.read_text(encoding="utf-8", errors="replace")
        out.append({"path": p, "via": via, "text": text})
        if depth < MAX_IMPORT_DEPTH:
            for child in imports(p, text):
                visit(child, depth + 1, str(p))

    for root in roots:
        visit(root, 0, None)
    return out


def default_roots(cwd: Path) -> list[Path]:
    roots = [p for p in (cwd / "CLAUDE.md", cwd / ".claude" / "CLAUDE.md", cwd / "CLAUDE.local.md")
             if p.is_file()]
    if not roots:
        roots = [p for p in (cwd / "AGENTS.md", cwd / ".claude" / "AGENTS.md") if p.is_file()]
    rules = cwd / ".claude" / "rules"
    if rules.is_dir():
        for p in sorted(rules.rglob("*.md")):
            head = p.read_text(encoding="utf-8", errors="replace")
            fm = head[: len(head) - len(strip_frontmatter(head))]
            if not re.search(r"^paths\s*:", fm, re.M):  # path-scoped rules load on demand
                roots.append(p)
    return roots


# ---------------------------------------------------------------- links


def links(text: str) -> list[str]:
    found = []
    for line, in_fence in prose_lines(text):
        if not in_fence:
            found.extend(LINK.findall(without_code_spans(line)))
    return found


def check_links(path: Path, text: str, cache: dict) -> list[str]:
    broken = []
    for target in links(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
            continue  # http:, mailto:, etc.
        file_part, _, anchor = target.partition("#")
        dest = (path.parent / unquote(file_part)).resolve() if file_part else path.resolve()
        if file_part and not dest.exists():
            broken.append(f"{shown(path)}: {target}  (no such file)")
            continue
        if anchor and dest.is_file() and dest.suffix.lower() in (".md", ".markdown"):
            if dest not in cache:
                cache[dest] = anchors(dest.read_text(encoding="utf-8", errors="replace"))
            if unquote(anchor).lower() not in cache[dest]:
                broken.append(f"{shown(path)}: {target}  (no such heading)")
    return broken


def linked_markdown(path: Path, text: str) -> list[Path]:
    out = []
    for target in links(text):
        file_part = target.partition("#")[0]
        if file_part and not re.match(r"^[a-z][a-z0-9+.-]*:", file_part, re.I):
            p = (path.parent / unquote(file_part)).resolve()
            if p.is_file() and p.suffix.lower() in (".md", ".markdown"):
                out.append(p)
    return out


# ---------------------------------------------------------------- main


def shown(p) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure CLAUDE.md / AGENTS.md against Claude Code's size warning "
                    "and check that every link still resolves.")
    ap.add_argument("paths", nargs="*", type=Path,
                    help="files to measure (default: the project's instruction files in .)")
    ap.add_argument("--limit", type=int, default=150_000,
                    help="per-file limit in characters; use the number in your warning "
                         "(default 150000; older or smaller-context setups warn at 40000)")
    ap.add_argument("--total-limit", type=int, default=None,
                    help="limit for all launch-loaded files together "
                         "(default: the larger of 120000 and --limit)")
    ap.add_argument("--headroom", type=float, default=10.0,
                    help="percent below the limit to aim for (default 10)")
    ap.add_argument("--links", action="store_true",
                    help="also check every relative link and #anchor, in the measured files "
                         "and in the markdown files they link to")
    ap.add_argument("--top", type=int, default=15, help="sections to list per file (default 15)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    total_limit = args.total_limit or max(120_000, args.limit)
    target = int(args.limit * (1 - args.headroom / 100))
    roots = args.paths or default_roots(Path.cwd())
    missing = [p for p in roots if not p.is_file()]
    if missing or not roots:
        print(f"no such file: {', '.join(map(str, missing)) or 'CLAUDE.md or AGENTS.md in .'}",
              file=sys.stderr)
        return 2

    files = launch_set(roots)
    report, total = [], 0
    for f in files:
        body = loaded_text(f["text"])
        size = utf16_len(body)
        total += size if size <= args.limit else 0  # oversized files are warned about alone
        report.append({
            "path": shown(f["path"]), "imported_by": f["via"] and shown(f["via"]), "chars": size,
            "bytes": len(f["text"].encode("utf-8")), "over": size > args.limit,
            "sections": breakdown(body)[: args.top],
        })

    broken: list[str] = []
    if args.links:
        cache: dict = {}
        checked, queue = set(), [(Path(f["path"]).resolve(), 0) for f in files]
        while queue:
            p, depth = queue.pop(0)
            if p in checked:
                continue
            checked.add(p)
            text = p.read_text(encoding="utf-8", errors="replace")
            broken += check_links(p, text, cache)
            if depth == 0:  # one level out: the docs the stubs point at
                queue += [(d, 1) for d in linked_markdown(p, text)]

    failed = any(r["over"] for r in report) or total > total_limit or bool(broken)
    if args.json:
        print(json.dumps({
            "limit": args.limit, "total_limit": total_limit, "target": target,
            "total_chars": total, "files": report,
            "links_checked": args.links, "broken_links": broken, "ok": not failed,
        }, indent=2))
        return 1 if failed else 0

    for r in report:
        via = f"  (imported by {r['imported_by']})" if r["imported_by"] else ""
        print(f"{r['path']}: {r['chars']:,} chars{via}")
        if r["over"]:
            print(f"  OVER the {args.limit:,} limit by {r['chars'] - args.limit:,}")
        if r["chars"] > target:
            print(f"  move at least {r['chars'] - target:,} chars to reach the {target:,} target")
        elif not r["imported_by"]:
            print(f"  {args.limit - r['chars']:,} under the limit (target {target:,})")
        if r["chars"] > target or len(report) == 1:
            print("  biggest sections:")
            for s in r["sections"]:
                print(f"    {s['chars']:8,}  {s['heading']}")
        print()

    if len(report) > 1:
        state = "OVER" if total > total_limit else "under"
        print(f"all launch-loaded files: {total:,} chars, {state} the {total_limit:,} total limit")
    if args.links:
        print(f"links: {'BROKEN' if broken else 'all resolve'}")
        for line in broken:
            print(f"  {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
