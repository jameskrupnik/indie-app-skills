#!/usr/bin/env python3
"""Check an app store listing against the app it describes.

The failure this catches is a sentence that reads perfectly and is false: a
listing naming a mode that was deleted, promising there are no adverts of a
kind the binary now serves, or counting twelve of something the code has six
of. Nothing in a compiler, a test suite or `deliver` compares the two, and the
reviewer reads the listing before they open the app.

Exits non-zero on any FAIL. WARNs never fail the run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Words that are capitalised for grammar rather than because they name a thing.
# Anything here is skipped by the proper-noun check.
STOPWORDS = {
    "a", "an", "and", "the", "or", "but", "if", "so", "then", "than", "that",
    "this", "these", "those", "there", "here", "it", "its", "you", "your",
    "yours", "we", "our", "us", "they", "them", "their", "he", "she", "his",
    "her", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "no", "not", "nothing", "every",
    "each", "both", "all", "any", "some", "more", "most", "less", "least",
    "first", "last", "next", "new", "old", "same", "other", "another",
    "play", "player", "players", "playing", "played", "game", "games", "app",
    "apps", "screen", "screens", "tap", "hold", "drag", "swipe", "press",
    "wifi", "ios", "android", "apple", "google", "iphone", "ipad", "store",
    "when", "where", "what", "who", "why", "how", "while", "after", "before",
    "with", "without", "from", "into", "over", "under", "on", "off", "in",
    "out", "up", "down", "left", "right", "for", "to", "of", "at", "by",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "can", "could", "will", "would", "should", "may", "might", "must",
    "have", "has", "had", "get", "gets", "got", "go", "goes", "went",
    "settings", "delete", "data", "privacy", "support", "review", "notes",
    "also", "present", "ads", "ad", "coins", "coin", "sound", "sounds",
    "pause", "paused", "mute", "music", "score", "scores", "best", "target",
    "targets", "level", "levels", "mode", "modes", "table", "tables",
    # **Language names are never screen names, and a release note listing the
    # languages an update added is the one place they all appear at once.**
    # Taco Rain's "Spanish, Latin American Spanish, Portuguese, Italian and
    # Polish join the seven that were already here" failed this check five
    # times over. A reviewer will not go hunting the UI for a button called
    # "Polish", and the localisations are declared to the store separately, so
    # there is nothing here for the proper-noun check to protect.
    # **Month names, for the same reason.** Review notes date things - "the
    # build reviewed was uploaded on 29 August" - and a reviewer is not going
    # to search the UI for a screen called "August".
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "english", "spanish", "portuguese", "italian", "polish", "french",
    "german", "dutch", "japanese", "korean", "chinese", "russian", "arabic",
    "hindi", "turkish", "swedish", "danish", "norwegian", "finnish", "greek",
    "czech", "hungarian", "romanian", "ukrainian", "vietnamese", "thai",
    "indonesian", "malay", "hebrew", "american", "british", "latin",
    # The regional qualifiers belong here for the same reason the languages
    # do, and this list had three of them and not the fourth: "Brazilian
    # Portuguese" failed every run against an app whose five locales are
    # declared to the store and which deliberately has no language picker, so
    # the word appears nowhere in its strings and never will.
    "brazilian",
    "languages", "language", "localization", "localizations",
}

# Claims a listing makes about *classes of thing a store cares about*, and the
# code that has to exist (or not) for each to be true.
#
# The direction matters and both are checked. "No rewarded video" while a
# rewarded ad ships is a false promise to a reviewer; a rewarded ad that the
# listing never mentions is an undisclosed one. Both have cost real
# rejections.
CAPABILITY_CLAIMS = [
    {
        "name": "rewarded video",
        # **The last two asserts are the house disclosure wording, and they
        # were added because rewriting the copy hid a real disclosure.** These
        # listings used to say "watch an optional video for 3-9 bonus coins";
        # Google's behavioral policy bars an app that "promises payment or
        # incentives to users who click on or view ads", so the offer was
        # rephrased as disclosure - "a video adds 3-9 bonus coins to a task you
        # have already completed". The feature is disclosed just as plainly and
        # the words "rewarded video" are gone, so the old patterns reported
        # four honestly-documented apps as hiding one. A check that fires on
        # the honest version teaches you to ignore it.
        "asserts": [
            r"rewarded (video|ad)",
            r"watch (a|an|one)? ?(short )?(video|ad|advert)",
            r"a video adds",
            r"short videos",
        ],
        # Do **not** add "never needs a video" here. It denies that the video
        # is *required*, not that it exists, and the app says it in the same
        # breath as disclosing the bonus. The existing patterns both require
        # the word "rewarded" nearby, which is what keeps them apart.
        "denies": [r"no rewarded (video|ad)", r"never .{0,20}rewarded"],
        "code": [r"\bRewarded(Interstitial)?Ad\b"],
        # **A rewarded unit that exists only as Google's public test id is not
        # shipped.** Asteroid Duel carries the whole hangar implementation and
        # ships with `androidRewarded`/`iosRewarded` empty in the production
        # AdUnits, because no rewarded unit has been created in AdMob; the
        # service reads an empty id as "no ads", never loads, and the offer
        # never appears. Its listing's "no rewarded video" is true. Matching
        # `RewardedAd` alone called that app a liar.
        #
        # So the gate is the *production* unit id, not the class: absent when
        # no rewarded id anywhere is outside Google's sample publisher
        # (3940256099942544), which is debug-only by definition. Written as a
        # whole-blob negative lookahead because this has to assert that
        # something is missing, which a plain search cannot do.
        #
        # **Match the id, not the field name.** The first version of this gate
        # looked for `Rewarded:` and flipped three apps that do ship one into
        # the opposite error, because this portfolio holds three unrelated
        # shapes for the same constant: `androidRewarded:` in an `AdUnits`
        # class, `_androidRewardedAdUnitId =` on an `AdService`, and
        # `_prodRewardedAndroid =` on an `AdUnitIds`. Any identifier containing "rewarded" assigned a non-test
        # `ca-app-pub-` id covers all three, and the `\s*` spans the newline
        # two of them wrap on.
        "absent_if": [
            r"\A(?!(?si:.*rewarded\w*\s*[:=]\s*'ca-app-pub-(?!3940256099942544)))"
        ],
    },
    {
        "name": "in-app purchase",
        "asserts": [r"in-app purchase(?!s? of any kind)", r"\bbuy (it|the app|coins)\b", r"one payment"],
        "denies": [r"no in-app purchase", r"nothing to buy", r"there is no in-app purchase"],
        "code": [r"\bbuyNonConsumable\b", r"\bqueryProductDetails\b"],
        # **A capability behind a compile-time false flag is not shipped.**
        # Several of these apps carry a whole purchase implementation that
        # nothing can reach because `selling` is false — no buy tile, no
        # Restore, no StoreKit call — and for those the listing's "no in-app
        # purchases" is true. Matching the implementation alone reported every
        # one of them as a liar, which is the fastest way to teach somebody to
        # ignore this script.
        "absent_if": [r"selling\s*=\s*false"],
    },
    {
        "name": "banner or interstitial advertising",
        "asserts": [r"\bbanner\b", r"\binterstitial\b", r"\badvert(isement)?s?\b"],
        # Not a bare "ad-free": that is usually the name of a purchasable
        # upgrade in an app that very much has ads.
        "denies": [r"contains no ad", r"no ads at all", r"completely ad-free"],
        "code": [r"\bBannerAd\b", r"\bInterstitialAd\b", r"google_mobile_ads"],
    },
    {
        "name": "accounts or sign-in",
        "asserts": [r"\bsign in\b", r"\bcreate an account\b", r"\blog in\b"],
        "denies": [r"no account", r"no sign-?in", r"nothing to sign"],
        "code": [r"signInWith(?!Anonymously)", r"\bcreateUserWith"],
    },
    {
        "name": "online or multi-device play",
        "asserts": [r"\bonline\b", r"same wi-?fi", r"two devices", r"\bmatchmak", r"\blobby\b"],
        # **Nothing mode-scoped.** "No second device" and "one phone" describe
        # a *mode* — the one where two people share a handset — in apps that
        # also have a two-device mode described three paragraphs later. Read as
        # global claims they flagged an app for denying a feature it was
        # advertising on the same page. A denial only counts if it is about the
        # whole app.
        # **The denial forms an app actually writes.** Hoverline ships four AI
        # rivals and says so at length, which makes "this is not multiplayer"
        # the single most important sentence in its review notes — and saying
        # it properly means writing the words "matchmaking" and "online",
        # both of which are asserts. With only the three patterns above, the
        # most careful disclosure in the family FAILED for making it. Same
        # shape as the leaderboards entry below, which is rule 3 of this
        # skill's own guidance.
        #
        # All of these are whole-app statements, which is what the note above
        # requires: none of them can be read as describing one mode of an app
        # that has another.
        "denies": [r"no online play", r"\boffline only\b", r"never connects",
                   r"no matchmaking", r"never goes online",
                   r"no network connection of any kind",
                   r"there is no network"],
        "code": [r"\bNearby\w*\b", r"\bSocket\b", r"\bmultiplayer\b"],
    },
    {
        "name": "leaderboards",
        "asserts": [r"\bleaderboard"],
        # **A denial contains an assertion**, which is rule 3 of this skill's
        # own guidance and this entry was the one place breaking it. "No
        # accounts, no sign-in, no leaderboards" is an app being honest about
        # not having one, and with an empty `denies` it was reported as an app
        # claiming one — a FAIL on the most careful listing in the family.
        "denies": [r"no leaderboard", r"without .{0,20}leaderboard",
                   r"leaderboard-free"],
        # **Not a bare "leaderboard".** That matched `Icons.leaderboard_outlined`
        # and a comment, and reported a leaderboard in an app with none.
        # An icon is not a capability; only an API that submits a score is.
        "code": [r"GameCenter", r"PlayGames", r"submitScore", r"\bLeaderboard\w*\("],
    },
]

GENERATED = (".g.dart", ".freezed.dart", ".config.dart", ".gr.dart")
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

failures: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def listing_files(app: Path) -> list[Path]:
    """Every human-readable listing file, including the review notes.

    **The review notes are in scope and are usually the worst offender.** They
    are written once, read by exactly one person who can reject the app, and
    nobody revisits them — so they are where a deleted mode survives longest.

    TestFlight "what to test" copy is in scope for the same reason and was
    missed by the first version of this script: it tells real testers to go and
    find named features, so a stale one sends them looking for something that
    is not there and turns a test round into a bug report about the notes.
    """
    found: list[Path] = []
    for pattern in (
        "fastlane/metadata/*/en-US/*.txt",
        "fastlane/metadata/*/review_information/notes.txt",
        "fastlane/metadata/*/testflight/*.txt",
        "fastlane/metadata/*/changelogs/*.txt",
        "fastlane/metadata/android/en-US/*.txt",
    ):
        found.extend(sorted(app.glob(pattern)))
    # URLs and copyright lines are not prose and only add noise.
    return [p for p in found if not p.name.endswith(("_url.txt", "copyright.txt"))]


def app_vocabulary(app: Path) -> str:
    """Everything the app itself says or names, as one lowercased blob.

    Deliberately coarse. The question is only "does this word appear anywhere
    in the app", so precision costs nothing here and false *positives* are what
    make a check get ignored.
    """
    parts: list[str] = []
    for path in app.rglob("*.i18n.json"):
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    for path in list(app.glob("lib/**/*.dart")) + list(app.glob("packages/*/lib/**/*.dart")):
        if path.name.endswith(GENERATED):
            continue
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts).lower()


def code_blob(app: Path) -> str:
    """Non-generated Dart, **with comments stripped**.

    The comments in these repos explain at length what the app deliberately
    does *not* do, so matching capability patterns against them finds a
    rewarded video in an app whose only mention of one is a note saying it has
    none. Doc comments are the densest source of exactly the words being
    searched for.
    """
    parts: list[str] = []
    for path in list(app.glob("lib/**/*.dart")) + list(app.glob("packages/*/lib/**/*.dart")):
        if path.name.endswith(GENERATED):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
        source = re.sub(r"^\s*///?.*$", "", source, flags=re.M)
        parts.append(source)
    return "\n".join(parts)


def check_proper_nouns(files: list[Path], vocab: str) -> None:
    """Named things in the listing that the app has never heard of.

    A capitalised word mid-sentence, or any Quoted "Thing", is almost always
    the name of a screen, a mode or a character. If the app's own strings and
    source never mention it, the listing is describing a different app —
    usually the one this was forked from.
    """
    unknown: dict[str, set[str]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        candidates: set[str] = set()
        # Quoted names first: the review notes label buttons this way.
        candidates.update(re.findall(r'"([A-Za-z][A-Za-z \'-]{1,28})"', text))
        # Then capitalised words that are not starting a sentence or a line.
        for match in re.finditer(r"(?<![.!?:\n]\s)(?<!^)\b([A-Z][a-z]{2,})\b", text, re.M):
            candidates.add(match.group(1))
        for raw in candidates:
            words = [w for w in re.split(r"[^A-Za-z']+", raw) if w]
            # A quoted phrase is known if every word in it is known.
            missing = [
                w for w in words
                if w.lower() not in STOPWORDS and w.lower() not in vocab
            ]
            if missing:
                unknown.setdefault(raw.strip(), set()).add(path.name)

    if not unknown:
        ok("Every name in the listing exists somewhere in the app")
        return
    lines = [
        f"{len(unknown)} name(s) in the listing appear nowhere in the app:",
    ]
    for name in sorted(unknown):
        lines.append(f"  {name!r}  ({', '.join(sorted(unknown[name]))})")
    lines.append(
        "A screen, mode or character the app does not have is the single most"
    )
    lines.append(
        "expensive thing a listing can contain: a reviewer told to try it will"
    )
    lines.append("look for it, fail, and reject on 2.3 Accurate Metadata.")
    fail("\n       ".join(lines))


def check_capabilities(files: list[Path], code: str) -> None:
    """Claims about adverts, purchases, accounts and online play."""
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in files
    ).lower()

    clean = True
    for claim in CAPABILITY_CLAIMS:
        present = any(re.search(p, code) for p in claim["code"]) and not any(
            re.search(p, code) for p in claim.get("absent_if", [])
        )
        denied = any(re.search(p, text) for p in claim["denies"])
        # **A denial wins over an assertion, because it contains one.** "There
        # are no in-app purchases" matches the phrase "in-app purchase", so
        # reading the two independently made every honest disclaimer look like
        # a claim — and the script then failed the app for describing a feature
        # it had just said it did not have.
        asserted = not denied and any(
            re.search(p, text) for p in claim["asserts"]
        )

        if denied and present:
            clean = False
            fail(
                f"The listing says the app has no {claim['name']}, and the code"
                f"\n       has one. This is a promise to a reviewer that the"
                f"\n       binary breaks."
                f"\n"
                f"\n       Before rewriting the copy, check whether it is"
                f"\n       reachable in a *release* build: these apps routinely"
                f"\n       carry a full implementation behind blank production"
                f"\n       unit ids or a false flag, and an unreachable feature"
                f"\n       makes the claim true. If that is the case, add the"
                f"\n       gate to this claim's `absent_if` so the next run is"
                f"\n       quiet — and say so in the review notes, because a"
                f"\n       reviewer cannot see a blank unit id."
            )
        elif present and not asserted:
            clean = False
            warn(
                f"The app has {claim['name']} and no listing file mentions it."
                f"\n       Undisclosed is not the same as absent; say so in the"
                f"\n       review notes at least."
            )
        elif asserted and not present:
            clean = False
            fail(
                f"The listing describes {claim['name']} and the code has none."
                f"\n       Either it was removed and the copy was not, or the copy"
                f"\n       came from the app this one was forked from."
            )
    if clean:
        ok("Advertising, purchase and account claims match the code")


def check_counts(files: list[Path], app: Path) -> None:
    """"Twelve tables", "six themes", "ten badges" — against the real lists.

    Advisory rather than a failure: the mapping from a noun to a Dart list is a
    guess, and a check that guesses wrong and fails is a check people learn to
    skip. It is here because a stale count is invisible, survives every test,
    and is exactly the kind of thing that drifts when content is added.
    """
    counts: dict[str, int] = {}
    for path in list(app.glob("packages/*/lib/**/*.dart")) + list(app.glob("lib/**/*.dart")):
        if path.name.endswith(GENERATED):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")

        # **Keyed on the enclosing class, not the element type.** `Tables.all`
        # is a `List<TableSpec>`, and keying on `TableSpec` gave "tablespec",
        # which prefix-matched the word "tables" in the listing along with
        # "tabletheme" and "tableend" — three warnings about one sentence, two
        # of them nonsense.
        for match in re.finditer(
            r"(?:abstract\s+)?(?:final\s+)?class\s+(\w+)\s*\{(.*?)\n\}",
            source,
            re.S,
        ):
            holder, body = match.group(1), match.group(2)
            listing = re.search(
                r"static const (?:List<\w+> )?all\s*=\s*<(\w+)>\[(.*?)\];",
                body,
                re.S,
            )
            if not listing:
                continue
            element = listing.group(1)
            # Counted by constructor calls, not by splitting on commas: these
            # are multi-line literals whose arguments are themselves
            # comma-separated, which counted twelve tables as eighty-four.
            found = len(re.findall(rf"\b{re.escape(element)}\s*\(", listing.group(2)))
            if found:
                counts[holder.lower()] = found

        # `enum Thing { a, b, c }` — power-ups and the like.
        #
        # **Only the head of the body, up to the first `;`.** A Dart enum may
        # carry methods, and scanning the whole block counted `for` and `if`
        # from their bodies as members — which reported ten achievements as
        # twelve and produced a confident, wrong warning about the listing.
        for match in re.finditer(r"enum (\w+)\s*\{(.*?)\n\}", source, re.S):
            kind, body = match.group(1), match.group(2).split(";")[0]
            members = re.findall(r"^\s*([a-z]\w*)\s*[,(]", body, re.M)
            if members:
                counts.setdefault(kind.lower(), len(members))

    if not counts:
        return

    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
    found = False
    for match in re.finditer(
        r"\b(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")\s+([a-z]{3,})\b",
        text,
        re.I,
    ):
        raw, noun = match.group(1).lower(), match.group(2).lower()
        claimed = NUMBER_WORDS.get(raw, None)
        if claimed is None:
            if not raw.isdigit():
                continue
            claimed = int(raw)
        singular = noun[:-1] if noun.endswith("s") else noun
        for kind, actual in counts.items():
            # **Exact, after stripping one plural on each side.** Prefix
            # matching was tried and is what produced the "Twelve tables" /
            # "tablespec 84" nonsense: in a codebase where half the types start
            # with the same word, a prefix match relates almost anything to
            # almost anything.
            if kind.rstrip("s") == singular:
                found = True
                if actual != claimed:
                    warn(
                        f'The listing says "{match.group(0)}" and the code has'
                        f"\n       {actual} ({kind}). One of them is stale."
                    )
    if found:
        ok("Counted claims in the listing were checked against the code")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default=".", help="app directory (default: cwd)")
    parser.add_argument("--listing", action="append", default=[],
                        help="extra listing file to check; repeatable")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    args = parser.parse_args()

    app = Path(args.app).resolve()
    files = listing_files(app) + [Path(p) for p in args.listing]
    files = [p for p in files if p.is_file()]
    if not files:
        print(f"No listing files under {app}/fastlane/metadata. Nothing to check.")
        return 0

    if not args.json:
        print(f"\nListing accuracy — {app.name}")
        print(f"  {len(files)} listing file(s)\n")

    vocab = app_vocabulary(app)
    code = code_blob(app)
    if not vocab.strip():
        print("No Dart sources found — is this an app repo?", file=sys.stderr)
        return 1

    check_proper_nouns(files, vocab)
    check_capabilities(files, code)
    check_counts(files, app)

    if args.json:
        print(json.dumps({"failures": failures, "warnings": warnings}, indent=2))
        return 1 if failures else 0

    for message in warnings:
        print(f"\n\033[33m  ! {message}\033[0m")
    if failures:
        print(f"\n\033[31m{len(failures)} check(s) failed:\033[0m\n")
        for message in failures:
            print(f"  \033[31m✗\033[0m {message}\n")
        return 1
    print("\nListing and app agree.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
