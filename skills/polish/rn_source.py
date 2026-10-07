"""Light reading of React Native / Expo sources (TypeScript or JavaScript).

No parser, no packages: comments and string bodies are blanked with offsets
kept, then functions and JSX elements are found by bracket matching. That is
enough to answer "is this inside a frame callback", "is this inside a
component body" and "what props does this <Pressable> carry", and it is wrong
in the corners a parser would get right, so every finding built on it is a
lead to check, not a verdict.

The same file ships with the perf and polish skills so each stands alone.
Python 3.9+, stdlib only.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

Span = Tuple[int, int]

JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs")
JS_SKIP_DIRS = {"node_modules", "build", "Pods", "ios", "android", "dist",
                "web-build", "coverage", "vendor", "scripts", "lib-build"}
TEST_NAME = re.compile(r"\.(?:test|spec)\.[jt]sx?$")
CONFIG_NAME = re.compile(r"(?:^|\.)config\.[cm]?[jt]s$|^(?:babel|metro|jest|"
                         r"eslint|prettier|tailwind)\b")
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function",
            "typeof", "await", "new", "delete", "void", "yield", "super",
            "import", "export", "do", "else", "case", "in", "of", "with"}


def detect_rn(root: Path) -> bool:
    """Whether [root] (or a package up to two levels below it) depends on
    react-native or expo."""
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")
                       and d not in JS_SKIP_DIRS] if depth < 2 else []
        if "package.json" not in filenames:
            continue
        try:
            pkg = json.loads((Path(dirpath) / "package.json").read_text(
                encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(pkg.get(key), dict):
                deps.update(pkg[key])
        if "react-native" in deps or "expo" in deps:
            return True
    return False


def js_files(root: Path, tests: bool = False) -> List[Path]:
    """App sources (or, with [tests], test files) under [root].

    node_modules, build output, .expo, Pods and native folders are pruned,
    as are hidden directories, type declarations and tool config files.
    """
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in JS_SKIP_DIRS]
        in_tests = "__tests__" in Path(dirpath).relative_to(root).parts
        for name in filenames:
            if not name.endswith(JS_EXT) or name.endswith(".d.ts"):
                continue
            is_test = in_tests or bool(TEST_NAME.search(name))
            if is_test != tests:
                continue
            if not tests and CONFIG_NAME.search(name):
                continue
            out.append(Path(dirpath) / name)
    return sorted(out)


_REGEX_BEFORE = set("(,=:[!&|?{;+-*%~^")


def strip_js(text: str) -> str:
    """Blank comments and the bodies of strings, template literals and regex
    literals, keeping offsets and newlines.

    Quotes stay, so `accessibilityRole="button"` still shows the prop. A
    plain string stops at a newline, which limits the damage when an
    apostrophe in JSX text (`<Text>Don't</Text>`) is read as a quote.
    """
    out = list(text)
    i, n = 0, len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        two = text[i:i + 2]
        c = text[i]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c in "'\"`":
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c:
                    break
                if c != "`" and text[j] == "\n":
                    break
                j += 1
            blank(i + 1, j)
            i = j + 1
        elif c == "/":
            k = i - 1
            while k >= 0 and text[k] in " \t":
                k -= 1
            prev = text[k] if k >= 0 else "\n"
            word = re.search(r"(\w+)$", text[max(0, k - 10):k + 1])
            if text[i + 1:i + 2] in (">", "") or prev == "<":
                i += 1  # `/>` and `</` close JSX tags
                continue
            if prev in _REGEX_BEFORE or prev == "\n" or (
                    word and word.group(1) in ("return", "typeof", "case")):
                j, klass = i + 1, False
                while j < n and text[j] != "\n":
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == "[":
                        klass = True
                    elif text[j] == "]":
                        klass = False
                    elif text[j] == "/" and not klass:
                        break
                    j += 1
                if j < n and text[j] == "/":
                    blank(i + 1, j)
                    i = j + 1
                    continue
            i += 1
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


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _expression_end(text: str, start: int) -> int:
    """End of an arrow function's expression body starting at [start]."""
    depth, j, n = 0, start, len(text)
    while j < n:
        c = text[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return j
            depth -= 1
        elif depth == 0 and c in ",;":
            return j
        elif depth == 0 and c == "\n":
            rest = text[j + 1:j + 200].lstrip()
            if not re.match(r"(?:\?|:|\.|&&|\|\||\+|-|\*|/|<|>|=)", rest):
                return j
        j += 1
    return n


@dataclass
class Func:
    name: Optional[str]
    start: int
    params: Span
    body: Span


_FUNC_KW = re.compile(r"\bfunction\b\s*\*?\s*([A-Za-z_$][\w$]*)?\s*"
                      r"(?:<[^>()]*>)?\s*\(")
_METHOD = re.compile(r"(?m)^[ \t]*(?:(?:async|static|public|private|"
                     r"protected|get|set)\s+)*([A-Za-z_$][\w$]*)\s*"
                     r"(?:<[^>()]*>)?\s*\(")
_ARROW_NAME = re.compile(r"(?:\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
                         r"(?::[^=;]{0,200})?=\s*(?:async\s*)?$)")
_WRAPPED_NAME = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
                           r"(?::[^=;]{0,200})?=\s*(?:React\.)?(?:memo|"
                           r"forwardRef|useCallback|useMemo)\s*(?:<[^>]*>)?"
                           r"\s*\(\s*(?:async\s*)?$")


def _block_after(text: str, pos: int) -> Optional[Span]:
    """A `{...}` body after a parameter list, skipping a return type."""
    m = re.compile(r"\s*(?::\s*[^{;=]{1,200}?)?\s*\{").match(text, pos)
    if not m:
        return None
    start = m.end() - 1
    return (start, match_close(text, start))


def functions(text: str) -> List[Func]:
    """Function declarations, function expressions, arrows and methods."""
    out: List[Func] = []
    seen: set = set()
    for m in _FUNC_KW.finditer(text):
        p = m.end() - 1
        pe = match_close(text, p)
        body = _block_after(text, pe)
        if body:
            name = m.group(1)
            if not name:
                w = _WRAPPED_NAME.search(text[max(0, m.start() - 200):m.start()])
                name = w.group(1) if w else None
            out.append(Func(name, m.start(), (p, pe), body))
            seen.add(body[0])
    for m in _METHOD.finditer(text):
        name = m.group(1)
        if name in KEYWORDS or name == "function":
            continue
        p = m.end() - 1
        pe = match_close(text, p)
        body = _block_after(text, pe)
        if body and body[0] not in seen and "=>" not in text[pe:body[0]]:
            out.append(Func(name, m.start(), (p, pe), body))
            seen.add(body[0])
    for m in re.finditer(r"=>", text):
        # Find the parameter list: `(...)` or a bare identifier before `=>`.
        k = m.start() - 1
        while k >= 0 and text[k] in " \t\n":
            k -= 1
        # Skip a return type annotation `): Foo =>` (approximate).
        params: Span
        if k >= 0 and text[k] == ")":
            depth, j = 0, k
            while j >= 0:
                if text[j] == ")":
                    depth += 1
                elif text[j] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            params = (max(j, 0), k + 1)
        else:
            w = re.search(r"([A-Za-z_$][\w$]*)\s*$", text[max(0, k - 60):k + 1])
            if w and re.search(r"\)\s*:\s*[\w$.]*$",
                               text[max(0, k - 200):k + 1]):
                w = None  # `(a): Type =>` is a return type, not a param
            if w:
                params = (k + 1 - len(w.group(0).rstrip()), k + 1)
            else:
                ann = text.rfind(")", max(0, k - 200), k + 1)
                if ann < 0:
                    continue
                depth, j = 0, ann
                while j >= 0:
                    if text[j] == ")":
                        depth += 1
                    elif text[j] == "(":
                        depth -= 1
                        if depth == 0:
                            break
                    j -= 1
                params = (max(j, 0), ann + 1)
        s = re.compile(r"\s*").match(text, m.end()).end()
        if s < len(text) and text[s] == "{":
            body = (s, match_close(text, s))
        else:
            body = (s, _expression_end(text, s))
        before = text[max(0, params[0] - 250):params[0]]
        named = _ARROW_NAME.search(before) or _WRAPPED_NAME.search(before)
        out.append(Func(named.group(1) if named else None, params[0], params,
                        body))
    return out


def innermost(funcs: List[Func], pos: int) -> Optional[Func]:
    inside = [f for f in funcs if f.body[0] <= pos < f.body[1]]
    return min(inside, key=lambda f: f.body[1] - f.body[0]) if inside else None


def is_component(f: Optional[Func], path: Path) -> bool:
    return bool(f and f.name and f.name[:1].isupper()
                and path.suffix in (".tsx", ".jsx", ".js"))


@dataclass
class Element:
    name: str
    start: int
    attrs: Span          # inside the opening tag, after the name
    children: Optional[Span]  # None when self-closing
    end: int


def _tag_end(text: str, pos: int) -> Tuple[int, bool]:
    """Index just past the `>` closing an opening tag whose attributes start
    at [pos], and whether it was self-closing."""
    depth, j, n = 0, pos, len(text)
    while j < n:
        c = text[j]
        if c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif c == ">" and depth <= 0:
            return j + 1, text[j - 1] == "/"
        j += 1
    return n, True


def elements(text: str, names: "set[str] | Tuple[str, ...]") -> Iterator[Element]:
    """Every `<Name ...>` element for Name in [names], with its children."""
    alt = "|".join(sorted(map(re.escape, names), key=len, reverse=True))
    opener = re.compile(r"<(%s)(?![\w.$])" % alt)
    for m in opener.finditer(text):
        name = m.group(1)
        tag_end, self_closing = _tag_end(text, m.end())
        attrs = (m.end(), tag_end - (2 if self_closing else 1))
        if self_closing:
            yield Element(name, m.start(), attrs, None, tag_end)
            continue
        same = re.compile(r"<(/?)%s(?![\w.$])" % re.escape(name))
        depth, j = 1, tag_end
        close_at = len(text)
        while True:
            s = same.search(text, j)
            if not s:
                break
            if s.group(1):
                depth -= 1
                if depth == 0:
                    close_at = s.start()
                    break
                j = s.end()
            else:
                e, sc = _tag_end(text, s.end())
                if not sc:
                    depth += 1
                j = e
        end = text.find(">", close_at)
        yield Element(name, m.start(), attrs, (tag_end, close_at),
                      len(text) if end < 0 else end + 1)


def has_prop(attrs: str, *props: str) -> bool:
    return bool(re.search(r"(?<![\w-])(?:%s)\s*=" % "|".join(
        map(re.escape, props)), attrs)) or bool(
        re.search(r"\{\s*\.\.\.", attrs))  # a spread may carry it


def prop_value(attrs: str, prop: str) -> Optional[str]:
    """The raw value after `prop=`: a `{...}` expression or a quoted string."""
    m = re.search(r"(?<![\w-])%s\s*=\s*" % re.escape(prop), attrs)
    if not m:
        return None
    j = m.end()
    if j < len(attrs) and attrs[j] == "{":
        return attrs[j + 1:match_close(attrs, j) - 1]
    q = re.match(r"(['\"])[^'\"]*\1", attrs[j:])
    return q.group(0) if q else None


@dataclass
class Styles:
    """`StyleSheet.create` entries of one file: `styles.card` -> its text."""
    entries: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, text: str) -> "Styles":
        s = cls()
        for m in re.finditer(r"\b(?:const|let|var)\s+(\w+)\s*=\s*StyleSheet"
                             r"\.create\s*\(\s*\{", text):
            sheet = m.group(1)
            open_at = m.end() - 1
            body_end = match_close(text, open_at) - 1
            j = open_at + 1
            entry = re.compile(r"\s*,?\s*(\w+)\s*:\s*\{")
            while j < body_end:
                e = entry.match(text, j)
                if not e:
                    nxt = text.find(",", j + 1)
                    if nxt < 0 or nxt >= body_end:
                        break
                    j = nxt
                    continue
                o = e.end() - 1
                c = match_close(text, o)
                s.entries[f"{sheet}.{e.group(1)}"] = text[o + 1:c - 1]
                j = c
        return s

    def resolve(self, style_expr: Optional[str]) -> str:
        """The top-level keys a `style={...}` expression can reach (inline
        objects plus referenced sheet entries), one part per line. Nested
        objects (`textShadowOffset: { height: 3 }`) are removed."""
        if not style_expr:
            return ""
        parts = []
        j = 0
        while True:
            o = style_expr.find("{", j)
            if o < 0:
                break
            c = match_close(style_expr, o)
            parts.append(style_expr[o + 1:c - 1])
            j = c
        for ref in re.findall(r"\b(\w+\.\w+)\b", style_expr):
            if ref in self.entries:
                parts.append(self.entries[ref])
        return "\n".join(_flat(p) for p in parts)


def _flat(text: str) -> str:
    """[text] with every nested `{...}` and `[...]` group removed."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\{[^{}]*\}|\[[^\[\]]*\]", " ", text)
    return text


def number_prop(style_text: str, prop: str) -> Optional[float]:
    m = re.search(r"(?<![\w$])%s\s*:\s*([0-9]+(?:\.[0-9]+)?)\b(?!\s*[*/+-])"
                  % re.escape(prop), style_text)
    return float(m.group(1)) if m else None


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
