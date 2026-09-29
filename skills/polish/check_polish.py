#!/usr/bin/env python3
"""Static checks for the polish faults that hide from a green test suite.

Every check here fired for real on a shipping app whose `flutter analyze` was
clean and whose suite was green. None of them is a style opinion: each one is a
thing a user sees and a test does not.

Advisory by design. Exits 0 unless --strict.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The narrowest tablet the app can be installed on, in logical points (iPad
# mini). A content cap wider than this never engages on any tablet in portrait,
# which is the single most common way "we handled tablets" turns out to be
# false.
NARROWEST_TABLET = 744


@dataclass
class Finding:
    check: str
    level: str  # FAIL | WARN
    path: str
    line: int
    message: str


@dataclass
class Repo:
    root: Path
    lib: list[Path] = field(default_factory=list)
    tests: list[Path] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> "Repo":
        def dart(*globs: str) -> list[Path]:
            out: list[Path] = []
            for g in globs:
                out += [
                    p
                    for p in root.glob(g)
                    if "/build/" not in str(p)
                    and not p.name.endswith(".g.dart")
                    and not p.name.endswith(".freezed.dart")
                    and ".dart_tool" not in str(p)
                ]
            return sorted(set(out))

        return cls(
            root=root,
            lib=dart("lib/**/*.dart", "packages/*/lib/**/*.dart"),
            tests=dart("test/**/*.dart", "packages/*/test/**/*.dart",
                       "integration_test/**/*.dart"),
        )

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


def check_reduce_motion(repo: Repo) -> list[Finding]:
    """Ambient animation that never stops is what Reduce Motion is for.

    A looping AnimationController runs from the moment its screen appears until
    the user leaves it, with nothing triggering it and nothing ending it. If the
    file that owns it has never heard of `disableAnimations`, it does not stop.
    """
    out = []
    for path in repo.lib:
        text = repo.read(path)
        if "disableAnimations" in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\.repeat\s*\(", line) or "repeat(reverse:" in line:
                out.append(Finding(
                    "reduce-motion", "WARN", repo.rel(path), i,
                    "a looping animation in a file that never checks "
                    "MediaQuery.disableAnimations",
                ))
                break
    return out


def check_icon_labels(repo: Repo) -> list[Finding]:
    """An icon-only button with no tooltip has no accessible name."""
    out = []
    for path in repo.lib:
        text = repo.read(path)
        # `IconButton.styleFrom(` is a style, not a button. Matching it was
        # this check's first false positive.
        #
        # The lookbehind is the second: without it this matches the *call
        # sites* of any wrapper named `_IconButton` or `AppIconButton`, which
        # is precisely the shape a codebase takes once it has fixed this
        # finding properly — one wrapper that requires a label, used
        # everywhere. So the check reported a fault at every use of the fix for
        # it, and a check that fires on the correct answer is worse than none,
        # because it teaches people to skim past this whole category. The
        # wrapper's own definition still contains a bare `IconButton(` and is
        # still checked, which is where the tooltip belongs anyway.
        for match in re.finditer(
                r"(?<![\w$])IconButton(?!\.styleFrom)(\.\w+)?\s*\(",
                text):
            # Scan forward to the matching close paren, crudely but adequately.
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
            if "tooltip:" in body or "Semantics" in body:
                continue
            line = text.count("\n", 0, match.start()) + 1
            out.append(Finding(
                "icon-label", "WARN", repo.rel(path), line,
                "IconButton with no tooltip: — nothing to announce and no "
                "long-press hint",
            ))
    return out


def check_fixed_aspect(repo: Repo) -> list[Finding]:
    """A fixed childAspectRatio ties height to width. Text wrapping unties it.

    Wider cells wrap text into *fewer* lines and need *less* height; a ratio
    says the opposite. It is wrong at both ends — cavernous tiles on a tablet,
    clipped text on a small phone — and neither end throws.
    """
    out = []
    for path in repo.lib:
        text = repo.read(path)
        for i, line in enumerate(text.splitlines(), 1):
            m = re.search(r"childAspectRatio:\s*([0-9.]+)\s*,", line)
            if m:
                out.append(Finding(
                    "fixed-aspect", "WARN", repo.rel(path), i,
                    f"childAspectRatio: {m.group(1)} is a literal — cell "
                    "height is tied to width, but text wrapping is not",
                ))
    return out


def check_content_cap(repo: Repo) -> list[Finding]:
    """A max-width above the narrowest tablet never engages on a tablet.

    The subtlety that cost a false positive on the first run: a *wide* cap is
    perfectly legitimate for a two-pane layout that only exists in landscape.
    What is not legitimate is having no narrow one — that is the shape where
    every list in the app runs edge to edge while the code looks handled.
    """
    pattern = re.compile(
        r"(?:static\s+)?const\s+\w*(?:maxWidth|MaxWidth|contentWidth|"
        r"ContentWidth|readableWidth)\w*\s*=\s*([0-9]+(?:\.[0-9]+)?)"
    )
    caps: list[tuple[Path, int, float]] = []
    for path in repo.lib:
        for i, line in enumerate(repo.read(path).splitlines(), 1):
            m = pattern.search(line)
            if m:
                caps.append((path, i, float(m.group(1))))

    if not caps:
        return []
    if any(value <= NARROWEST_TABLET for _, _, value in caps):
        # There is a usable cap. Anything wider is presumed to be a deliberate
        # two-pane one, which is a judgement call rather than a fault.
        return []
    path, line, value = min(caps, key=lambda c: c[2])
    return [Finding(
        "content-cap", "FAIL", repo.rel(path), line,
        f"the narrowest content cap is {value:g}, which never engages on any "
        f"tablet in portrait (narrowest is {NARROWEST_TABLET}pt) — every list "
        "runs edge to edge on every tablet",
    )]


def check_haptics_switch(repo: Repo) -> list[Finding]:
    """Haptics people cannot turn off are haptics people uninstall over."""
    uses, has_switch = None, False
    for path in repo.lib:
        text = repo.read(path)
        if "HapticFeedback." in text and uses is None:
            uses = repo.rel(path)
        if re.search(r"haptic|vibrat", text, re.I) and re.search(
            r"Switch|setHaptic|hapticsEnabled", text
        ):
            has_switch = True
    if uses and not has_switch:
        return [Finding(
            "haptics-switch", "WARN", uses, 1,
            "the app buzzes and offers no way to stop it",
        )]
    return []


def check_test_coverage(repo: Repo) -> list[Finding]:
    """The two surfaces a suite silently never renders at."""
    out = []
    joined = "\n".join(repo.read(p) for p in repo.tests)
    if not repo.tests:
        return out
    if "textScaler" not in joined and "textScaleFactor" not in joined:
        out.append(Finding(
            "untested-scale", "WARN", "test/", 1,
            "no test sets a text scale — Dynamic Type reaches 3.1x and "
            "layouts commonly break at 1.35x, one notch up the iOS slider",
        ))
    tablet = re.search(r"\b(7[4-9][0-9]|8[0-9][0-9]|9[0-9][0-9]|1[0-9]{3})\b",
                       joined)
    if not tablet and "iPad" not in joined:
        out.append(Finding(
            "untested-tablet", "WARN", "test/", 1,
            "no test renders at a tablet width — a stretched phone layout "
            "is invisible from a phone",
        ))
    return out


CHECKS = [
    ("content-cap", check_content_cap),
    ("reduce-motion", check_reduce_motion),
    ("fixed-aspect", check_fixed_aspect),
    ("icon-label", check_icon_labels),
    ("haptics-switch", check_haptics_switch),
    ("test-coverage", check_test_coverage),
]

GREEN, YELLOW, RED, DIM, OFF = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", default=".", help="app directory (default: .)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on any finding")
    args = ap.parse_args()

    root = Path(args.app).resolve()
    repo = Repo.load(root)

    findings: list[Finding] = []
    for _, fn in CHECKS:
        findings += fn(repo)

    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
        return 1 if (args.strict and findings) else 0

    print(f"Polish — {root.name}")
    print(f"  {len(repo.lib)} source file(s), {len(repo.tests)} test file(s)\n")

    if not findings:
        print(f"  {GREEN}✓{OFF} Nothing the static checks can see.")
    else:
        by_check: dict[str, list[Finding]] = {}
        for f in findings:
            by_check.setdefault(f.check, []).append(f)
        for check, group in by_check.items():
            colour = RED if group[0].level == "FAIL" else YELLOW
            print(f"  {colour}{group[0].level}{OFF}  {check}"
                  f"  ({len(group)})")
            for f in group[:8]:
                print(f"        {DIM}{f.path}:{f.line}{OFF}  {f.message}")
            if len(group) > 8:
                print(f"        {DIM}… and {len(group) - 8} more{OFF}")
            print()

    print(f"\n{DIM}These are the mechanical ones. The ones that matter most "
          f"need a screenshot — see SKILL.md.{OFF}")
    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
