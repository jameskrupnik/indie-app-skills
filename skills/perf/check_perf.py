#!/usr/bin/env python3
"""Static checks for work that repeats every frame.

**Scope is the whole discriminator.** A `Paint()`, a shader, a `TextPainter`
or a blur is unremarkable in a `build` that runs when state changes, and is a
per-frame cost in a `render(Canvas)` that runs sixty times a second. So every
check here finds the hot methods first and only reports what is inside them.

Each check fired for real on a shipping app whose analyze was clean, whose
suite was green, and which was not dropping frames — which is the point.
Nothing here is a crash; it is all waste that a profiler shows and a test
never will.

Advisory by design. Exits 0 unless --strict. Confirm anything it reports by
measuring — see SKILL.md, and do not skip the part about alternating the arms.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Signatures of methods that run per frame.
#
# `render`/`paint` take a Canvas: Flame components, CustomPainters, and
# RenderObjects all land here. Flame's `update(double dt)` is the simulation
# tick. `onGameResize` is deliberately absent — it fires on layout, not on
# frames, and treating it as hot produced nothing but noise.
HOT_SIGNATURES = [
    re.compile(r"\bvoid\s+render\s*\(\s*(?:ui\.)?Canvas\b"),
    re.compile(r"\bvoid\s+paint\s*\(\s*(?:ui\.)?Canvas\b"),
    re.compile(r"\bvoid\s+update\s*\(\s*(?:final\s+)?double\b"),
    re.compile(r"\bvoid\s+renderTree\s*\(\s*(?:ui\.)?Canvas\b"),
]

# Anything called from a hot method is hot too. One level of indirection is
# where most of this actually hides: `render` calls `_drawGlow`, and the blur
# is in `_drawGlow`.
PRIVATE_CALL = re.compile(r"\b(_[A-Za-z]\w*)\s*\(")

# The memo idiom, which is what the fix for every check here looks like.
#
# **Without this the tool reports its own advice back as a fault.** A cached
# shader still calls `createShader` and a cached paragraph still calls
# `ParagraphBuilder` — the difference is that the call is reached once and its
# result is kept, and both of those are visible in the source. A method that
# null-checks a field and assigns a field is a memo; a call preceded by `??=`
# or `putIfAbsent` is a memo. Neither is per-frame work.
FIELD_STORE = re.compile(r"(?<![\w.])(_\w+)(?:\[[^\]]*\])?\s*=(?!=)")
MEMO_CALL = re.compile(r"(?:\?\?=|\?\?|putIfAbsent\s*\(|=>)\s*$")
LAZY_ASSIGN = re.compile(r"\?\?=\s*$")


def is_memo(body: str) -> bool:
    """Whether [body] stores its result in a field behind an early return.

    That shape — check, return the cached value, otherwise build and store — is
    what every fix in this file looks like. A method matching it runs its
    expensive part once, however hot the thing calling it is.
    """
    store = FIELD_STORE.search(body)
    if not store:
        return False
    return "return" in body[:store.start()]


@dataclass
class Finding:
    check: str
    level: str  # FAIL | WARN | NOTE
    path: str
    line: int
    message: str


@dataclass
class Repo:
    root: Path
    lib: list[Path] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> "Repo":
        out: list[Path] = []
        for g in ("lib/**/*.dart", "packages/*/lib/**/*.dart"):
            out += [
                p
                for p in root.glob(g)
                if "/build/" not in str(p)
                and ".dart_tool" not in str(p)
                and not p.name.endswith(".g.dart")
                and not p.name.endswith(".freezed.dart")
                and not p.name.endswith(".config.dart")
            ]
        return cls(root=root, lib=sorted(set(out)))

    def read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def strip_comments(text: str) -> str:
    """Blank out comments and string bodies, preserving offsets and newlines.

    Every check below matches on source text, and a `MaskFilter` named in a doc
    comment explaining why there is no longer a `MaskFilter` is exactly the
    kind of false positive that gets a tool ignored.
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
            triple = text[i:i + 3] == quote * 3
            end = quote * 3 if triple else quote
            j = i + (3 if triple else 1)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j:j + len(end)] == end:
                    j += len(end)
                    break
                j += 1
            for k in range(i, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def body_after(text: str, start: int) -> tuple[int, int] | None:
    """Span of the `{...}` block that follows [start]. None for `=>` bodies."""
    brace = text.find("{", start)
    arrow = text.find("=>", start)
    semi = text.find(";", start)
    if brace < 0:
        return None
    if 0 <= arrow < brace or 0 <= semi < brace:
        # An expression body or a declaration; take the rest of the statement.
        end = semi if semi >= 0 else len(text)
        return (start, end)
    depth, j = 0, brace
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return (brace, j + 1)
        j += 1
    return (brace, len(text))


def hot_spans(text: str) -> list[tuple[int, int]]:
    """Byte spans of every per-frame method, plus the private helpers they call.

    Two passes, because the blur is usually not in `render` itself — it is in
    the `_drawGlow` that `render` calls, and a one-pass scan misses every one
    of those.
    """
    spans: list[tuple[int, int]] = []
    for pattern in HOT_SIGNATURES:
        for m in pattern.finditer(text):
            span = body_after(text, m.end())
            if span:
                spans.append(span)
    if not spans:
        return []

    spans = [s for s in spans if not is_memo(text[s[0]:s[1]])]
    if not spans:
        return []

    def calls_in(a: int, b: int) -> set[str]:
        """Private helpers called from [a, b), skipping memoized call sites.

        `_paragraphs.putIfAbsent(step, () => _build(alpha))` reaches `_build`
        at most once per distinct step, so `_build` is not per-frame work
        however expensive it is.
        """
        found: set[str] = set()
        for m in PRIVATE_CALL.finditer(text[a:b]):
            before = text[a:b][max(0, m.start() - 60):m.start()]
            if MEMO_CALL.search(before.rstrip()[-24:] if before else ""):
                continue
            found.add(m.group(1))
        return found

    called: set[str] = set()
    for a, b in spans:
        called |= calls_in(a, b)

    # Helpers called by helpers, to a fixed depth. Two rounds covers the
    # render -> _drawX -> _drawY chains seen in practice; unbounded recursion
    # here would pull in half the file through a shared utility.
    for _ in range(2):
        added: set[str] = set()
        for name in list(called):
            for m in re.finditer(
                r"\b(?:void|double|int|bool|Offset|Rect|Paint|Path|Color)?\s*"
                + re.escape(name) + r"\s*\([^;{]*\)\s*(?:async\s*)?\{",
                text,
            ):
                span = body_after(text, m.end() - 1)
                if span and span not in spans:
                    if is_memo(text[span[0]:span[1]]):
                        continue
                    spans.append(span)
                    added |= calls_in(*span)
        if not added:
            break
        called |= added
    return spans


def in_any(spans: list[tuple[int, int]], pos: int) -> bool:
    return any(a <= pos < b for a, b in spans)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------- the checks

def scan(repo: Repo, pattern: re.Pattern, check: str, level: str,
         message: str, *, skip_if: str | None = None) -> list[Finding]:
    out: list[Finding] = []
    for path in repo.lib:
        raw = repo.read(path)
        if not raw:
            continue
        text = strip_comments(raw)
        spans = hot_spans(text)
        if not spans:
            continue
        for m in pattern.finditer(text):
            if not in_any(spans, m.start()):
                continue
            # `_cloudPaint ??= Paint()` builds it once. The assignment is the
            # cache, and it is right there in front of the thing it caches.
            before = text[max(0, m.start() - 40):m.start()].rstrip()
            # `_groundPaint ??= (Paint()..color = x)` — the paren is noise
            # between the cache and the thing being cached.
            before = before.rstrip("( \t\n")
            if LAZY_ASSIGN.search(before) or MEMO_CALL.search(before[-24:]):
                continue
            if skip_if and skip_if in text[max(0, m.start() - 80):m.start()]:
                continue
            out.append(Finding(check, level, repo.rel(path),
                               line_of(text, m.start()), message))
    return out


def check_blur(repo: Repo) -> list[Finding]:
    """A blur is an offscreen render pass, per object, per frame.

    On Impeller a MaskFilter or ImageFilter blur cannot be folded into the pass
    it sits in: it needs its own render target, a downsample and two blur
    passes. A radial gradient reaching the same distance is one fill and no
    pass switch. That is usually a straight swap, but it is *not* a free one —
    a linear ramp does not fall off like a gaussian, so match it by eye.
    """
    return scan(
        repo,
        re.compile(r"\b(?:MaskFilter|ImageFilter)\.blur\s*\("),
        "blur-per-frame", "WARN",
        "a blur inside a per-frame method — an offscreen pass per object, "
        "per frame; a RadialGradient reaches the same distance in one fill",
    )


def check_text_layout(repo: Repo) -> list[Finding]:
    """Text shaping on the UI thread, once per frame, for a string that is
    usually constant.

    `TextPainter.layout` and `ParagraphBuilder.build` shape and line-break the
    text. A score popup that fades over 40 frames pays for that 40 times to
    draw the same four characters. Build it once; if only the opacity changes,
    quantise the opacity and cache one paragraph per step.
    """
    return scan(
        repo,
        re.compile(r"\b(?:TextPainter|ui\.ParagraphBuilder|ParagraphBuilder)"
                   r"\s*\("),
        "text-layout-per-frame", "FAIL",
        "text laid out inside a per-frame method — shaping runs on the UI "
        "thread, which is the thread jank comes from",
    )


def check_shader(repo: Repo) -> list[Finding]:
    """A gradient's Shader is an object to build, and its stops live in the
    space it was built for.

    Rebuilding it per frame allocates and defeats any caching underneath. Cache
    it against the rect it was created for — that key matters, because a
    rotation makes yesterday's shader the wrong size and a cache with no key
    stretches it across the new screen.
    """
    return scan(
        repo,
        re.compile(r"\.createShader\s*\("),
        "shader-per-frame", "WARN",
        "a Shader built inside a per-frame method — cache it against the "
        "rect it was built for",
    )


def check_save_layer(repo: Repo) -> list[Finding]:
    """saveLayer allocates an offscreen and switches render pass."""
    return scan(
        repo,
        re.compile(r"\.saveLayer\s*\("),
        "save-layer-per-frame", "NOTE",
        "saveLayer inside a per-frame method — an offscreen buffer per call; "
        "often avoidable by baking the alpha into the colour",
    )


def check_iterable_allocation(repo: Repo) -> list[Finding]:
    """Sixty throwaway lists a second, on the thread with 16ms to spare.

    `.toList()` in a per-frame sweep is the common one, and it usually finds
    nothing on almost every frame. A reused scratch list, or iterating a const
    enum instead of a map's keys, costs nothing and allocates nothing.
    """
    return scan(
        repo,
        re.compile(r"\.(?:toList|toSet)\s*\(\s*\)"),
        "allocation-per-frame", "NOTE",
        "a collection copied inside a per-frame method — reuse a scratch "
        "list, or iterate something that is already const",
    )


def check_paint_allocation(repo: Repo) -> list[Finding]:
    """A `Paint()` per draw call per frame.

    The cheapest thing on this list and the most numerous. Worth hoisting when
    the Paint is constant, which it usually is; not worth contorting the code
    for when the colour genuinely varies.
    """
    return scan(
        repo,
        re.compile(r"\bPaint\s*\(\s*\)"),
        "paint-per-frame", "NOTE",
        "a Paint allocated inside a per-frame method — hoist it to a field "
        "when its colour does not change",
    )


def check_image_decode(repo: Repo) -> list[Finding]:
    """Decoding or rasterizing inside a frame stalls that frame."""
    return scan(
        repo,
        re.compile(r"\b(?:toImageSync|toImage|decodeImageFromList|"
                   r"instantiateImageCodec|loadPicture)\s*\("),
        "decode-per-frame", "FAIL",
        "an image decoded or rasterized inside a per-frame method — do it "
        "once at load and blit from the result",
    )


def check_render_coverage(repo: Repo) -> list[Finding]:
    """A game whose tests never call `render`.

    A shader built from an empty rect, a paragraph laid out to the wrong
    constraints, a gradient whose stops do not ascend: none is a compile error,
    and a suite that only drives `update` sees none of them. The symptom is an
    invisible object falling through the sky.
    """
    # Only files that actually *draw*. A domain model with a `update(double dt)`
    # simulation tick has no render-time faults to miss, and counting one made
    # this check point at a file with no canvas in it.
    draws = [
        re.compile(r"\bvoid\s+render\s*\(\s*(?:ui\.)?Canvas\b"),
        re.compile(r"\bvoid\s+paint\s*\(\s*(?:ui\.)?Canvas\b"),
    ]
    hot_files = [
        p for p in repo.lib
        if any(d.search(strip_comments(repo.read(p))) for d in draws)
    ]
    if not hot_files:
        return []

    tests: list[Path] = []
    for g in ("test/**/*.dart", "packages/*/test/**/*.dart"):
        tests += list(repo.root.glob(g))
    if any(re.search(r"\.render\s*\(|renderTree\s*\(|toImage\s*\(",
                     p.read_text(encoding="utf-8", errors="replace"))
           for p in tests):
        return []

    return [Finding(
        "render-untested", "WARN", repo.rel(hot_files[0]), 1,
        f"{len(hot_files)} file(s) draw per frame and no test ever calls "
        "render — render-time faults cannot fail this suite",
    )]


def check_probe(repo: Repo) -> list[Finding]:
    """No harness means every future change to this is a guess."""
    found = list(repo.root.glob("tool/**/*perf*.dart"))
    found += list(repo.root.glob("tool/**/*bench*.dart"))
    if found:
        return []
    if not any(hot_spans(strip_comments(repo.read(p))) for p in repo.lib):
        return []
    return [Finding(
        "no-probe", "NOTE", "tool/", 1,
        "no frame-cost harness in tool/ — see SKILL.md for one to copy; "
        "without it every claim about this is an opinion",
    )]


CHECKS = [
    ("text-layout-per-frame", check_text_layout),
    ("decode-per-frame", check_image_decode),
    ("blur-per-frame", check_blur),
    ("shader-per-frame", check_shader),
    ("save-layer-per-frame", check_save_layer),
    ("allocation-per-frame", check_iterable_allocation),
    ("paint-per-frame", check_paint_allocation),
    ("render-untested", check_render_coverage),
    ("no-probe", check_probe),
]

GREEN, YELLOW, RED, DIM, OFF = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
)
COLOUR = {"FAIL": RED, "WARN": YELLOW, "NOTE": DIM}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", default=".", help="app directory (default: .)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on any finding")
    ap.add_argument("--quiet", action="store_true",
                    help="hide NOTE-level findings")
    args = ap.parse_args()

    root = Path(args.app).resolve()
    repo = Repo.load(root)

    findings: list[Finding] = []
    for _, fn in CHECKS:
        findings += fn(repo)
    if args.quiet:
        findings = [f for f in findings if f.level != "NOTE"]

    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
        return 1 if (args.strict and findings) else 0

    hot = sum(
        1
        for p in repo.lib
        if any(sig.search(strip_comments(repo.read(p)))
               for sig in HOT_SIGNATURES)
    )
    print(f"Frame cost — {root.name}")
    print(f"  {len(repo.lib)} source file(s), {hot} with per-frame methods\n")

    if not findings:
        print(f"  {GREEN}✓{OFF} Nothing repeating per frame that a static "
              f"check can see.")
    else:
        by_check: dict[str, list[Finding]] = {}
        for f in findings:
            by_check.setdefault(f.check, []).append(f)
        order = [name for name, _ in CHECKS]
        for check in sorted(by_check, key=order.index):
            group = by_check[check]
            colour = COLOUR[group[0].level]
            print(f"  {colour}{group[0].level}{OFF}  {check}  ({len(group)})")
            seen_files: dict[str, int] = {}
            for f in group:
                seen_files[f.path] = seen_files.get(f.path, 0) + 1
            for f in group[:6]:
                print(f"        {DIM}{f.path}:{f.line}{OFF}")
            if len(group) > 6:
                print(f"        {DIM}… and {len(group) - 6} more in "
                      f"{len(seen_files)} file(s){OFF}")
            print(f"        {group[0].message}\n")

    print(f"{DIM}Every one of these is a hypothesis. Measure it, paired, "
          f"before and after — see SKILL.md.{OFF}")
    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
