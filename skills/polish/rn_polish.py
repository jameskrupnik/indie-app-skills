"""React Native / Expo checks for check_polish.py.

The same faults as the Flutter checks, in React Native's vocabulary: a
number chosen against one device or one text size, and a setting that
silences nothing.

  icon-label          a Pressable/Touchable with no accessible name
  a11y-role           a Pressable/Touchable with no accessibilityRole/role
  tap-target          a pressable sized under 44pt with no hitSlop
  font-scaling        allowFontScaling={false} or a maxFontSizeMultiplier < 1.5
  fixed-height-text   a fixed height around Text, which clips at large text
  reduce-motion       Animated.loop / ReduceMotion.Never / frame-driven motion
                      in a file that never asks about Reduce Motion
  haptics-switch      Vibration or expo-haptics with no in-app switch
  safe-area           no safe-area handling anywhere, or RN's deprecated one
  dimensions-at-load  Dimensions.get at module scope (stale after rotation)
  image-alt           an Image with no alt / accessibilityLabel
  content-cap         a maxWidth no tablet reaches in portrait
  tablet-layout       supportsTablet with no code that reads the window size

Everything is advisory, and a lead to check: a shape can be deliberate.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import rn_source as rs

NARROWEST_TABLET = 744
MIN_TAP = 44  # Apple HIG points; Material asks for 48dp
PRESSABLES = ("Pressable", "TouchableOpacity", "TouchableHighlight",
              "TouchableWithoutFeedback", "TouchableNativeFeedback")
LABEL_PROPS = ("accessibilityLabel", "aria-label", "accessibilityLabelledBy",
               "aria-labelledby")
HIDDEN_PROPS = ("accessibilityElementsHidden", "importantForAccessibility",
                "aria-hidden")
# Children that carry no words of their own.
SILENT_CHILD = re.compile(
    r"<(?!/)(?!(?:View|Image|Svg|Path|Circle|Rect|G|Animated\.View|"
    r"\w*Icons?|MaterialIcons|MaterialCommunityIcons|Ionicons|Feather|"
    r"FontAwesome\w*|AntDesign|Entypo|EvilIcons|Foundation|Octicons|"
    r"SimpleLineIcons|Zocial|LinearGradient|Fragment)\b)[A-Za-z]")


@dataclass
class RNFinding:
    check: str
    level: str
    path: str
    line: int
    message: str


class RNRepo:
    def __init__(self, root: Path):
        self.root = root
        self.files = rs.js_files(root)
        self._raw: Dict[Path, str] = {}
        self._text: Dict[Path, str] = {}

    def raw(self, p: Path) -> str:
        if p not in self._raw:
            self._raw[p] = rs.read(p)
        return self._raw[p]

    def text(self, p: Path) -> str:
        if p not in self._text:
            self._text[p] = rs.strip_js(self.raw(p))
        return self._text[p]

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)


def _find(repo: RNRepo, p: Path, pos: int, check: str, level: str,
          message: str) -> RNFinding:
    return RNFinding(check, level, repo.rel(p),
                     rs.line_of(repo.text(p), pos), message)


def check_pressables(repo: RNRepo) -> List[RNFinding]:
    """Accessible name, role and size of every Pressable/Touchable."""
    out: List[RNFinding] = []
    for p in repo.files:
        text = repo.text(p)
        styles = rs.Styles.of(text)
        for el in rs.elements(text, PRESSABLES):
            attrs = text[el.attrs[0]:el.attrs[1]]
            spread = bool(re.search(r"\{\s*\.\.\.", attrs))
            hidden = re.search(r"\baccessible\s*=\s*\{\s*false\s*\}", attrs) \
                or rs.has_prop(attrs, *HIDDEN_PROPS)
            if hidden or spread:
                continue
            kids = text[el.children[0]:el.children[1]] if el.children else ""
            worded = "<Text" in kids or bool(SILENT_CHILD.search(kids)) or \
                bool(re.search(r">\s*\{[^}]*\}\s*<|^\s*\{[^}]*\}\s*$", kids))
            if not rs.has_prop(attrs, *LABEL_PROPS) and not worded:
                out.append(_find(
                    repo, p, el.start, "icon-label", "WARN",
                    f"<{el.name}> with no accessibilityLabel and no Text "
                    "inside: a screen reader announces nothing useful"))
            if not rs.has_prop(attrs, "accessibilityRole", "role"):
                out.append(_find(
                    repo, p, el.start, "a11y-role", "NOTE",
                    f"<{el.name}> with no accessibilityRole (or role): "
                    "VoiceOver and TalkBack will not say \"button\""))
            if rs.has_prop(attrs, "hitSlop"):
                continue
            style = styles.resolve(rs.prop_value(attrs, "style"))
            dims = [v for v in (rs.number_prop(style, "width"),
                                rs.number_prop(style, "height"))
                    if v is not None]
            mins = [v for v in (rs.number_prop(style, "minWidth"),
                                rs.number_prop(style, "minHeight"))
                    if v is not None]
            small = [v for v in dims if v < MIN_TAP]
            if small and not any(v >= MIN_TAP for v in mins):
                out.append(_find(
                    repo, p, el.start, "tap-target", "WARN",
                    f"<{el.name}> is {min(small):g}pt on a side with no "
                    f"hitSlop; Apple asks for {MIN_TAP}pt and Material for "
                    "48dp. Add hitSlop or grow the box"))
    return out


def check_font_scaling(repo: RNRepo) -> List[RNFinding]:
    """Text that refuses to grow with the system text size."""
    out: List[RNFinding] = []
    for p in repo.files:
        text = repo.text(p)
        for m in re.finditer(r"\ballowFontScaling\s*(?:=\s*\{\s*|:\s*)false\b",
                             text):
            out.append(_find(
                repo, p, m.start(), "font-scaling", "WARN",
                "allowFontScaling is false: this text ignores the system text "
                "size. Cap it with maxFontSizeMultiplier instead, and only "
                "where the layout truly cannot grow"))
        for m in re.finditer(r"\bmaxFontSizeMultiplier\s*(?:=\s*\{\s*|:\s*)"
                             r"([0-9]+(?:\.[0-9]+)?)\b", text):
            v = float(m.group(1))
            if 1 <= v < 1.5:
                out.append(_find(
                    repo, p, m.start(), "font-scaling", "WARN",
                    f"maxFontSizeMultiplier {v:g} stops text growing almost "
                    "at once; iOS Dynamic Type reaches about 3.1x, and 1.35x "
                    "is one notch up the slider"))
    return out


def check_fixed_height_text(repo: RNRepo) -> List[RNFinding]:
    """A literal height around Text: fine at 1.0x, clipped at 1.35x."""
    out: List[RNFinding] = []
    names = ("View", "Text") + PRESSABLES
    for p in repo.files:
        text = repo.text(p)
        styles = rs.Styles.of(text)
        for el in rs.elements(text, names):
            attrs = text[el.attrs[0]:el.attrs[1]]
            style = styles.resolve(rs.prop_value(attrs, "style"))
            h = rs.number_prop(style, "height")
            if h is None or rs.number_prop(style, "minHeight") is not None:
                continue
            kids = text[el.children[0]:el.children[1]] if el.children else ""
            holds_text = el.name == "Text" or re.search(r"<Text(?![\w.])", kids)
            if not holds_text or "adjustsFontSizeToFit" in kids + attrs:
                continue
            out.append(_find(
                repo, p, el.start, "fixed-height-text", "WARN",
                f"height: {h:g} around text; it fits at 1.0x and clips when "
                "the system text size goes up. Use minHeight, or padding"))
    return out


def reduce_motion_names(repo: RNRepo) -> List[str]:
    """Hooks/helpers that wrap the Reduce Motion APIs, so a file calling
    `useMotionOk()` counts as honouring it."""
    names = set()
    api = re.compile(r"useReducedMotion|isReduceMotionEnabled|"
                     r"reduceMotionChanged")
    for p in repo.files:
        text = repo.text(p)
        if not api.search(text):
            continue
        for f in rs.functions(text):
            if f.name and len(f.name) >= 4 and api.search(
                    text[f.body[0]:f.body[1]]):
                names.add(f.name)
    return sorted(names)


def check_reduce_motion(repo: RNRepo) -> List[RNFinding]:
    """Reanimated animations honour Reduce Motion by default
    (ReduceMotion.System); React Native's own Animated, an explicit
    ReduceMotion.Never, and motion driven by a frame callback do not."""
    out: List[RNFinding] = []
    helpers = reduce_motion_names(repo)
    honours = re.compile(r"useReducedMotion|isReduceMotionEnabled|"
                         r"reduceMotionChanged|ReduceMotion\.System|"
                         r"\breduced?Motion\b|\breduced?_motion\b" +
                         "".join("|\\b%s\\b" % re.escape(h) for h in helpers))
    for p in repo.files:
        text = repo.text(p)
        loop = re.search(r"\bAnimated\.loop\s*\(", text)
        never = re.search(r"\bReduceMotion\.Never\b", text)
        frame = re.search(r"(?<![\w.$])(?:useFrameCallback|useClock)\s*\(", text)
        # ReduceMotion.Never itself contains "ReduceMotion", so judge it on
        # the text with those occurrences removed.
        rest = re.sub(r"(?:\breduceMotion\s*:\s*)?\bReduceMotion\.Never\b",
                      "", text)
        if honours.search(rest):
            continue
        if loop:
            out.append(_find(
                repo, p, loop.start(), "reduce-motion", "WARN",
                "Animated.loop in a file that never checks Reduce Motion; "
                "React Native's Animated does not honour it on its own. Use "
                "AccessibilityInfo.isReduceMotionEnabled()"))
        if never:
            out.append(_find(
                repo, p, never.start(), "reduce-motion", "WARN",
                "ReduceMotion.Never opts this animation out of the system "
                "Reduce Motion setting; keep it only for motion that carries "
                "meaning"))
        if frame and not loop and not never:
            out.append(_find(
                repo, p, frame.start(), "reduce-motion", "NOTE",
                "motion driven by a frame callback is not covered by "
                "Reanimated's ReduceMotion default; if it is ambient, gate it "
                "on useReducedMotion()"))
    return out


def check_haptics_switch(repo: RNRepo) -> List[RNFinding]:
    """Vibration a user cannot turn off.

    React Native's `Vibration` calls the vibrator directly. expo-haptics is
    skipped by iOS when system haptics are off, but on Android
    impactAsync/notificationAsync are simulated with the Vibrator API.
    """
    plugin: Optional[Tuple[Path, int]] = None
    gentle: Optional[Tuple[Path, int]] = None
    has_switch = False
    for p in repo.files:
        text = repo.text(p)
        m = re.search(r"\bVibration\.vibrate\s*\(|\bHaptics\.(?:impact|"
                      r"notification)Async\s*\(", text)
        if m and plugin is None:
            plugin = (p, m.start())
        g = re.search(r"\bHaptics\.(?:selection|performAndroidHaptics)Async"
                      r"\s*\(", text)
        if g and gentle is None:
            gentle = (p, g.start())
        if re.search(r"haptic|vibrat", text, re.I) and (
                re.search(r"<Switch\b|\bSwitch\b|\bCheckbox\b", text) or
                re.search(r"(?i:set\w*(?:haptic|vibrat))|"
                          r"(?i:haptic|vibrat)\w*(?:Enabled|On)\b", text)):
            has_switch = True
    if has_switch:
        return []
    if plugin:
        return [_find(repo, plugin[0], plugin[1], "haptics-switch", "WARN",
                      "vibration with no in-app switch: Vibration.vibrate and "
                      "expo-haptics impact/notification (simulated with "
                      "Android's Vibrator) are not silenced by a system "
                      "haptics setting on every platform")]
    if gentle:
        return [_find(repo, gentle[0], gentle[1], "haptics-switch", "NOTE",
                      "haptics with no in-app switch; fine unless the app "
                      "buzzes often, and a game that does should offer one")]
    return []


def check_safe_area(repo: RNRepo) -> List[RNFinding]:
    out: List[RNFinding] = []
    uses = False
    for p in repo.files:
        raw, text = repo.raw(p), repo.text(p)
        if re.search(r"\b(?:SafeAreaProvider|SafeAreaView|useSafeAreaInsets|"
                     r"useSafeAreaFrame|SafeAreaInsetsContext|"
                     r"withSafeAreaInsets|initialWindowMetrics)\b", text):
            uses = True
        m = re.search(r"import\s*\{[^}]*\bSafeAreaView\b[^}]*\}\s*from\s*"
                      r"['\"]react-native['\"]", raw)
        if m:
            out.append(_find(
                repo, p, m.start(), "safe-area", "WARN",
                "SafeAreaView from react-native is deprecated and iOS-only; "
                "use react-native-safe-area-context, which also pads Android "
                "cutouts and gesture bars"))
    if not uses and repo.files and any(
            re.search(r"<View\b", repo.text(p)) for p in repo.files):
        out.append(RNFinding(
            "safe-area", "WARN", "app/", 1,
            "no safe-area handling anywhere (SafeAreaView, useSafeAreaInsets); "
            "content can sit under the notch, the Dynamic Island or the "
            "home indicator unless every screen has a navigator header"))
    return out


def check_dimensions(repo: RNRepo) -> List[RNFinding]:
    out: List[RNFinding] = []
    for p in repo.files:
        text = repo.text(p)
        funcs = None
        for m in re.finditer(r"\bDimensions\.get\s*\(", text):
            funcs = funcs if funcs is not None else rs.functions(text)
            if rs.innermost(funcs, m.start()) is None:
                out.append(_find(
                    repo, p, m.start(), "dimensions-at-load", "WARN",
                    "Dimensions.get at module scope is read once, at load: "
                    "rotation, split view and foldables leave it stale. Use "
                    "useWindowDimensions() in the component"))
    return out


def check_image_alt(repo: RNRepo) -> List[RNFinding]:
    out: List[RNFinding] = []
    for p in repo.files:
        text = repo.text(p)
        for el in rs.elements(text, ("Image",)):
            attrs = text[el.attrs[0]:el.attrs[1]]
            if rs.has_prop(attrs, "alt", *LABEL_PROPS, *HIDDEN_PROPS,
                           "accessible"):
                continue
            out.append(_find(
                repo, p, el.start, "image-alt", "NOTE",
                "an Image with no alt or accessibilityLabel; a screen reader "
                "skips it. Fine if decorative, a gap if it carries meaning"))
    return out


def check_content_cap(repo: RNRepo) -> List[RNFinding]:
    caps = []
    for p in repo.files:
        text = repo.text(p)
        for m in re.finditer(r"\bmaxWidth\s*:\s*([0-9]+(?:\.[0-9]+)?)\b",
                             text):
            caps.append((p, m.start(), float(m.group(1))))
    big = [c for c in caps if c[2] >= 400]  # ignore chip/badge caps
    if not big or any(v <= NARROWEST_TABLET for _, _, v in big):
        return []
    p, pos, v = min(big, key=lambda c: c[2])
    where = ("any iPad in portrait (largest is 1024pt)" if v > 1024 else
             f"the smallest iPad in portrait ({NARROWEST_TABLET}pt)")
    return [_find(repo, p, pos, "content-cap",
                  "FAIL" if v > 1024 else "WARN",
                  f"the narrowest content cap is {v:g}, which never engages "
                  f"on {where}: lists run edge to edge")]


def check_tablet_layout(repo: RNRepo) -> List[RNFinding]:
    """Expo's ios.supportsTablet, with nothing that reads the window."""
    cfg = repo.root / "app.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    expo = data.get("expo", data) if isinstance(data, dict) else {}
    if not (expo.get("ios") or {}).get("supportsTablet"):
        return []
    reads = re.compile(r"\buseWindowDimensions\b|\bonLayout\b|"
                       r"\bDimensions\.addEventListener\b|\buseSafeAreaFrame\b")
    for p in repo.files:
        text = repo.text(p)
        if reads.search(text):
            return []
        funcs = rs.functions(text)
        if any(rs.innermost(funcs, m.start()) for m in
               re.finditer(r"\bDimensions\.get\s*\(", text)):
            return []  # read at render time; module-scope reads are stale
    return [RNFinding(
        "tablet-layout", "WARN", "app.json", 1,
        "ios.supportsTablet is true and no code reads the window size at "
        "render time (useWindowDimensions, onLayout): every iPad gets the phone layout "
        "stretched")]


CHECKS: List[Tuple[str, Callable[[RNRepo], List[RNFinding]]]] = [
    ("icon-label / a11y-role / tap-target", check_pressables),
    ("font-scaling", check_font_scaling),
    ("fixed-height-text", check_fixed_height_text),
    ("reduce-motion", check_reduce_motion),
    ("haptics-switch", check_haptics_switch),
    ("safe-area", check_safe_area),
    ("dimensions-at-load", check_dimensions),
    ("image-alt", check_image_alt),
    ("content-cap", check_content_cap),
    ("tablet-layout", check_tablet_layout),
]

CHECK_NAMES = ["icon-label", "a11y-role", "tap-target", "font-scaling",
               "fixed-height-text", "reduce-motion", "haptics-switch",
               "safe-area", "dimensions-at-load", "image-alt", "content-cap",
               "tablet-layout"]


def run(root: Path) -> Tuple[RNRepo, List[RNFinding]]:
    repo = RNRepo(root)
    return repo, [f for _, fn in CHECKS for f in fn(repo)]
