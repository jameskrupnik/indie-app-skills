#!/usr/bin/env python3
"""Check a Flutter, React Native or Expo app's store listing against the app.

The failure this catches is a sentence that reads perfectly and is false: a
listing naming a mode that was deleted, promising there are no adverts of a
kind the binary now serves, or counting twelve of something the code has six
of. Nothing in a compiler, a test suite or fastlane `deliver`/`supply`
compares the two, and the reviewer reads the listing before opening the app.

Assumed layout (fastlane's own): listing text in `metadata/` under any of
`fastlane/`, `ios/fastlane/` or `android/fastlane/`, one directory per locale
(`metadata/en-US/`, `metadata/android/en-US/`, `metadata/ios/en-US/` all
work), plus `review_information/notes.txt`. An Expo app's EAS Metadata file
(`store.config.json`, App Store only) is read too.

Flutter (pubspec.yaml): app code is every `.dart` file under a `lib/`
directory (so `lib/` and `packages/*/lib/` both count), minus generated files.
App strings also include `.arb`, slang `.i18n.json`/`.yaml` and text files
under `assets/`.

React Native / Expo (package.json naming react-native): app code is every
`.ts`, `.tsx`, `.js` and `.jsx` file outside node_modules, build output,
.expo, android/, ios/ and tests (so `src/`, expo-router's `app/` and a root
`App.tsx` all count). App strings also include `.json` under a directory named
i18n, locales, translations or lang, and text files under `assets/`.

Exit codes: 0 no FAIL (warnings allowed), 1 at least one FAIL, 2 nothing to
check (no listing files or no app sources).
"""

from __future__ import annotations

import argparse
import atexit
import bisect
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Tunables. Everything portfolio- or language-specific lives here.
# ---------------------------------------------------------------------------

# Capitalised words that do not name a thing in the app: grammar, platform and
# store vocabulary, and words a listing uses about itself. Skipped by the
# name check. Add per-app exceptions with --allow rather than growing this.
STOPWORDS = set("""
a an and the or but if so then than that this these those there here it its
you your yours we our us they them their he she his her no not nothing every
each both all any some more most less least first last next new old same
other another when where what who why how while after before with without
from into over under on off in out up down left right for to of at by is are
was were be been being do does did can could will will would should may might
must have has had get gets got go goes went also just only even still yes
app apps game games play player players playing screen screens tap taps hold
drag swipe press settings delete data privacy support review notes version
update updates build builds test tests tester testers feedback
ios ipados macos android apple google iphone ipad mac watch store play
wifi wi fi bluetooth icloud siri voiceover talkback center kit face touch id
dark light mode reduce motion dynamic type accessibility
monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october
november december
english spanish portuguese italian polish french german dutch japanese
korean chinese russian arabic hindi turkish swedish danish norwegian finnish
greek czech hungarian romanian ukrainian vietnamese thai indonesian malay
hebrew american british latin brazilian european canadian mexican
simplified traditional language languages localization localizations
""".split())
# **Language, region and month names are never screen names**, and a release
# note that lists the languages an update added is where they all appear at
# once. The localisations are declared to the store separately, so an app with
# no language picker never mentions "Polish" in its strings and never will.

# Files whose capitalisation is branding or title case, not a named feature.
# They are still checked for capability claims and counts.
NAME_CHECK_SKIPS = {"name.txt", "title.txt", "subtitle.txt", "keywords.txt",
                    "promotional_text.txt"}

# Words that turn an assertion into a denial when they precede it in the same
# clause: "no leaderboards", "never shows a rewarded video", "without ads".
NEGATORS = r"\b(no|not|never|without|nothing|zero|none|n't|free of)\b"

# Claims a listing makes about *classes of thing a store cares about*, and the
# code that has to exist (or not) for each to be true. Both directions are
# checked: "no rewarded video" while one ships is a false promise to a
# reviewer; a rewarded ad the listing never mentions is an undisclosed one.
#
# Each entry:
#   asserts    regexes over the lowercased listing that claim the capability.
#              A match preceded by a NEGATOR in the same clause is ignored.
#   denies     regexes that deny it *for the whole app*. Never mode-scoped:
#              "no second device" describes one mode of an app that may have
#              another. Matched per sentence.
#   code       regexes over comment-stripped Dart that mean it is implemented.
#   absent_if  regexes over the same code meaning the implementation is
#              unreachable in a release build (a false flag, test-only ids).
CAPABILITY_CLAIMS = [
    {
        "name": "rewarded video",
        # The last two catch disclosure wording that avoids the word
        # "rewarded" (Google Play bars *incentivising* ad views, so honest
        # copy often says "a video adds 3 coins" instead). A check that fires
        # on the honest version teaches you to ignore it.
        "asserts": [
            r"rewarded (video|ad)",
            # "Watch an ad to support us" is an opt-in interstitial, not a
            # reward, so a bare "watch an ad" needs a payoff after it.
            r"watch (a|an|one)? ?(short |optional )?(video|ad|advert)s?\b.{0,30}"
            r"\b(for|to (earn|get|unlock|double|claim|continue))\b",
            r"\ba video (adds|gives|doubles|unlocks|grants)",
        ],
        # Not "never needs a video": that denies the video is *required*, not
        # that it exists, and is usually written right beside a disclosure.
        "denies": [r"no rewarded (video|ad)", r"never .{0,20}rewarded"],
        "code": [r"\bRewarded(Interstitial)?Ad\b"],
        # React Native only (react-native-google-mobile-ads hooks).
        "code_rn": [r"\buseRewarded(Interstitial)?Ad\b"],
        # **A rewarded unit that exists only as Google's public sample id is
        # not shipped.** An app can carry the whole implementation with blank
        # production unit ids; the service reads blank as "no ads" and the
        # offer never appears. So: absent when rewarded ids appear in code and
        # every one is on Google's sample publisher (3940256099942544).
        # **Match the id, not the field name**: `androidRewarded:`,
        # `_rewardedAdUnitId =` and `prodRewardedAndroid =` are all common
        # shapes. If your ids come from --dart-define or a config file, this
        # finds no ids and treats the implementation as present.
        "absent_if": [
            r"(?si)\A(?=.*rewarded\w*\s*[:=]\s*['\"]ca-app-pub-3940256099942544)"
            r"(?!.*rewarded\w*\s*[:=]\s*['\"]ca-app-pub-(?!3940256099942544))"
        ],
    },
    {
        "name": "in-app purchase",
        "asserts": [r"in-app purchase", r"\bbuy (it|the app|coins|gems|premium)\b",
                    r"\bone(-time)? payment\b", r"\bsubscription\b"],
        "denies": [r"no in-app purchase", r"nothing to buy",
                   r"no subscription", r"free, with no .{0,20}purchase"],
        "code": [r"\bbuy(Non)?Consumable\b", r"\bqueryProductDetails\b",
                 r"\bpurchase(Package|StoreProduct|Product)\b"],
        # react-native-iap / expo-iap; RevenueCat is covered by `code`.
        "code_rn": [r"\brequestPurchase\b", r"\brequestSubscription\b",
                    r"\buseIAP\b"],
        # **A capability behind a compile-time false flag is not shipped.**
        # Match the gate, not the implementation. Adapt to your flag's name.
        "absent_if": [r"(?i)\b\w*(selling|purchases?|iap)\w*\s*=\s*false\b"],
    },
    {
        "name": "banner or interstitial advertising",
        "asserts": [r"\bbanners?\b", r"\binterstitial\b", r"\badvert(isement)?s?\b",
                    r"\bad-supported\b"],
        # Not a bare "ad-free": that is usually the name of a purchasable
        # upgrade in an app that very much has ads.
        "denies": [r"contains no ad", r"no ads at all", r"completely ad-free",
],
        "code": [r"\bBannerAd\b", r"\bInterstitialAd\b", r"\bNativeAd\b",
                 r"package:google_mobile_ads/"],
        "code_rn": [r"\buse(Interstitial|AppOpen)Ad\b",
                    r"['\"]react-native-google-mobile-ads['\"]"],
    },
    {
        "name": "accounts or sign-in",
        "asserts": [r"\bsign in\b", r"\bsign-in\b", r"\bcreate an account\b", r"\blog in\b"],
        "denies": [r"no account", r"no sign-?in", r"nothing to sign"],
        "code": [r"signInWith(?!Anonymously)", r"\bcreateUserWith", r"\bGoogleSignIn\b"],
        # @react-native-google-signin spells it GoogleSignin; expo-apple-authentication.
        "code_rn": [r"\bGoogleSignin\b", r"\bAppleAuthentication\.signInAsync\b"],
    },
    {
        "name": "online or multi-device play",
        "asserts": [r"\bonline\b", r"same wi-?fi", r"two devices", r"\bmatchmak",
                    r"\blobby\b", r"\bmultiplayer\b"],
        # Whole-app statements only; see the note on `denies` above. "No
        # matchmaking server" is deliberately absent: an app with nearby
        # two-device play writes exactly that.
        "denies": [r"no online play", r"\boffline only\b", r"never connects",
                   r"never goes online", r"no network connection of any kind",
                   r"there is no network", r"not (a )?multiplayer"],
        "code": [r"\bNearby\w*\b", r"\bSocket\b", r"\bWebSocketChannel\b",
                 r"\bGKMatch\w*\b"],
        "code_rn": [r"\bnew WebSocket\b", r"['\"]socket\.io-client['\"]"],
    },
    {
        "name": "leaderboards",
        "asserts": [r"\bleaderboard"],
        "denies": [r"no leaderboard", r"without .{0,20}leaderboard", r"leaderboard-free"],
        # Not a bare "leaderboard": that matches `Icons.leaderboard`. An icon
        # is not a capability; only an API that submits a score is.
        "code": [r"GameCenter", r"PlayGames", r"submitScore", r"\bLeaderboard\w*\("],
    },
]

GENERATED = (".g.dart", ".freezed.dart", ".config.dart", ".gr.dart",
             ".mocks.dart", ".gen.dart")
PRUNE = {"build", ".dart_tool", ".git", "Pods", "node_modules", ".gradle",
         ".symlinks", "ephemeral", ".fvm", "test", "integration_test",
         "test_driver", "fastlane", "docs"}
STRING_SUFFIXES = (".arb", ".i18n.json", ".i18n.yaml", ".i18n.yml")
# React Native / Expo.
JS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
JS_SKIP_SUFFIXES = (".d.ts", ".test.ts", ".test.tsx", ".test.js", ".test.jsx",
                    ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx")
JS_PRUNE = {"android", "ios", ".expo", "dist", "web-build", "coverage",
            "__tests__", "__mocks__", "e2e", "vendor"}
# Root config files: tooling, never app copy.
JS_ROOT_SKIP = re.compile(r"^(babel|metro|jest|eslint|prettier|tailwind|webpack"
                          r"|react-native|app|postcss)\.config\.|^\.")
STRING_DIRS = {"i18n", "locales", "locale", "translations", "lang", "langs"}
ASSET_TEXT_SUFFIXES = (".json", ".txt", ".md", ".yaml", ".yml", ".csv", ".arb")
SENTINELS = r"(none|unknown|unset|empty|invalid|undefined)\b"
MAX_ASSET_BYTES = 2_000_000
# Listing files that are not prose: URLs, contact details, credentials.
NOT_PROSE = re.compile(r"(_url|copyright|video|first_name|last_name|phone_number"
                       r"|email_address|demo_user|demo_password)\.txt$")
# "one" and "1" are left out: "move one piece at a time" is not a total.
NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}

# Display names for listing files that are not files of their own (fields
# of store.config.json, written to temp files).
LABELS: dict = {}

failures: list[str] = []
warnings: list[str] = []
passes: list[str] = []


def color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Finding files
# ---------------------------------------------------------------------------

def walk(app: Path, extra_prune: frozenset = frozenset()):
    for root, dirs, files in os.walk(app):
        dirs[:] = [d for d in dirs if d not in PRUNE and not d.startswith(".")
                   and not d.endswith("webdemo") and d not in extra_prune]
        for name in files:
            yield Path(root) / name


def detect_stack(app: Path) -> str:
    """"flutter", "react-native", "expo", or "" when neither is recognised.

    pubspec.yaml wins, so a Flutter app with a package.json for tooling stays
    Flutter.
    """
    if (app / "pubspec.yaml").is_file():
        return "flutter"
    try:
        pkg = json.loads((app / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    if "react-native" not in deps:
        return ""
    try:
        app_json = json.loads((app / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        app_json = {}
    if ("expo" in deps or "expo" in app_json or (app / "app.config.js").is_file()
            or (app / "app.config.ts").is_file()):
        return "expo"
    return "react-native"


def store_config_files(app: Path, locale: str, tmp: Path) -> dict[Path, str]:
    """EAS Metadata (store.config.json) text, as fastlane-named temp files.

    EAS Metadata covers the App Store only. Each field is written to a file
    named like fastlane's (subtitle.txt, keywords.txt...) so the name check
    skips the same fields it skips for fastlane. Returns {temp path: label}.
    """
    candidates = [app / "store.config.json"]
    try:
        eas = json.loads((app / "eas.json").read_text(encoding="utf-8"))
        for profile in eas.get("submit", {}).values():
            mp = (profile.get("ios") or {}).get("metadataPath")
            if mp and mp.endswith(".json"):
                candidates.append(app / mp)
    except (OSError, ValueError, AttributeError):
        pass
    fields = {"title": "title.txt", "subtitle": "subtitle.txt",
              "description": "description.txt", "keywords": "keywords.txt",
              "releaseNotes": "release_notes.txt",
              "promoText": "promotional_text.txt"}
    out: dict[Path, str] = {}
    for cfg in dict.fromkeys(candidates):
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        apple = data.get("apple") or {}
        info = (apple.get("info") or {}).get(locale) or {}
        texts = {fields[k]: v for k, v in info.items() if k in fields}
        notes = (apple.get("review") or {}).get("notes")
        if notes:
            texts["notes.txt"] = notes
        for name, value in texts.items():
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            if not isinstance(value, str) or not value.strip():
                continue
            key = "review.notes" if name == "notes.txt" else f"info.{locale}." + next(
                k for k, v in fields.items() if v == name)
            sub = tmp / str(len(out))
            sub.mkdir(parents=True, exist_ok=True)
            path = sub / name
            path.write_text(value, encoding="utf-8")
            out[path] = f"{cfg.relative_to(app).as_posix()}#apple.{key}"
    return out


def metadata_roots(app: Path) -> list[Path]:
    return [p for p in (app / "fastlane/metadata", app / "ios/fastlane/metadata",
                        app / "android/fastlane/metadata") if p.is_dir()]


def listing_files(app: Path, locale: str) -> list[Path]:
    """Every human-readable listing file for one locale, plus review notes.

    **The review notes are in scope and are usually the worst offender.** They
    are written once, read by exactly one person who can reject the app, and
    revisited by nobody, so they are where a deleted mode survives longest.
    Android changelogs and any `testflight/` "what to test" copy count too:
    both send a real person looking for named features.
    """
    found: list[Path] = []
    for root in metadata_roots(app):
        for path in sorted(root.rglob("*.txt")):
            parts = path.relative_to(root).parts[:-1]
            if NOT_PROSE.search(path.name):
                continue
            if "review_information" in parts:
                if path.name == "notes.txt":
                    found.append(path)
            elif locale in parts or "default" in parts or "testflight" in parts:
                found.append(path)
    return found


def js_files(app: Path) -> list[Path]:
    out = []
    for p in walk(app, frozenset(JS_PRUNE)):
        if not p.name.endswith(JS_SUFFIXES) or p.name.endswith(JS_SKIP_SUFFIXES):
            continue
        if p.parent == app and JS_ROOT_SKIP.search(p.name):
            continue
        out.append(p)
    return out


def strip_js_comments(source: str) -> str:
    """Remove // and /* */ comments from TS/JS, leaving strings intact.

    Same reason as the Dart version. Template literals are kept whole,
    `${}` included; a regex literal containing `//` can lose the rest of its
    line, which only ever hides code, never invents it.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        two = source[i:i + 2]
        c = source[i]
        if two == "//":
            j = source.find("\n", i)
            i = n if j < 0 else j
        elif two == "/*":
            j = source.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif c in "'\"`":
            j = i + 1
            while j < n and source[j] != c:
                if c != "`" and source[j] == "\n":
                    break
                j += 2 if source[j] == "\\" else 1
            j = min(n, j + 1)
            out.append(source[i:j])
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def dart_files(app: Path) -> list[Path]:
    return [p for p in walk(app)
            if p.suffix == ".dart" and "lib" in p.relative_to(app).parts
            and not p.name.endswith(GENERATED)]


def strip_dart_comments(source: str) -> str:
    """Remove // and /* */ comments, leaving string literals intact.

    **Capability checks must not see comments.** Well-documented code explains
    at length what the app deliberately does *not* do, so a search over
    comments finds a rewarded video in an app whose only mention of one is a
    note saying it has none. A regex cannot strip them safely: `'https://'` is
    not a comment, and an ad unit id inside a string is what a gate must see.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        two = source[i:i + 2]
        if two == "//":
            j = source.find("\n", i)
            i = n if j < 0 else j
        elif two == "/*":
            depth, i = 1, i + 2  # Dart block comments nest.
            while i < n and depth:
                if source.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif source.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
        elif c in "'\"":
            raw = i > 0 and source[i - 1] == "r"
            quote = source[i:i + 3] if source[i:i + 3] in ("'''", '"""') else c
            j = i + len(quote)
            while j < n and not source.startswith(quote, j):
                j += 2 if source[j] == "\\" and not raw else 1
            j = min(n, j + len(quote))
            out.append(source[i:j])
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def vocabulary(app: Path, sources: list[str], stack: str = "flutter") -> list[str]:
    """Every word the app says or names, lowercased, sorted for prefix lookup.

    Identifiers are split on camelCase, so `NearbyLobbyView` contributes
    "nearby", "lobby" and "view". Deliberately coarse: the question is only
    "does this word appear anywhere in the app", and false *positives* are
    what get a check ignored.
    """
    parts = list(sources)
    rn = stack in ("react-native", "expo")
    for path in walk(app, frozenset(JS_PRUNE) if rn else frozenset()):
        rel = path.relative_to(app).parts
        if rn and path.suffix == ".json" and STRING_DIRS & set(rel[:-1]) and \
                path.stat().st_size <= MAX_ASSET_BYTES:
            parts.append(read(path))
        elif path.name.endswith(STRING_SUFFIXES) or (
            "assets" in rel and path.name.endswith(ASSET_TEXT_SUFFIXES)
            and path.stat().st_size <= MAX_ASSET_BYTES
        ):
            parts.append(read(path))
    blob = "\n".join(parts)
    blob = re.sub(r"([a-z])([A-Z])", r"\1 \2", blob)
    return sorted({w.lower() for w in re.findall(r"[A-Za-z]+", blob)})


def known(word: str, vocab: list[str]) -> bool:
    """Exact, singular/plural, or as the start of a longer word (escort ->
    escorting). Never the other way round: a short vocab token must not
    vouch for a longer listing word."""
    w = word.lower()
    for stem in {w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith("es") else w}:
        i = bisect.bisect_left(vocab, stem)
        if i < len(vocab) and vocab[i].startswith(stem):
            return True
    return False


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

BULLET = re.compile(r"^\s*(?:[-*•·–—>]|\d+[.)])\s*")


def check_names(files: list[Path], vocab: list[str], allow: set[str]) -> None:
    """Named things in the listing that the app has never heard of.

    A capitalised word mid-sentence, or any "Quoted Thing", is almost always
    the name of a screen, mode or character. If the app's own strings and
    source never mention it, the listing is describing a different app,
    usually the one this was forked from.
    """
    unknown: dict[str, set[str]] = {}
    for path in files:
        if path.name in NAME_CHECK_SKIPS:
            continue
        for line in read(path).splitlines():
            line = BULLET.sub("", line)
            quoted = list(re.finditer(r'["“]([A-Za-z][A-Za-z \'’-]{1,28})["”]', line))
            candidates = {q.group(1) for q in quoted}
            for m in re.finditer(r"\b[A-Z][a-z]{2,}\b", line):
                if any(q.start() < m.start() < q.end() for q in quoted):
                    continue  # already judged as part of the quoted name
                before = line[:m.start()].rstrip(" \"'(“‘")
                if before and before[-1] not in ".!?:":
                    candidates.add(m.group(0))
            for raw in candidates:
                words = [w for w in re.split(r"[^A-Za-z]+", raw) if w]
                if any(w.lower() not in STOPWORDS and w.lower() not in allow
                       and not known(w, vocab) for w in words):
                    unknown.setdefault(raw.strip(), set()).add(
                        LABELS.get(path, path.name))

    if not unknown:
        passes.append("Every name in the listing exists somewhere in the app")
        return
    lines = [f"{len(unknown)} name(s) in the listing appear nowhere in the app:"]
    lines += [f"  {n!r}  ({', '.join(sorted(unknown[n]))})" for n in sorted(unknown)]
    lines += [
        "A screen, mode or character the app does not have is the most",
        "expensive thing a listing can contain: a reviewer told to try it will",
        "look for it, fail, and reject on 2.3 Accurate Metadata.",
        "(Not a feature name? Pass --allow WORD.)",
    ]
    fail("\n       ".join(lines))


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*•]|\d+[.)]))", text) if s.strip()]


def asserts_in(sentence: str, patterns: list[str]) -> bool:
    """True if a pattern matches and is not negated earlier in its clause.

    **A denial contains an assertion.** "No accounts, no sign-in, no
    leaderboards" matches "leaderboard", and without this every honest
    disclaimer reads as a claim.
    """
    for p in patterns:
        for m in re.finditer(p, sentence):
            clause = re.split(r"[,;:()—]|\band\b|\bbut\b", sentence[:m.start()])[-1]
            if not re.search(NEGATORS, clause):
                return True
    return False


def check_capabilities(files: list[Path], code: str, rn: bool = False) -> None:
    """Claims about adverts, purchases, accounts, online play, leaderboards.

    [rn] adds each claim's `code_rn` patterns (React Native library names) to
    its `code` patterns.
    """
    text = "\n\n".join(read(p) for p in files).lower().replace("’", "'")
    parts = sentences(text)

    clean = True
    for claim in CAPABILITY_CLAIMS:
        patterns = claim["code"] + (claim.get("code_rn", []) if rn else [])
        implemented = any(re.search(p, code) for p in patterns)
        gated = implemented and any(re.search(p, code) for p in claim.get("absent_if", []))
        present = implemented and not gated
        denied = any(re.search(p, s) for s in parts for p in claim["denies"])
        # **A denial wins over an assertion in the same sentence**, because it
        # usually contains one.
        asserted = any(
            asserts_in(s, claim["asserts"]) for s in parts
            if not any(re.search(p, s) for p in claim["denies"])
        )
        name = claim["name"]

        if denied and present:
            clean = False
            fail(
                f"The listing says the app has no {name}, and the code has one."
                "\n       This is a promise to a reviewer that the binary breaks."
                "\n       If the implementation is unreachable in a release build"
                "\n       (a false flag, test-only ad unit ids), add that gate to"
                "\n       this claim's `absent_if` and say so in the review notes:"
                "\n       a reviewer cannot see a blank unit id."
            )
        elif asserted and gated:
            clean = False
            fail(
                f"The listing describes {name}. The code implements it, but it"
                "\n       looks switched off in a release build (its `absent_if`"
                "\n       gate matched). Enable it before release, or take it out"
                "\n       of the copy."
            )
        elif asserted and not implemented:
            clean = False
            fail(
                f"The listing describes {name} and the code has none. Either it"
                "\n       was removed and the copy was not, or the copy came from"
                "\n       the app this one was forked from."
            )
        elif present and not asserted and not denied:
            clean = False
            warn(
                f"The app has {name} and no listing file mentions it."
                "\n       Undisclosed is not the same as absent; say so in the"
                "\n       review notes at least."
            )
    if clean:
        passes.append("Advertising, purchase, account and online claims match the code")


def top_level_items(body: str) -> list[str]:
    """Split a list or enum body on commas at bracket depth 0, stopping at
    the first depth-0 `;` (where an enhanced enum's members end)."""
    items, depth, start = [], 0, 0
    for i, c in enumerate(body):
        if c in "([{<":
            depth += 1
        elif c in ")]}>":
            depth -= 1
        elif c == ";" and depth == 0:
            body = body[:i]
            break
        elif c == "," and depth == 0:
            items.append(body[start:i])
            start = i + 1
    items.append(body[start:])
    return [s.strip() for s in items if s.strip()]


def matching_close(source: str, open_index: int) -> int:
    pairs = {"{": "}", "[": "]"}
    opener, closer = source[open_index], pairs[source[open_index]]
    depth = 0
    for i in range(open_index, len(source)):
        if source[i] == opener:
            depth += 1
        elif source[i] == closer:
            depth -= 1
            if depth == 0:
                return i
    return len(source)


def collection_counts(sources: list[str]) -> dict[str, int]:
    """Named lists and enums in the code, keyed by lowercased name.

    - `enum Theme { a, b, c }` -> "theme": 3 (members only, not methods).
    - `static const all = <Level>[...]` -> keyed on the *enclosing class*.
    - `const themes = <ThemeSpec>[...]` / `const List<ThemeSpec> themes = [`
      -> "themes", counted by `ThemeSpec(` constructor calls, because list
      items are multi-line calls with their own commas.

    `const` only: a `final` list is usually built in a loop, so its literal
    says nothing about its length. Sentinel enum members (`none`, `unknown`)
    are not counted: "three medals" is right for `{none, bronze, silver, gold}`.
    """
    counts: dict[str, int] = {}
    for source in sources:
        for m in re.finditer(r"\benum\s+(\w+)[^{;]*\{", source):
            body = source[m.end():matching_close(source, m.end() - 1)]
            members = [s for s in top_level_items(body)
                       if re.match(r"(@\w+(\([^)]*\))?\s*)*[A-Za-z_]\w*\s*(\(|$)", s, re.S)
                       and not re.match(SENTINELS, s)]
            if members:
                counts.setdefault(m.group(1).lower(), len(members))

        classes = [(m.group(1), m.end() - 1)
                   for m in re.finditer(r"\bclass\s+(\w+)[^{;]*\{", source)]
        for m in re.finditer(
            r"(?:static\s+)?const\s+(?:List<(\w+)>\s+)?(\w+)\s*=\s*"
            r"(?:const\s*)?(?:<(\w+)>)?\[", source,
        ):
            element, name = m.group(1) or m.group(3), m.group(2)
            if not element:
                continue
            body = source[m.end():matching_close(source, m.end() - 1)]
            found = len(re.findall(rf"\b{re.escape(element)}(\.\w+)?\s*\(", body))
            if not found:
                continue
            if name == "all":
                owners = [c for c, start in classes if start < m.start()]
                if not owners:
                    continue
                key = owners[-1]
            else:
                key = re.sub(r"^(_|k(?=[A-Z]))", "", name)
            counts.setdefault(key.lower(), found)
    return counts


def js_collection_counts(sources: list[str]) -> dict[str, int]:
    """TS/JS analogue of collection_counts.

    - `enum Theme { A, B = 'b' }` -> "theme": 2.
    - `const THEMES = [...]`, `const themes: Theme[] = [...]`,
      `export const themes = [...] as const` -> "themes", counted as the
      array's top-level items (object literals have their own commas, so
      split at depth 0).

    `const` only, for the same reason as the Dart version.
    """
    counts: dict[str, int] = {}
    for source in sources:
        for m in re.finditer(r"\benum\s+(\w+)\s*\{", source):
            body = source[m.end():matching_close(source, m.end() - 1)]
            members = [x for x in top_level_items(body)
                       if re.match(r"[A-Za-z_]\w*\s*(=|$)", x, re.S)
                       and not re.match(SENTINELS, x, re.I)]
            if members:
                counts.setdefault(m.group(1).lower(), len(members))
        for m in re.finditer(
            r"\bconst\s+(\w+)\s*(?::\s*[\w<>\[\]., |]+?)?\s*=\s*\[", source):
            body = source[m.end():matching_close(source, m.end() - 1)]
            items = top_level_items(body)
            if len(items) < 2:
                continue
            name = re.sub(r"^_+", "", m.group(1))
            if name.isupper():
                name = name.replace("_", "")
            counts.setdefault(name.lower(), len(items))
    return counts


def check_counts(files: list[Path], sources: list[str], rn: bool = False) -> None:
    """ "Twelve tables", "six themes" against the real lists and enums.

    Advisory rather than a failure: mapping a noun to a Dart list is a guess,
    and a guess that fails a build gets the check skipped. It is here because
    a stale count survives every test and drifts whenever content is added.
    """
    counts = js_collection_counts(sources) if rn else collection_counts(sources)
    if not counts:
        return
    text = "\n".join(read(p) for p in files)
    checked = False
    number = (r"\b([2-9]|[1-9]\d{1,2}|" + "|".join(NUMBER_WORDS)
              + r")\s+([a-z]{3,})(?:[ -]([a-z]{3,}))?\b")

    def stem(word: str) -> str:
        word = re.sub(r"our", "or", word)  # colour -> color
        return word[:-1] if word.endswith("s") else word

    seen: set[tuple[str, str]] = set()
    for match in re.finditer(number, text, re.I):
        raw, noun, following = (g.lower() if g else "" for g in match.groups())
        claimed = NUMBER_WORDS.get(raw) or int(raw)
        # "six hull colours" is about `HullColor`, not `hulls`: try the
        # two-word noun first and only fall back to the single word.
        candidates = [(stem(noun + following), f"{raw} {noun} {following}")] if following else []
        candidates.append((stem(noun), f"{raw} {noun}"))
        for key, phrase in candidates:
            # **Exact, after stripping one plural on each side.** Prefix
            # matching related "tables" to `TableSpec`, `TableTheme` and
            # `TableEnd`: three warnings about one sentence, two of them
            # nonsense.
            hits = [(k, n) for k, n in counts.items() if stem(k) == key]
            if not hits:
                continue
            checked = True
            for kind, actual in hits:
                if actual != claimed and (phrase, kind) not in seen:
                    seen.add((phrase, kind))
                    warn(f'The listing says "{phrase}" and the code has'
                         f"\n       {actual} ({kind}). One of them is stale.")
            break
    if checked:
        passes.append("Counted claims in the listing were checked against the code")


# ---------------------------------------------------------------------------

def fail(msg: str) -> None:
    failures.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", default=".",
                        help="Flutter, React Native or Expo app directory (default: cwd)")
    parser.add_argument("--locale", default="en-US",
                        help="listing locale directory to check (default: en-US)")
    parser.add_argument("--listing", action="append", default=[], metavar="FILE",
                        help="extra listing file to check, e.g. copy kept outside "
                             "fastlane; repeatable")
    parser.add_argument("--allow", action="append", default=[], metavar="WORD",
                        help="capitalised word that is not a feature name "
                             "(a brand, a place); repeatable")
    parser.add_argument("--json", action="store_true",
                        help="print only a JSON object {failures, warnings, passes}")
    args = parser.parse_args()

    app = Path(args.app).resolve()
    stack = detect_stack(app)
    rn = stack in ("react-native", "expo")
    files = listing_files(app, args.locale) + [Path(p) for p in args.listing]
    labels: dict[Path, str] = {}
    if rn:
        tmp = Path(tempfile.mkdtemp(prefix="listing-accuracy-"))
        atexit.register(shutil.rmtree, tmp, True)
        labels = store_config_files(app, args.locale, tmp)
        LABELS.update(labels)
        files += list(labels)
    files = [p for p in files if p.is_file()]

    def stop(message: str) -> int:
        if args.json:
            print(json.dumps({"error": message, "failures": [], "warnings": [],
                              "passes": []}, indent=2))
        else:
            print(message, file=sys.stderr)
        return 2

    if not files:
        return stop(f"No {args.locale} listing files under {app}/"
                    "{fastlane,ios/fastlane,android/fastlane}/metadata"
                    + (" or store.config.json" if rn else "") +
                    " and no --listing given. Nothing was checked.")
    if rn:
        paths = js_files(app)
        if not paths:
            return stop(f"No TypeScript or JavaScript sources in {app}. "
                        "Is this a React Native app?")
    else:
        paths = dart_files(app)
        if not paths:
            return stop(f"No Dart sources under a lib/ directory in {app}. "
                        "Is this a Flutter app?")
    sources = [read(p) for p in paths]
    strip = strip_js_comments if rn else strip_dart_comments
    stripped = [strip(s) for s in sources]

    check_names(files, vocabulary(app, sources, stack), {w.lower() for w in args.allow})
    check_capabilities(files, "\n".join(stripped), rn)
    check_counts(files, stripped, rn)

    if args.json:
        out = {"app": str(app), "files": [labels.get(p, str(p)) for p in files],
               "failures": failures, "warnings": warnings, "passes": passes}
        if stack != "flutter":
            out["stack"] = stack or "unknown"
        print(json.dumps(out, indent=2))
        return 1 if failures else 0

    print(f"\nListing accuracy: {app.name} ({len(files)} listing file(s), {args.locale})\n")
    for message in passes:
        print(f"  {color('32', 'ok')} {message}")
    for message in warnings:
        print(f"\n  {color('33', 'WARN')} {message}")
    for message in failures:
        print(f"\n  {color('31', 'FAIL')} {message}")
    if failures:
        print(f"\n{len(failures)} check(s) failed.\n")
        return 1
    print("\nListing and app agree." + (" (warnings above)" if warnings else "") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
