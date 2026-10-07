"""React Native / Expo checks for check_perf.py.

Same discriminator as the Flutter checks: scope. A `Skia.Paint()`, a shader,
a `.map()` or a `console.log` is unremarkable in an event handler and a
per-frame cost in a frame callback. So the per-frame code is found first:

  certain   useFrameCallback(...)            Reanimated, runs on the UI thread
            requestAnimationFrame(...)       a JS-thread loop
            any function taking an SkCanvas  react-native-skia drawing
  while     useDerivedValue / useAnimatedStyle / useAnimatedProps /
  animating useAnimatedReaction / createPicture: these re-run whenever a
            shared value they read changes, which is every frame only while
            something is animating. Reported one level lower, tagged.

Functions those call are followed three levels down, across files through
relative and tsconfig-alias imports (`@/game/simulation`), because the
allocation is usually in the `stepWorld` the frame callback calls.

Separately, component render bodies (scope "render") get the React checks:
inline props to memoized children, StyleSheet.create per render, heavy work
outside useMemo, mapped lists in a ScrollView. A render runs on state
changes, not per frame, so these are leads about re-render cost.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import rn_source as rs

Span = Tuple[int, int]

CERTAIN_CALLS = {"useFrameCallback": "frame", "requestAnimationFrame": "raf"}
ANIM_CALLS = ("useDerivedValue", "useAnimatedStyle", "useAnimatedProps",
              "useAnimatedReaction", "createPicture")
HOOK_CALL = re.compile(r"(?<![\w.$])(%s)\s*\(" % "|".join(
    list(CERTAIN_CALLS) + list(ANIM_CALLS)))
CALL = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*(?:<[^<>()]*>)?\s*\(")
LAZY = re.compile(r"(?:\?\?=|\|\|=|\?\?|\|\|)\s*\(?\s*$")
IMPORT = re.compile(r"import\s+(?:type\s+)?(?:\w+\s*,\s*)?\{([^}]*)\}\s*from\s*"
                    r"(['\"])([^'\"]+)\2")

ANIM_TAG = (" [in a shared-value callback: per-frame only while a value it "
            "reads is animating]")
LOWER = {"FAIL": "WARN", "WARN": "NOTE", "NOTE": "NOTE"}


@dataclass
class HotSpan:
    span: Span
    certain: bool
    origin: str  # frame | raf | canvas | anim


class RNRepo:
    def __init__(self, root: Path):
        self.root = root
        self.files = rs.js_files(root)
        self.tests = rs.js_files(root, tests=True)
        self._raw: Dict[Path, str] = {}
        self._text: Dict[Path, str] = {}
        self._funcs: Dict[Path, List[rs.Func]] = {}
        self.aliases = self._aliases()
        self.hot: Dict[Path, List[HotSpan]] = {}
        self._build_hot()

    # -- reading ---------------------------------------------------------
    def raw(self, p: Path) -> str:
        if p not in self._raw:
            self._raw[p] = rs.read(p)
        return self._raw[p]

    def text(self, p: Path) -> str:
        if p not in self._text:
            self._text[p] = rs.strip_js(self.raw(p))
        return self._text[p]

    def funcs(self, p: Path) -> List[rs.Func]:
        if p not in self._funcs:
            self._funcs[p] = rs.functions(self.text(p))
        return self._funcs[p]

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)

    # -- imports ---------------------------------------------------------
    def _aliases(self) -> List[Tuple[str, Path]]:
        """tsconfig `paths` such as `"@/*": ["./src/*"]`."""
        cfg = self.root / "tsconfig.json"
        try:
            data = json.loads(re.sub(r"(?m)^\s*//.*$|,(\s*[}\]])", r"\1",
                                     cfg.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            data = {}
        opts = data.get("compilerOptions", {}) if isinstance(data, dict) else {}
        base = self.root / opts.get("baseUrl", ".")
        out = []
        for key, targets in (opts.get("paths") or {}).items():
            if key.endswith("/*") and targets:
                out.append((key[:-1], base / targets[0].rstrip("*")))
        if not out and (self.root / "src").is_dir():
            out.append(("@/", self.root / "src"))  # the Expo default
        return out

    def resolve(self, frm: Path, spec: str) -> Optional[Path]:
        if spec.startswith("."):
            base = frm.parent / spec
        else:
            base = None
            for prefix, target in self.aliases:
                if spec.startswith(prefix):
                    base = target / spec[len(prefix):]
                    break
            if base is None:
                return None
        for cand in [base] + [Path(str(base) + e) for e in rs.JS_EXT] + [
                base / ("index" + e) for e in rs.JS_EXT]:
            if cand.is_file():
                return cand.resolve()
        return None

    def imports(self, p: Path) -> Dict[str, Path]:
        out: Dict[str, Path] = {}
        for m in IMPORT.finditer(self.raw(p)):
            target = self.resolve(p, m.group(3))
            if not target:
                continue
            for name in m.group(1).split(","):
                name = re.sub(r"^\s*type\s+", "", name).strip()
                if not name:
                    continue
                parts = re.split(r"\s+as\s+", name)
                out[parts[-1].strip()] = target
        return out

    # -- per-frame spans -------------------------------------------------
    def _build_hot(self) -> None:
        files = {p.resolve(): p for p in self.files}
        frontier: Dict[Tuple[Path, str], Tuple[bool, str]] = {}

        def add(p: Path, span: Span, certain: bool, origin: str) -> None:
            self.hot.setdefault(p, []).append(HotSpan(span, certain, origin))
            for name in self.calls_in(p, span):
                key = (p, name)
                old = frontier.get(key)
                if not old or (certain and not old[0]):
                    frontier[key] = (certain, origin)

        for p in self.files:
            text = self.text(p)
            for m in HOOK_CALL.finditer(text):
                hook = m.group(1)
                if hook == "createPicture" and (
                        _in_call(text, m.start(), "useMemo") or
                        _in_call(text, m.start(), "useCallback")):
                    continue  # recorded once per dependency change
                open_at = m.end() - 1
                span = (open_at, rs.match_close(text, open_at))
                certain = hook in CERTAIN_CALLS
                origin = CERTAIN_CALLS.get(hook, "anim")
                add(p, span, certain, origin)
                bare = re.match(r"\(\s*([A-Za-z_$][\w$]*)\s*[,)]", text[open_at:])
                if bare:
                    frontier.setdefault((p, bare.group(1)), (certain, origin))
            for f in self.funcs(p):
                if re.search(r"\bSkCanvas\b", self.raw(p)[f.params[0]:f.params[1]]):
                    add(p, f.body, True, "canvas")

        seen: Set[Tuple[Path, str]] = set()
        for _ in range(3):
            nxt: Dict[Tuple[Path, str], Tuple[bool, str]] = {}
            for (p, name), (certain, origin) in frontier.items():
                if (p, name) in seen:
                    continue
                seen.add((p, name))
                target, decls = p, [f for f in self.funcs(p) if f.name == name]
                if not decls:
                    imp = self.imports(p).get(name)
                    if imp and imp in files:
                        target = files[imp]
                        decls = [f for f in self.funcs(target) if f.name == name]
                for f in decls:
                    self.hot.setdefault(target, []).append(
                        HotSpan(f.body, certain, origin))
                    for callee in self.calls_in(target, f.body):
                        key = (target, callee)
                        old = nxt.get(key)
                        if not old or (certain and not old[0]):
                            nxt[key] = (certain, origin)
            frontier = nxt

    def calls_in(self, p: Path, span: Span) -> Set[str]:
        text = self.text(p)
        out: Set[str] = set()
        for m in CALL.finditer(text, span[0], span[1]):
            name = m.group(1)
            if name in rs.KEYWORDS or name in CERTAIN_CALLS or name in ANIM_CALLS:
                continue
            if LAZY.search(text[max(span[0], m.start() - 40):m.start()]):
                continue
            out.add(name)
        return out

    def hot_at(self, p: Path, pos: int) -> Optional[HotSpan]:
        """The strongest per-frame span covering [pos], if any."""
        hits = [h for h in self.hot.get(p, []) if h.span[0] <= pos < h.span[1]]
        if not hits:
            return None
        return max(hits, key=lambda h: (h.certain, h.origin != "anim"))


@dataclass
class Rule:
    check: str
    level: str
    pattern: "re.Pattern[str]"
    message: str
    origins: Optional[Set[str]] = None
    unless_guarded: bool = False


def _guarded(text: str, span: Span, pos: int) -> bool:
    """Whether [pos] only runs under a condition inside [span]: an `if`
    body, or the right side of `&&` / `?` on the same line."""
    line_start = text.rfind("\n", 0, pos) + 1
    if re.search(r"&&|\?", text[line_start:pos]):
        return True
    for m in re.finditer(r"\bif\s*\(", text[span[0]:pos]):
        cond_open = span[0] + m.end() - 1
        cond_end = rs.match_close(text, cond_open)
        if cond_end > pos:
            continue
        s = re.compile(r"\s*").match(text, cond_end).end()
        if s < len(text) and text[s] == "{":
            end = rs.match_close(text, s)
        else:
            end = text.find(";", s)
            nl = text.find("\n", s)
            end = min(x for x in (end, nl, len(text)) if x >= 0) + 1
        if s <= pos < end:
            return True
    return False


FRAME_RULES = [
    Rule("text-layout-per-frame", "FAIL",
         re.compile(r"\bSkia\.(?:ParagraphBuilder\.Make|Font)\s*\(|"
                    r"(?<![\w.$])matchFont\s*\("),
         "a paragraph or font built inside per-frame code; shaping runs on "
         "the thread that draws the frame. Build it once and keep it"),
    Rule("text-layout-per-frame", "WARN",
         re.compile(r"\.(?:measureText|getGlyphWidths)\s*\("),
         "text measured inside per-frame code; for a label that changes "
         "rarely, measure once per new string and cache the width"),
    Rule("decode-per-frame", "FAIL",
         re.compile(r"\bSkia\.(?:Image\.MakeImageFromEncoded|Data\.fromBytes|"
                    r"Data\.fromBase64|SVG\.MakeFromString|SVG\.MakeFromData|"
                    r"RuntimeEffect\.Make)\s*\(|\.makeImageSnapshot\s*\("),
         "an image decoded, an SVG parsed, a shader compiled or a snapshot "
         "taken inside per-frame code; do it once at load and draw from the "
         "result"),
    Rule("blur-per-frame", "WARN",
         re.compile(r"\bSkia\.(?:ImageFilter|MaskFilter)\.MakeBlur\s*\("),
         "a blur filter created inside per-frame code: an offscreen pass per "
         "object per frame. Create it once, or a radial gradient reaching the "
         "same distance is one fill"),
    Rule("shader-per-frame", "WARN",
         re.compile(r"\bSkia\.Shader\.Make\w*\s*\(|\.makeShader\w*\s*\("),
         "a Shader built inside per-frame code; cache it keyed on the "
         "geometry it was built for (a moving object can use a local matrix)"),
    Rule("save-layer-per-frame", "NOTE",
         re.compile(r"\.saveLayer\s*\("),
         "saveLayer inside per-frame code: an offscreen buffer per call. "
         "Often avoidable by baking the alpha into the colour"),
    Rule("path-per-frame", "WARN",
         re.compile(r"\bSkia\.Path\.MakeFromSVGString\s*\("),
         "an SVG path string parsed inside per-frame code; parse once and "
         "transform the result"),
    Rule("path-per-frame", "NOTE",
         re.compile(r"\bSkia\.(?:Path|PathBuilder)\.Make\s*\("),
         "a Path built inside per-frame code; when its shape is constant, "
         "build it once and draw it with a transform"),
    Rule("paint-per-frame", "NOTE",
         re.compile(r"\bSkia\.Paint\s*\(\s*\)"),
         "a Paint allocated inside per-frame code; keep one (useMemo, or a "
         "module constant) and mutate it"),
    Rule("color-parse-per-frame", "NOTE",
         re.compile(r"\bSkia\.Color\s*\("),
         "Skia.Color() parses and allocates on every call; precompute the "
         "colours a frame uses"),
    Rule("allocation-per-frame", "NOTE",
         re.compile(r"\.(?:map|filter|slice|concat|flatMap)\s*\(|"
                    r"\[\s*\.\.\.|\{\s*\.\.\.(?=\s*\w)|"
                    r"\bObject\.(?:keys|values|entries|assign)\s*\(|"
                    r"\bJSON\.(?:parse|stringify)\s*\(|"
                    r"\bnew\s+(?:Array|Map|Set|Date|Float32Array|Float64Array)\b"),
         "a collection or object copied inside per-frame code; reuse a "
         "scratch array or iterate in place. The garbage collector pays for "
         "it later, in some other frame"),
    Rule("js-roundtrip-per-frame", "WARN",
         re.compile(r"(?<![\w.$])(?:runOnJS|scheduleOnRN)\s*\("),
         "a hop to the JS thread on every frame (runOnJS / scheduleOnRN, not "
         "behind a condition); send only when something changed, or keep the "
         "consumer on the UI thread with a shared value",
         origins={"frame", "anim", "canvas"}, unless_guarded=True),
    Rule("console-per-frame", "WARN",
         re.compile(r"\bconsole\.(?:log|info|warn|debug|trace)\s*\("),
         "console logging inside per-frame code; React Native's performance "
         "guide calls console statements a big bottleneck on the JS thread, "
         "and from a worklet each one crosses threads"),
    Rule("setstate-per-frame", "WARN",
         re.compile(r"(?<![\w.$])(?:set(?!Timeout|Interval|Immediate)"
                    r"[A-Z]\w*|this\.setState)\s*\("),
         "React state set inside a requestAnimationFrame loop re-renders the "
         "component every frame; move per-frame values to a ref, an "
         "Animated/shared value, or Reanimated's useFrameCallback",
         origins={"raf"}),
]


@dataclass
class RNFinding:
    check: str
    level: str
    path: str
    line: int
    message: str
    scope: str = "frame"


def check_frame(repo: RNRepo) -> List[RNFinding]:
    out: List[RNFinding] = []
    seen: Set[Tuple[str, str, int]] = set()
    probe = re.compile(r"perf|bench|probe|fps|jank", re.I)
    for p in repo.files:
        if not repo.hot.get(p) or probe.search(p.name):
            continue  # a measuring harness is allowed to log
        text = repo.text(p)
        for rule in FRAME_RULES:
            for m in rule.pattern.finditer(text):
                h = repo.hot_at(p, m.start())
                if h is None:
                    continue
                if rule.origins and h.origin not in rule.origins:
                    continue
                if LAZY.search(text[max(0, m.start() - 40):m.start()]):
                    continue  # `cache ??= Skia.Paint()`
                if rule.unless_guarded and _guarded(text, h.span, m.start()):
                    continue
                line = rs.line_of(text, m.start())
                key = (rule.check, repo.rel(p), line)
                if key in seen:
                    continue
                seen.add(key)
                out.append(RNFinding(
                    rule.check, rule.level if h.certain else LOWER[rule.level],
                    repo.rel(p), line,
                    rule.message + ("" if h.certain else ANIM_TAG),
                    "frame" if h.certain else "repaint"))
    return out


# ------------------------------------------------------------ render bodies

MEMO_DECL = re.compile(
    r"\b(?:const|let|var)\s+([A-Z]\w*)\s*(?::[^=]+)?=\s*(?:React\.)?memo\s*\(|"
    r"\bexport\s+default\s+(?:React\.)?memo\s*\(\s*([A-Z]\w*)|"
    r"\b([A-Z]\w*)\s*=\s*(?:React\.)?memo\s*\(\s*[A-Z]")
INLINE_PROP = re.compile(
    r"(?<![\w-])(?!key\b|ref\b)(\w+)\s*=\s*\{\s*(?:\{|\[|"
    r"(?:async\s*)?\([^()]*\)\s*(?::[^=]+)?=>|(?:async\s+)?\w+\s*=>|"
    r"function\b|[\w.]+\.bind\s*\()")


def memo_components(repo: RNRepo) -> Set[str]:
    names: Set[str] = set()
    for p in repo.files:
        for m in MEMO_DECL.finditer(repo.text(p)):
            names.add(next(g for g in m.groups() if g))
    return names


def _in_call(text: str, pos: int, callee: str) -> bool:
    """Whether [pos] sits inside the arguments of a `callee(...)` call."""
    for m in re.finditer(r"(?<![\w$])%s\s*(?:<[^<>()]*>)?\s*\(" % callee,
                         text[max(0, pos - 4000):pos]):
        open_at = max(0, pos - 4000) + m.end() - 1
        if rs.match_close(text, open_at) > pos:
            return True
    return False


def check_render(repo: RNRepo) -> List[RNFinding]:
    out: List[RNFinding] = []
    memo = memo_components(repo)

    def add(check: str, level: str, p: Path, pos: int, msg: str) -> None:
        out.append(RNFinding(check, level, repo.rel(p),
                             rs.line_of(repo.text(p), pos), msg, "render"))

    for p in repo.files:
        text = repo.text(p)
        funcs = repo.funcs(p)

        if memo:
            for el in rs.elements(text, memo):
                attrs = text[el.attrs[0]:el.attrs[1]]
                for m in INLINE_PROP.finditer(attrs):
                    add("inline-prop-to-memo", "WARN", p, el.attrs[0] + m.start(),
                        f"<{el.name}> is memo()-wrapped, and an inline object, "
                        "array or function prop is new on every render, so "
                        "the memo never skips. Hoist it, or useMemo/useCallback")
                    break

        for m in re.finditer(r"\bStyleSheet\.create\s*\(", text):
            f = rs.innermost(funcs, m.start())
            if f and not _in_call(text, m.start(), "useMemo"):
                add("stylesheet-in-render", "NOTE", p, m.start(),
                    "StyleSheet.create inside a function builds a new style "
                    "object on every call; create it once at module scope "
                    "and pick variants with an array")

        for m in re.finditer(r"\.(?:sort|reduce|toSorted)\s*\(|"
                             r"\bJSON\.(?:parse|stringify)\s*\(", text):
            f = rs.innermost(funcs, m.start())
            if rs.is_component(f, p) and not repo.hot_at(p, m.start()):
                add("heavy-in-render", "NOTE", p, m.start(),
                    "sorting, reducing or JSON work directly in a component "
                    "body reruns on every render; if the input is large or "
                    "rarely changes, wrap it in useMemo")

        for el in rs.elements(text, ("ScrollView",)):
            if not el.children:
                continue
            kids = text[el.children[0]:el.children[1]]
            m = re.search(r"(\]|\b[A-Z][A-Z0-9_]+)?\s*\.map\s*\(\s*"
                          r"(?:\([^()]*\)|\w+)\s*=>\s*\(?\s*<", kids)
            if m and not m.group(1):  # a literal or CONSTANT list is fixed
                add("list-in-scrollview", "NOTE", p, el.children[0] + m.start(),
                    "a mapped list inside a ScrollView renders every row at "
                    "once; if it can grow past a screen or two, use FlatList "
                    "(or FlashList) so rows render on demand")

        for el in rs.elements(text, ("FlatList", "SectionList", "FlashList",
                                     "VirtualizedList")):
            attrs = text[el.attrs[0]:el.attrs[1]]
            ri = re.search(r"\brenderItem\s*=\s*\{\s*(?:\(|\w+\s*=>|function)",
                           attrs)
            if ri:
                add("inline-render-item", "NOTE", p, el.attrs[0] + ri.start(),
                    f"<{el.name}> gets an inline renderItem, recreated every "
                    "render; React Native's list guide says move it out of "
                    "the JSX and wrap it in useCallback")

        for m in re.finditer(r"\bkey\s*=\s*\{\s*(?:index|idx|i)\s*\}|"
                             r"\bkeyExtractor\s*=\s*\{\s*\(\s*\w+\s*,\s*(\w+)\s*\)"
                             r"\s*=>\s*(?:String\s*\(\s*\1\s*\)|\1\b|`)", text):
            src = list(re.finditer(r"Array\.from\s*\(\s*\{\s*length\b|"
                                   r"(\]|\b[A-Z][A-Z0-9_]+)?\s*\.map\s*\(",
                                   text[max(0, m.start() - 600):m.start()]))
            if src and (src[-1].group(0).startswith("Array") or src[-1].group(1)):
                continue  # a fixed list (pips, stars, a CONSTANT) never reorders
            add("index-key", "NOTE", p, m.start(),
                "a list keyed by index: inserting or removing a row re-renders "
                "every row after it and can hand one row's state to another; "
                "key by a stable id")
    return out


def check_probe(repo: RNRepo) -> List[RNFinding]:
    if not any(h.certain for hs in repo.hot.values() for h in hs):
        return []
    name = re.compile(r"perf|bench|probe|fps|jank", re.I)
    if any(name.search(p.name) for p in repo.files + repo.tests):
        return []
    return [RNFinding(
        "no-probe", "NOTE", "src/", 1,
        "no frame-rate harness found (a *perf*/*probe*/*fps* file); copy "
        "frame_probe.ts, or measure with the Perf Monitor or Flashlight",
        "project")]


CHECKS: List[Tuple[str, Callable[[RNRepo], List[RNFinding]]]] = [
    ("frame (Skia, Reanimated, rAF)", check_frame),
    ("render bodies", check_render),
    ("no-probe", check_probe),
]

CHECK_NAMES = ["text-layout-per-frame", "decode-per-frame", "blur-per-frame",
               "shader-per-frame", "save-layer-per-frame", "path-per-frame",
               "paint-per-frame", "color-parse-per-frame",
               "allocation-per-frame", "js-roundtrip-per-frame",
               "console-per-frame", "setstate-per-frame",
               "inline-prop-to-memo", "stylesheet-in-render",
               "heavy-in-render", "list-in-scrollview", "inline-render-item",
               "index-key", "no-probe"]


def run(root: Path) -> Tuple[RNRepo, List[RNFinding]]:
    repo = RNRepo(root)
    findings: List[RNFinding] = []
    for _, fn in CHECKS:
        findings += fn(repo)
    return repo, findings
