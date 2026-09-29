#!/usr/bin/env python3
"""Static checks for the polish faults a green Flutter test suite never sees.

Each one is a thing a user sees and a test does not:

  content-cap      a max content width no tablet reaches in portrait
  reduce-motion    a looping animation in a file that ignores Reduce Motion
  fixed-aspect     a literal childAspectRatio, which clips text or wastes space
  icon-label       an IconButton with no tooltip, so no accessible name
  haptics-switch   haptics that bypass the system switch, with no in-app one
  untested-scale   no test sets a large text scale
  untested-tablet  no test renders at a tablet size

A shape can be deliberate, so everything is advisory: exits 0 unless
--strict. Python 3.9+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

# The narrowest iPad in portrait, in logical points (iPad mini). A content cap
# wider than this never engages on that tablet; one wider than 1024 (the
# largest iPad in portrait) never engages on any.
NARROWEST_TABLET = 744
# A shortest side at least this big is a tablet, not a phone.
TABLET_SHORTEST_SIDE = 600

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


def dart_files(root: Path, *tops: str) -> List[Path]:
    """Non-generated .dart files under any `lib/`, `test/`... directory in
    [root], so monorepos (packages/*, apps/*) work. Hidden directories are
    pruned, which keeps `.dart_tool` and an FVM SDK out of the scan."""
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS]
        parts = Path(dirpath).relative_to(root).parts
        if not any(t in parts for t in tops):
            continue
        for name in filenames:
            if name.endswith(".dart") and not name.endswith(GENERATED):
                out.append(Path(dirpath) / name)
    return sorted(out)


def strip_comments(text: str) -> str:
    """Blank comments, keeping offsets and newlines, so a doc comment that
    explains a fix is not reported as the fault."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = " " * (j - i)
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif text[i] in "'\"":
            # Skip string bodies so `//` inside a URL is not a comment.
            quote = text[i]
            end = quote * 3 if text[i:i + 3] == quote * 3 else quote
            j = i + len(end)
            while j < n and text[j:j + len(end)] != end:
                j += 2 if text[j] == "\\" else 1
            i = j + len(end)
        else:
            i += 1
    return "".join(out)


@dataclass
class Repo:
    root: Path
    lib: List[Path] = field(default_factory=list)
    tests: List[Path] = field(default_factory=list)
    _cache: Dict[Path, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Repo":
        return cls(root=root, lib=dart_files(root, "lib"),
                   tests=dart_files(root, "test", "integration_test"))

    def read(self, path: Path) -> str:
        if path not in self._cache:
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                raw = ""
            self._cache[path] = strip_comments(raw)
        return self._cache[path]

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def check_content_cap(repo: Repo) -> List[Finding]:
    """A max-width wider than the narrowest tablet never engages on it.

    A wide cap is legitimate for a two-pane landscape layout. Having no
    narrow one is the fault: every list runs edge to edge on every tablet
    while the code looks handled.
    """
    pattern = re.compile(
        r"(?:static\s+)?const\s+(?:double\s+)?\w*(?:maxWidth|MaxWidth|"
        r"contentWidth|ContentWidth|readableWidth|ReadableWidth)\w*\s*=\s*"
        r"([0-9]+(?:\.[0-9]+)?)")
    caps = []
    for path in repo.lib:
        text = repo.read(path)
        for m in pattern.finditer(text):
            caps.append((path, line_of(text, m.start()), float(m.group(1))))
    if not caps or any(v <= NARROWEST_TABLET for _, _, v in caps):
        return []
    path, line, value = min(caps, key=lambda c: c[2])
    where = ("any iPad in portrait (largest is 1024pt)" if value > 1024 else
             f"the smallest iPad in portrait ({NARROWEST_TABLET}pt)")
    return [Finding(
        "content-cap", "FAIL" if value > 1024 else "WARN", repo.rel(path),
        line, f"the narrowest content cap is {value:g}, which never engages "
        f"on {where}: lists run edge to edge",
    )]


def reduce_motion_helpers(repo: Repo) -> Set[str]:
    """Names of getters/functions that wrap `disableAnimations`, so a file
    that calls `context.reduceMotion` counts as honouring it."""
    names: Set[str] = set()
    decl = re.compile(r"(?:\bget\s+(\w+)|\b(\w+)\s*\([^()]*\)\s*(?:=>|\{))")
    for path in repo.lib:
        text = repo.read(path)
        for m in re.finditer(r"disableAnimations", text):
            before = text[max(0, m.start() - 200):m.start()]
            found = list(decl.finditer(before))
            if found:
                name = found[-1].group(1) or found[-1].group(2)
                if len(name) >= 4 and name not in {"build", "maybeOf"}:
                    names.add(name)
    return names


def check_reduce_motion(repo: Repo) -> List[Finding]:
    """A looping controller runs from the moment its screen appears until the
    user leaves. If its file never consults Reduce Motion, it never stops."""
    honour = ["disableAnimations"] + sorted(reduce_motion_helpers(repo))
    honours = re.compile(r"\b(?:%s)\b|disableAnimations" %
                         "|".join(map(re.escape, honour)))
    out = []
    for path in repo.lib:
        text = repo.read(path)
        if "AnimationController" not in text or honours.search(text):
            continue
        m = re.search(r"\.repeat\s*\(", text)
        if m:
            out.append(Finding(
                "reduce-motion", "WARN", repo.rel(path), line_of(text, m.start()),
                "a looping animation in a file that never checks "
                "MediaQuery.disableAnimationsOf (Reduce Motion)",
            ))
    return out


def check_fixed_aspect(repo: Repo) -> List[Finding]:
    """A fixed childAspectRatio ties cell height to width; text wrapping does
    the opposite (wider means fewer lines). Wrong at both ends and neither
    end throws. Fine for cells holding only an image or a colour."""
    out = []
    for path in repo.lib:
        text = repo.read(path)
        for m in re.finditer(r"childAspectRatio:\s*([0-9.]+)\s*[,)]", text):
            out.append(Finding(
                "fixed-aspect", "WARN", repo.rel(path),
                line_of(text, m.start()),
                f"childAspectRatio: {m.group(1)} is a literal; if the cell "
                "holds text, it clips on a phone or balloons on a tablet",
            ))
    return out


def labelled_by_wrapper(text: str, pos: int) -> bool:
    """Whether the widget at [pos] is the child of a `Semantics(label: ...)`
    or a `Tooltip(...)` whose parentheses enclose it."""
    for m in re.finditer(r"\b(?:Semantics|Tooltip)\s*\(",
                         text[max(0, pos - 300):pos]):
        start = max(0, pos - 300) + m.end() - 1
        depth, j = 0, start
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j > pos and re.search(r"\b(?:label|message)\s*:",
                                 text[start:pos]):
            return True
    return False


def check_icon_labels(repo: Repo) -> List[Finding]:
    """An icon-only button with no tooltip has no accessible name.

    The lookbehind skips wrappers like `AppIconButton(`: a codebase that fixed
    this properly has one wrapper requiring a label, and reporting every call
    site of the fix teaches people to skim the whole category. The wrapper's
    own `IconButton(` is still checked.
    """
    out = []
    for path in repo.lib:
        text = repo.read(path)
        for match in re.finditer(
                r"(?<![\w$])IconButton(?!\.styleFrom)(\.\w+)?\s*\(", text):
            depth, j = 0, match.end() - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            body = text[match.end():j]
            if re.search(r"\b(?:tooltip|semanticLabel)\s*:", body) or \
                    "Semantics(" in body or \
                    labelled_by_wrapper(text, match.start()):
                continue
            out.append(Finding(
                "icon-label", "WARN", repo.rel(path),
                line_of(text, match.start()),
                "IconButton with no tooltip: nothing for a screen reader to "
                "announce and no long-press hint",
            ))
    return out


def check_haptics_switch(repo: Repo) -> List[Finding]:
    """Haptics a user cannot turn off.

    Flutter's `HapticFeedback` already obeys the system setting (iOS System
    Haptics, Android Touch feedback), so on its own it only earns a NOTE for
    a game that buzzes often. A vibration plugin calls the vibrator directly
    and ignores that setting, so without an in-app switch it is a WARN.
    """
    plugin_use: Optional[str] = None
    haptic_use: Optional[str] = None
    has_switch = False
    for path in repo.lib:
        text = repo.read(path)
        if plugin_use is None and re.search(
                r"\b(?:Vibration|Vibrate|Haptics)\.\w+\s*\(", text):
            plugin_use = repo.rel(path)
        if haptic_use is None and "HapticFeedback." in text:
            haptic_use = repo.rel(path)
        if re.search(r"haptic|vibrat", text, re.I) and (
                re.search(r"\b(?:Switch|SwitchListTile|CupertinoSwitch|"
                          r"Checkbox|CheckboxListTile)\b", text) or
                re.search(r"(?i:set\w*(?:haptic|vibrat))|"
                          r"(?i:haptic|vibrat)\w*(?:Enabled|On)\b", text)):
            has_switch = True
    if has_switch:
        return []
    if plugin_use:
        return [Finding(
            "haptics-switch", "WARN", plugin_use, 1,
            "a vibration plugin bypasses the system haptics setting and the "
            "app has no switch of its own",
        )]
    if haptic_use:
        return [Finding(
            "haptics-switch", "NOTE", haptic_use, 1,
            "HapticFeedback obeys the system switch, so this is fine unless "
            "the app buzzes often; a game that does should offer its own",
        )]
    return []


def logical_sizes(text: str) -> List[float]:
    """Shortest sides of every size a test file renders at, in logical px.

    `physicalSize` is in device pixels: divided by the file's
    `devicePixelRatio`, or by 3.0, the flutter_test default, if unset.
    """
    dpr_m = re.search(r"devicePixelRatio\w*\s*=\s*([0-9.]+)", text)
    dpr = float(dpr_m.group(1)) if dpr_m else 3.0
    out = []
    for m in re.finditer(
            r"\b(?:Size|Vector2)\s*\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)", text):
        side = min(float(m.group(1)), float(m.group(2)))
        if "physicalSize" in text[max(0, m.start() - 60):m.start()]:
            side /= dpr
        out.append(side)
    return out


def check_test_coverage(repo: Repo) -> List[Finding]:
    """The two settings a suite most often never renders at."""
    out = []
    texts = [repo.read(p) for p in repo.tests]
    joined = "\n".join(texts)
    if not re.search(r"textScaler|textScaleFactor", joined):
        out.append(Finding(
            "untested-scale", "WARN", "test/", 1,
            "no test sets a text scale; iOS Dynamic Type reaches about 3.1x "
            "and layouts commonly break at 1.35x, one notch up the slider",
        ))
    tablet = any(s >= TABLET_SHORTEST_SIDE
                 for t in texts for s in logical_sizes(t))
    if not tablet and not re.search(r"ipad|tablet", joined, re.I):
        out.append(Finding(
            "untested-tablet", "WARN", "test/", 1,
            "no test renders at a tablet size (shortest side >= 600); a "
            "stretched phone layout is invisible from a phone",
        ))
    return out


CHECKS = [
    ("content-cap", check_content_cap),
    ("reduce-motion", check_reduce_motion),
    ("fixed-aspect", check_fixed_aspect),
    ("icon-label", check_icon_labels),
    ("haptics-switch", check_haptics_switch),
    ("untested-scale / untested-tablet", check_test_coverage),
]

COLOUR = {"FAIL": "\033[31m", "WARN": "\033[33m", "NOTE": "\033[2m"}
GREEN, DIM, OFF = "\033[32m", "\033[2m", "\033[0m"
RANK = {"FAIL": 0, "WARN": 1, "NOTE": 2}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
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
    else:
        findings = [f for _, fn in CHECKS for f in fn(repo)]
    if args.quiet:
        findings = [f for f in findings if f.level != "NOTE"]
    code = 1 if (args.strict and findings) else 0

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
        return code

    tty = sys.stdout.isatty()

    def c(colour: str, s: str) -> str:
        return f"{colour}{s}{OFF}" if tty else s

    print(f"Polish: {root.name}")
    print(f"  {len(repo.lib)} source file(s), {len(repo.tests)} test "
          "file(s)\n")
    if not findings:
        print(f"  {c(GREEN, 'OK')}  nothing the static checks can see.")
    groups: Dict[str, List[Finding]] = {}
    for f in sorted(findings, key=lambda f: RANK[f.level]):
        groups.setdefault(f.check, []).append(f)
    for check, group in groups.items():
        level = group[0].level
        print(f"  {c(COLOUR[level], level)}  {check}  ({len(group)})")
        for f in group[:8]:
            print(f"        {c(DIM, f'{f.path}:{f.line}')}  {f.message}")
        if len(group) > 8:
            print(c(DIM, f"        ... and {len(group) - 8} more"))
        print()
    print(c(DIM, "These are the mechanical ones. The ones that matter most "
                 "need a screenshot: see SKILL.md."))
    return code


if __name__ == "__main__":
    sys.exit(main())
