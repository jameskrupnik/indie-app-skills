#!/usr/bin/env python3
"""Static checks for work that repeats every frame in a Flutter app or game.

Scope is the whole discriminator. A `Paint()`, a shader, a `TextPainter` or a
blur is unremarkable in a `build` that runs when state changes, and a
per-frame cost in a `render(Canvas)` that runs sixty times a second. So this
finds the per-frame methods first and reports only what is inside them:

  render(Canvas) / renderTree(Canvas)   Flame components, custom games
  update(double dt)                     Flame's simulation tick
  paint(Canvas, Size)                   CustomPainter (see below)

Private helpers those methods call, in the same file, are followed two levels
down, because the blur is usually in the `_drawGlow` that `render` calls.

A CustomPainter's `paint` runs per frame only while something repaints it. One
wired to an animation (`super(repaint: ...)`) or whose `shouldRepaint` returns
`true` is treated as per-frame; any other painter's findings are reported one
level lower and tagged "repaint".

The memo idiom is recognised and not reported: `_x ??= ...`, `putIfAbsent`,
`if (_x == null) { _x = ... }`, and `if (_x != null) return _x; ... _x = ...`.

Every finding is a hypothesis. Nothing here is a crash; it is waste a profiler
shows and a test never will. Measure before and after (see SKILL.md), with the
arms alternated. Advisory: exits 0 unless --strict. Python 3.9+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

Span = Tuple[int, int]

# Signatures of methods that run per frame. `onGameResize` is deliberately
# absent: it fires on layout, not on frames.
_CANVAS = r"\(\s*(?:final\s+)?(?:ui\.)?Canvas\b"
HOT_SIGNATURES = [
    re.compile(r"\bvoid\s+render" + _CANVAS),
    re.compile(r"\bvoid\s+renderTree" + _CANVAS),
    re.compile(r"\bvoid\s+paint" + _CANVAS),
    re.compile(r"\bvoid\s+update\s*\(\s*(?:final\s+)?double\b"),
]
DRAW_SIGNATURES = HOT_SIGNATURES[:3]

PRIVATE_CALL = re.compile(r"(?<![\w.$])(_[A-Za-z]\w*)\s*\(")
FIELD_STORE = re.compile(r"(?<![\w.$])(_\w+)(?:\[[^\]]*\])?\s*=(?!=)")
LAZY_ASSIGN = re.compile(r"(?:\?\?=|\?\?)\s*\(?\s*$")
CLASS_DECL = re.compile(r"\bclass\s+(\w+)([^{;]*)\{")

SKIP_DIRS = {"build", "ios", "android", "macos", "windows", "linux", "web"}
GENERATED = (".g.dart", ".freezed.dart", ".config.dart", ".gr.dart",
             ".mocks.dart")


@dataclass
class Finding:
    check: str
    level: str  # FAIL | WARN | NOTE
    path: str
    line: int
    message: str
    scope: str = "frame"  # frame | repaint | project


def dart_files(root: Path, top: str) -> List[Path]:
    """Every non-generated .dart file under a `top` directory (lib, test...)
    anywhere in [root], so monorepos (packages/*, apps/*) work unchanged.

    Hidden directories are pruned, which keeps `.dart_tool` and an FVM SDK
    symlinked into `.fvm/` out of the scan.
    """
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS]
        rel_parts = Path(dirpath).relative_to(root).parts
        if top not in rel_parts:
            continue
        for name in filenames:
            if name.endswith(".dart") and not name.endswith(GENERATED):
                out.append(Path(dirpath) / name)
    return sorted(out)


@dataclass
class Repo:
    root: Path
    lib: List[Path] = field(default_factory=list)
    _cache: Dict[Path, str] = field(default_factory=dict)
    _hot: Dict[Path, "Hot"] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Repo":
        return cls(root=root, lib=dart_files(root, "lib"))

    def read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def stripped(self, path: Path) -> str:
        if path not in self._cache:
            self._cache[path] = strip_comments(self.read(path))
        return self._cache[path]

    def hot(self, path: Path) -> "Hot":
        if path not in self._hot:
            self._hot[path] = hot_spans(self.stripped(path))
        return self._hot[path]

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def strip_comments(text: str) -> str:
    """Blank out comments and string bodies, preserving offsets and newlines.

    A `MaskFilter` named in a comment explaining why there is no longer a
    `MaskFilter` is exactly the false positive that gets a tool ignored.
    Interpolations inside strings are blanked too, which is a known gap.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif text[i] in "'\"":
            quote = text[i]
            raw = i > 0 and text[i - 1] == "r"
            triple = text[i:i + 3] == quote * 3
            end = quote * 3 if triple else quote
            j = i + (3 if triple else 1)
            while j < n:
                if text[j] == "\\" and not raw:
                    j += 2
                    continue
                if text[j:j + len(end)] == end:
                    j += len(end)
                    break
                if not triple and text[j] == "\n":
                    break
                j += 1
            for k in range(i + 1, min(j, n) - 1):
                if out[k] != "\n":
                    out[k] = " "
            i = max(j, i + 1)
        else:
            i += 1
    return "".join(out)


def match_close(text: str, open_at: int) -> int:
    """Index just past the bracket matching the one at [open_at]."""
    pairs = {"(": ")", "{": "}", "[": "]"}
    opener = text[open_at]
    closer = pairs[opener]
    depth = 0
    for j in range(open_at, len(text)):
        if text[j] == opener:
            depth += 1
        elif text[j] == closer:
            depth -= 1
            if depth == 0:
                return j + 1
    return len(text)


def body_after_params(text: str, params_open: int) -> Optional[Span]:
    """The body of a method whose parameter list opens at [params_open].

    Returns the `{...}` block, or the expression of a `=>` body, or None for
    a bare call or declaration.
    """
    j = match_close(text, params_open)
    m = re.compile(r"\s*(?:async\*?\s*|sync\*\s*)?(\{|=>)").match(text, j)
    if not m:
        return None
    if m.group(1) == "{":
        start = m.end() - 1
        return (start, match_close(text, start))
    end = text.find(";", m.end())
    return (m.end(), len(text) if end < 0 else end + 1)


def statement_after(text: str, pos: int) -> Span:
    """The block or single statement starting at [pos]."""
    m = re.compile(r"\s*").match(text, pos)
    start = m.end()
    if start < len(text) and text[start] == "{":
        return (start, match_close(text, start))
    depth = 0
    for j in range(start, len(text)):
        c = text[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth <= 0:
            return (start, j + 1)
    return (start, len(text))


def memo_regions(text: str, span: Span) -> List[Span]:
    """Parts of [span] that run once and are then skipped: the memo idiom.

    `if (_x == null) { ... _x = ...; }` guards a build-once block, and
    `if (_x != null) return _x!;` guards the rest of the method. Both are the
    fix this tool recommends, so neither may be reported back as the fault.
    """
    a, b = span
    regions: List[Span] = []
    # `final hit = _cache[key]; if (hit != null) return hit;` guards on a
    # local that was read from a field, so map such locals to their field.
    alias = {m.group(1): m.group(2) for m in re.finditer(
        r"\b(\w+)\s*=\s*(_\w+)\s*[\[;]", text[a:b])}
    for m in re.finditer(r"\bif\s*\(", text[a:b]):
        cond_open = a + m.end() - 1
        cond_end = match_close(text, cond_open)
        cond = text[cond_open:cond_end]
        guarded = set(re.findall(
            r"(\w+)\s*(?:==|!=)|(?:==|!=)\s*(\w+)", cond))
        names = {alias.get(x, x) for pair in guarded for x in pair if x}
        names = {x for x in names if x.startswith("_")}
        if not names:
            continue
        stmt = statement_after(text, cond_end)
        stored = {s.group(1) for s in FIELD_STORE.finditer(
            text[stmt[0]:stmt[1]])}
        if names & stored:
            regions.append(stmt)
            continue
        if re.match(r"\{?\s*return\b", text[stmt[0]:stmt[1]]):
            rest = (stmt[1], b)
            later = {s.group(1) for s in FIELD_STORE.finditer(
                text[rest[0]:rest[1]])}
            if names & later:
                regions.append(rest)
    return regions


def class_spans(text: str) -> List[Tuple[str, str, Span]]:
    out = []
    for m in CLASS_DECL.finditer(text):
        start = m.end() - 1
        out.append((m.group(1), m.group(2), (start, match_close(text, start))))
    return out


def painter_repaints_per_frame(header: str, body: str) -> Optional[bool]:
    """None if not a CustomPainter; else whether it is wired to repaint
    every frame (a repaint listenable, or shouldRepaint always true)."""
    if not re.search(r"\bextends\s+CustomPainter\b", header):
        return None
    if re.search(r"super\s*\(\s*repaint\s*:|\bsuper\.repaint\b", body):
        return True
    if re.search(r"shouldRepaint\s*\([^)]*\)\s*(?:=>\s*true\s*;|"
                 r"\{\s*return\s+true\s*;\s*\})", body):
        return True
    return False


@dataclass
class Hot:
    """Per-frame spans of one file: (span, certain) plus memo regions."""
    spans: List[Tuple[Span, bool]]
    memo: List[Span]

    def at(self, pos: int) -> Optional[bool]:
        """None if [pos] is not hot; else whether it is certainly per-frame."""
        if any(a <= pos < b for a, b in self.memo):
            return None
        hits = [certain for (a, b), certain in self.spans if a <= pos < b]
        if not hits:
            return None
        return any(hits)


def hot_spans(text: str) -> Hot:
    """Every per-frame method in [text], plus the private helpers it calls."""
    classes = class_spans(text)

    def certainty_of(pos: int) -> Optional[bool]:
        inner = [c for c in classes if c[2][0] <= pos < c[2][1]]
        if not inner:
            return None
        _, header, (a, b) = min(inner, key=lambda c: c[2][1] - c[2][0])
        return painter_repaints_per_frame(header, text[a:b])

    spans: List[Tuple[Span, bool]] = []
    for pattern in HOT_SIGNATURES:
        for m in pattern.finditer(text):
            span = body_after_params(text, text.index("(", m.start()))
            if not span:
                continue
            painter = certainty_of(m.start())
            is_paint = "paint" in m.group(0) and "render" not in m.group(0)
            certain = True if not is_paint or painter is None else painter
            spans.append((span, certain))
    if not spans:
        return Hot([], [])

    memo: List[Span] = []
    for span, _ in spans:
        memo += memo_regions(text, span)

    def calls_in(span: Span) -> Set[str]:
        """Private helpers called from [span], skipping memoized call sites:
        `_cache.putIfAbsent(k, () => _build(k))` reaches `_build` once."""
        a, b = span
        found: Set[str] = set()
        for m in PRIVATE_CALL.finditer(text, a, b):
            pos = m.start()
            if any(x <= pos < y for x, y in memo):
                continue
            if LAZY_ASSIGN.search(text[max(a, pos - 40):pos]) or \
                    in_put_if_absent(text, pos):
                continue
            found.add(m.group(1))
        return found

    # Helpers called by helpers, two levels deep. That covers the
    # render -> _drawX -> _drawY chains seen in practice; unbounded recursion
    # pulls half a file in through one shared utility.
    frontier: Dict[str, bool] = {}
    for span, certain in spans:
        for name in calls_in(span):
            frontier[name] = frontier.get(name, False) or certain
    seen: Set[str] = set()
    for _ in range(3):
        nxt: Dict[str, bool] = {}
        for name, certain in frontier.items():
            if name in seen:
                continue
            seen.add(name)
            decl = re.compile(
                r"(?m)^[ \t]*(?:[\w<>?,.\[\]]+[ \t]+){0,4}"
                + re.escape(name) + r"[ \t]*(?:<[^>]*>)?[ \t]*\(")
            for d in decl.finditer(text):
                span = body_after_params(text, d.end() - 1)
                if not span:
                    continue
                own = certainty_of(d.start())
                sure = certain if own is None else (own or certain)
                spans.append((span, sure))
                memo += memo_regions(text, span)
                for callee in calls_in(span):
                    nxt[callee] = nxt.get(callee, False) or sure
        frontier = nxt
    return Hot(spans, memo)


def in_put_if_absent(text: str, pos: int) -> bool:
    """Whether [pos] sits inside the arguments of a `putIfAbsent(...)` call,
    which runs its builder once per key rather than once per frame."""
    start = text.rfind("putIfAbsent", max(0, pos - 400), pos)
    if start < 0:
        return False
    paren = text.find("(", start)
    return 0 <= paren < pos < match_close(text, paren)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


LOWER = {"FAIL": "WARN", "WARN": "NOTE", "NOTE": "NOTE"}
REPAINT_TAG = (" [in a CustomPainter not wired to an animation: per-frame "
               "only while something repaints it]")


# ---------------------------------------------------------------- the checks

def scan(repo: Repo, pattern: "re.Pattern[str]", check: str, level: str,
         message: str, *, raw: bool = False) -> List[Finding]:
    """Report [pattern] wherever it lands inside a per-frame span.

    With [raw], the pattern is matched against the original source (to see
    string literals) but must still start in live code.
    """
    out: List[Finding] = []
    for path in repo.lib:
        text = repo.stripped(path)
        hot = repo.hot(path)
        if not hot.spans:
            continue
        source = repo.read(path) if raw else text
        for m in pattern.finditer(source):
            if text[m.start()] != source[m.start()]:
                continue  # in a comment or string
            certain = hot.at(m.start())
            if certain is None:
                continue
            # `_paint ??= Paint()` or `_p ??= (Paint()..color = x)`.
            if LAZY_ASSIGN.search(text[max(0, m.start() - 40):m.start()]) \
                    or in_put_if_absent(text, m.start()):
                continue
            out.append(Finding(
                check, level if certain else LOWER[level], repo.rel(path),
                line_of(text, m.start()),
                message + ("" if certain else REPAINT_TAG),
                "frame" if certain else "repaint"))
    return out


def check_text_layout(repo: Repo) -> List[Finding]:
    """`TextPainter.layout` and `ParagraphBuilder.build` shape and line-break
    the string on the UI thread. A score popup fading over 40 frames pays 40
    times to draw four characters."""
    return scan(
        repo,
        re.compile(r"\b(?:TextPainter|ui\.ParagraphBuilder|ParagraphBuilder)"
                   r"\s*\("),
        "text-layout-per-frame", "FAIL",
        "text laid out inside a per-frame method; shaping runs on the UI "
        "thread, the thread jank comes from. Lay it out once and keep it",
    )


def check_flame_text(repo: Repo) -> List[Finding]:
    """Flame's `TextPaint.render(canvas, 'text', pos)` formats and lays out
    the string on every call. A `TextComponent` keeps its layout until the
    text changes."""
    return scan(
        repo,
        re.compile(r"\.render\s*\(\s*\w+\s*,\s*(?:['\"]|\$|\w+\.toString\(\))"),
        "text-render-per-frame", "WARN",
        "a string drawn with TextPaint.render inside a per-frame method; it "
        "is laid out on every call. Use a TextComponent or cache the layout",
        raw=True,
    )


def check_image_decode(repo: Repo) -> List[Finding]:
    """Decoding or rasterizing inside a frame stalls that frame."""
    return scan(
        repo,
        re.compile(r"\b(?:toImageSync|toImage|decodeImageFromList|"
                   r"instantiateImageCodec|loadPicture)\s*\("),
        "decode-per-frame", "FAIL",
        "an image decoded or rasterized inside a per-frame method; do it "
        "once at load and draw from the result",
    )


def check_blur(repo: Repo) -> List[Finding]:
    """A blur cannot fold into the pass it sits in: it needs its own render
    target, a downsample and two passes. A radial gradient reaching the same
    distance is one fill, but it does not fall off like a gaussian, so match
    it by eye."""
    return scan(
        repo,
        re.compile(r"\b(?:MaskFilter|ImageFilter)\.blur\s*\("),
        "blur-per-frame", "WARN",
        "a blur inside a per-frame method: an offscreen pass per object per "
        "frame. A RadialGradient reaches the same distance in one fill",
    )


def check_shader(repo: Repo) -> List[Finding]:
    """Rebuilding a Shader per frame allocates and defeats caching. Key the
    cache on the rect it was built for, or a resize stretches the old one."""
    return scan(
        repo,
        re.compile(r"\.createShader\s*\("),
        "shader-per-frame", "WARN",
        "a Shader built inside a per-frame method; cache it keyed on the "
        "rect it was built for",
    )


def check_save_layer(repo: Repo) -> List[Finding]:
    """saveLayer allocates an offscreen buffer and switches render pass."""
    return scan(
        repo,
        re.compile(r"\.saveLayer\s*\("),
        "save-layer-per-frame", "NOTE",
        "saveLayer inside a per-frame method: an offscreen buffer per call. "
        "Often avoidable by baking the alpha into the colour",
    )


def check_iterable_allocation(repo: Repo) -> List[Finding]:
    """`.toList()` in a per-frame sweep: sixty throwaway lists a second,
    usually finding nothing."""
    return scan(
        repo,
        re.compile(r"\.(?:toList|toSet)\s*\(\s*\)"),
        "allocation-per-frame", "NOTE",
        "a collection copied inside a per-frame method; reuse a scratch "
        "list, or iterate something already const",
    )


def check_paint_allocation(repo: Repo) -> List[Finding]:
    """The cheapest thing on this list and the most numerous. Worth hoisting
    when the Paint is constant; not worth contorting code when it varies."""
    return scan(
        repo,
        re.compile(r"\bPaint\s*\(\s*\)"),
        "paint-per-frame", "NOTE",
        "a Paint allocated inside a per-frame method; hoist it to a field "
        "when its colour does not change",
    )


def check_render_coverage(repo: Repo) -> List[Finding]:
    """A suite that drives `update` and never calls `render`.

    A shader built from an empty rect or a gradient whose stops do not ascend
    is not a compile error. Only files that actually draw count: a model with
    an `update(double dt)` tick has no render-time faults to miss.
    """
    drawing = [p for p in repo.lib
               if any(d.search(repo.stripped(p)) for d in DRAW_SIGNATURES)]
    if not drawing:
        return []
    tests = dart_files(repo.root, "test") + dart_files(
        repo.root, "integration_test")
    probe = re.compile(r"\.render\s*\(|renderTree\s*\(|\.paint\s*\(\s*\w+\s*,"
                       r"|toImage(?:Sync)?\s*\(|matchesGoldenFile")
    if any(probe.search(repo.read(p)) for p in tests):
        return []
    return [Finding(
        "render-untested", "WARN", repo.rel(drawing[0]), 1,
        f"{len(drawing)} file(s) draw on a canvas and no test renders one "
        "(render/paint/toImage/golden): render-time faults cannot fail this "
        "suite", "project",
    )]


def check_probe(repo: Repo) -> List[Finding]:
    """No harness means every future claim about frame cost is a guess."""
    name = re.compile(r"perf|bench|frame|probe|jank", re.I)
    for top in ("tool", "test", "integration_test", "benchmark"):
        if any(name.search(p.name) for p in dart_files(repo.root, top)):
            return []
    if not any(repo.hot(p).spans for p in repo.lib):
        return []
    return [Finding(
        "no-probe", "NOTE", "tool/", 1,
        "no frame-cost harness found (a *perf*/*bench*/*frame*/*probe* file "
        "in tool/, test/ or integration_test/); copy frame_probe.dart",
        "project",
    )]


CHECKS = [
    ("text-layout-per-frame", check_text_layout),
    ("decode-per-frame", check_image_decode),
    ("text-render-per-frame", check_flame_text),
    ("blur-per-frame", check_blur),
    ("shader-per-frame", check_shader),
    ("save-layer-per-frame", check_save_layer),
    ("allocation-per-frame", check_iterable_allocation),
    ("paint-per-frame", check_paint_allocation),
    ("render-untested", check_render_coverage),
    ("no-probe", check_probe),
]

COLOUR = {"FAIL": "\033[31m", "WARN": "\033[33m", "NOTE": "\033[2m"}
GREEN, DIM, OFF = "\033[32m", "\033[2m", "\033[0m"
RANK = {"FAIL": 0, "WARN": 1, "NOTE": 2}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="checks: " + ", ".join(n for n, _ in CHECKS))
    ap.add_argument("--app", default=".",
                    help="Flutter project or monorepo root (default: .)")
    ap.add_argument("--json", action="store_true",
                    help="print findings as a JSON array")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if anything is reported (after --quiet)")
    ap.add_argument("--quiet", action="store_true",
                    help="hide NOTE-level findings")
    args = ap.parse_args()

    root = Path(args.app).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    repo = Repo.load(root)
    if not repo.lib:
        print(f"no Dart sources under a lib/ directory in {root}",
              file=sys.stderr)

    findings: List[Finding] = []
    for _, fn in CHECKS:
        findings += fn(repo)
    if args.quiet:
        findings = [f for f in findings if f.level != "NOTE"]
    code = 1 if (args.strict and findings) else 0

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
        return code

    tty = sys.stdout.isatty()

    def c(colour: str, s: str) -> str:
        return f"{colour}{s}{OFF}" if tty else s

    hot = sum(1 for p in repo.lib if repo.hot(p).spans)
    print(f"Frame cost: {root.name}")
    print(f"  {len(repo.lib)} source file(s), {hot} with per-frame methods\n")

    if not findings:
        print(f"  {c(GREEN, 'OK')}  nothing repeating per frame that a "
              "static check can see.")
        return code

    groups: Dict[Tuple[str, str], List[Finding]] = {}
    for f in findings:
        groups.setdefault((f.check, f.level), []).append(f)
    order = [n for n, _ in CHECKS]
    for (check, level) in sorted(
            groups, key=lambda k: (RANK[k[1]], order.index(k[0]))):
        group = groups[(check, level)]
        files = len({f.path for f in group})
        print(f"  {c(COLOUR[level], level)}  {check}  ({len(group)})")
        for f in group[:6]:
            print(f"        {c(DIM, f'{f.path}:{f.line}')}")
        if len(group) > 6:
            print(c(DIM, f"        ... and {len(group) - 6} more, "
                         f"{files} file(s) in all"))
        print(f"        {group[0].message}\n")
    print(c(DIM, "Each of these is a hypothesis. Measure it, paired, before "
                 "and after: see SKILL.md."))
    return code


if __name__ == "__main__":
    sys.exit(main())
