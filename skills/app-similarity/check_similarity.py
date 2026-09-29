#!/usr/bin/env python3
"""Measure how much one app shares with its siblings: source, metadata, images.

Written after an app was rejected under App Store guideline 4.3(a) with 110 of
its 159 Dart files (69%) identical to a sibling that was already live.
The point of running this *before* submitting is that the number is invisible
otherwise: every one of those apps looked different on screen.

**It measures three surfaces because 4.3(a) names three.** The rejection letter
says "a similar binary, metadata, and/or concept" — so a clean source number
proves nothing while two apps ship the same description. Two sibling apps
carried byte-identical descriptions in two locales, one of them describing the
other app's spaceships, and no source check would ever say so.

    python3 check_similarity.py                 # cwd against its siblings
    python3 check_similarity.py --threshold 40
    python3 check_similarity.py --alias candy --alias fruit
    python3 check_similarity.py --surface source     # one surface only
    python3 check_similarity.py --json

Exits non-zero if any surface is at or above the threshold, or if any file on
any surface is byte-identical to a sibling's.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import pathlib
import re
import sys

# Files that say nothing about whether two apps are the same app.
SKIP_SUFFIXES = ('.g.dart', '.freezed.dart', '.config.dart', '.gr.dart')
SKIP_DIRS = {'build', '.dart_tool', '.git', 'ios', 'android', 'macos',
             'windows', 'linux', 'web', '.symlinks', 'Pods'}
# **Only `build` and dotfiles here, and the difference is load-bearing.**
# `SKIP_DIRS` exists to drop platform *source* trees, and it holds `ios` and
# `android` — which are also the directory names fastlane gives the listing, so
# reusing it here silently skipped every store text file and left the metadata
# surface reporting one file it had found by accident.
SKIP_DIRS_ASSET = {'build', '.git'}

# Store listing text. Everything a reviewer reads before opening the binary.
# Android lives under metadata/android/, iOS under metadata/ios/ or the
# fastlane default metadata/<locale>/ — all three are globbed the same way.
#
# `Framefile.json` is deliberately absent: it is fastlane's framing config, so
# it is identical across these apps for the same reason the logger is, and
# counting it would put a 100% on a surface with nothing on it.
META_DIRS = ('fastlane/metadata',)
META_SUFFIXES = ('.txt',)

# Store screenshots and the frames built from them.
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp')
IMAGE_DIRS = ('fastlane/screenshots', 'fastlane/metadata')

# Everything the binary actually ships that is not code or store copy: sound
# effects, fonts, and the generated icon and launch images on both platforms.
#
# **This surface exists because two live-adjacent apps shipped the same sound
# file under four different names and nothing noticed.** One game's
# `level_clear.wav` was byte-identical to a live sibling's `level_up.wav`, and
# to `race_won.wav`, `cleared.wav` and `level_up.wav` in three more repos. The
# generators had been
# forked and never re-composed, so the same `_arpeggio([523, 659, 784, 1047,
# 1319])` call produced the same bytes in five repos.
#
# Guideline 4.3(a) says "the same source code **or assets**", and until this
# surface existed the checker read only Dart, store text and screenshots — so
# it could return a clean bill of health on an app shipping a live app's audio.
#
# `ios` and `android` are needed here and are in `SKIP_DIRS`, which is why this
# uses `SKIP_DIRS_ASSET` like the metadata and screenshot surfaces do.
ASSET_SUFFIXES = ('.wav', '.mp3', '.ogg', '.m4a', '.aac',
                  '.ttf', '.otf',
                  '.png', '.jpg', '.jpeg', '.webp', '.svg',
                  '.riv', '.json', '.lottie')
ASSET_DIRS = ('assets',
              'ios/Runner/Assets.xcassets',
              'android/app/src/main/res')

# Tool-generated manifests, excluded for `Framefile.json`'s reason: they list
# filenames and scale factors, `flutter_launcher_icons` and
# `flutter_native_splash` write them, and they are identical across these apps
# because the tools are. Left in, every app reports three permanent matches on
# this surface — and three entries that always mean nothing are how the one
# that means something gets skimmed past.
ASSET_EXCLUDE_NAME = {'contents.json'}

SURFACES = ('source', 'metadata', 'screenshots', 'assets')


def pubspec_name(app: pathlib.Path) -> str | None:
    spec = app / 'pubspec.yaml'
    if not spec.exists():
        return None
    for line in spec.read_text().splitlines():
        m = re.match(r'^name:\s*(\S+)', line)
        if m:
            return m.group(1)
    return None


def tokens_for(app: pathlib.Path, extra: list[str]) -> list[str]:
    """Every spelling of this app's name that could appear in source."""
    words: set[str] = set(extra)
    for base in filter(None, {pubspec_name(app), app.name}):
        flat = re.sub(r'[-_\s]', '', base)
        words |= {base, flat, base.replace('-', '_'), base.replace('_', '-'),
                  base.replace('_', ' '), base.replace('-', ' ')}
        words |= set(re.split(r'[-_\s]+', base))
    words = {w for w in words if len(w) >= 3}

    out: set[str] = set()
    for w in words:
        out |= {w.lower(), w.upper(), w.capitalize(), w.title()}
    # **Longest first, and this is the whole correctness of the tool.** Python's
    # alternation is leftmost-*first*, so with 'peel' before 'peel_frenzy' the
    # package name `peel_frenzy_ui` normalises to `X_frenzy_ui` — and every file
    # differing only by its package name then counts as different. That bug
    # understated one measurement by four points in the direction that lets a
    # bad app through.
    return sorted(out, key=len, reverse=True)


def normaliser(tokens: list[str]):
    if not tokens:
        return lambda text: text
    rx = re.compile('|'.join(re.escape(t) for t in tokens))
    return lambda text: rx.sub('X', text)


def _walk(app: pathlib.Path, suffixes: tuple[str, ...],
          under: tuple[str, ...] | None = None) -> dict[str, pathlib.Path]:
    """Every file under [app] with one of [suffixes], keyed by relative path.

    [under] restricts the search to a list of relative prefixes. Keying by
    relative path is what makes two apps comparable at all, and it is also the
    tool's main limitation — see `path-matching` in SKILL.md.
    """
    out: dict[str, pathlib.Path] = {}
    roots = [app / u for u in under] if under else [app]
    for root in roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob('*')
        for f in candidates:
            if not f.is_file() or not f.name.lower().endswith(suffixes):
                continue
            rel = f.relative_to(app)
            if any(p in SKIP_DIRS_ASSET or p.startswith('.')
                   for p in rel.parts):
                continue
            out[str(rel)] = f
    return out


def dart_files(app: pathlib.Path) -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    for f in app.rglob('*.dart'):
        rel = f.relative_to(app)
        if any(part in SKIP_DIRS or part.startswith('.') for part in rel.parts):
            continue
        if f.name.endswith(SKIP_SUFFIXES):
            continue
        out[str(rel)] = f
    return out


# Listing files that are the *developer's*, not the app's. One publisher's
# support address, privacy policy and marketing site are the same on every app
# they ship, and a copyright line and a review contact are boilerplate — so
# these match for the same reason the logger does. Leaving them in put a 33% on
# three URL files and buried the surface that matters.
#
# **`title.txt` and `name.txt` are excluded for a different and sharper
# reason: the normaliser makes them match unconditionally.** The whole content
# of those files is the app's name, and the normaliser's job is to rewrite the
# app's name to `X` — so `Asteroid Duel` and `Peel Frenzy` both become `X X`
# and the tool reported five apps with byte-identical titles that in fact share
# no word. Any file whose content *is* the app name is unmeasurable this way.
META_EXCLUDE_PATH = ('review_information', 'copyright', '_url.txt')
# **Matched on the exact filename, not as a substring.** `subtitle.txt` ends
# with `title.txt`, so a substring test silently dropped the subtitle — real
# listing copy — and took the metadata surface from six files to five with
# nothing to show that it had.
META_EXCLUDE_NAME = ('title.txt', 'name.txt')


def meta_files(app: pathlib.Path) -> dict[str, pathlib.Path]:
    """Store listing copy, minus the files that cannot help but match.

    What is left is what a reviewer actually reads as a description of *this*
    app: subtitle, keywords, promotional text, description, release notes and
    the TestFlight and App Review notes.
    """
    out = _walk(app, META_SUFFIXES, META_DIRS)
    return {
        k: v for k, v in out.items()
        if not any(x in k.lower() for x in META_EXCLUDE_PATH)
        and pathlib.PurePath(k).name.lower() not in META_EXCLUDE_NAME
    }


def image_files(app: pathlib.Path) -> dict[str, pathlib.Path]:
    return _walk(app, IMAGE_SUFFIXES, IMAGE_DIRS)


def asset_files(app: pathlib.Path) -> dict[str, pathlib.Path]:
    """Bundled assets: audio, fonts, and the generated icon and launch images.

    Deliberately includes the platform icon and splash trees, which the source
    surface skips. Those are *generated* from the app's own painters here, so
    they are the one place a fork's leftovers show up as a picture rather than
    as code — and an icon shared between two apps is the single most visible
    thing guideline 4.3 can be shown.
    """
    out = _walk(app, ASSET_SUFFIXES, ASSET_DIRS)
    return {
        k: v for k, v in out.items()
        if pathlib.PurePath(k).name.lower() not in ASSET_EXCLUDE_NAME
    }


def bucket(path: str) -> str:
    """Group a shared file by what kind of sameness it represents.

    A bare percentage is not actionable: shared logging is expected for one
    developer's two apps, shared *gameplay* is the thing 4.3 is about. The
    tiers are what turn the number into a decision.
    """
    p = path.lower()
    if any(k in p for k in ('/logger/', 'log_', 'crash', 'bootstrap.dart',
                            'firebase', 'analytics', 'sentry')):
        return 'infrastructure'
    if any(k in p for k in ('/ads/', 'ad_service', 'banner', 'admob',
                            'interstitial', 'unity')):
        return 'infrastructure'
    if any(k in p for k in ('/router/', '/i18n/', 'setup', 'injection',
                            'di.dart', 'main.dart', 'run_app')):
        return 'infrastructure'
    if p.startswith(('test/', 'test_driver/', 'integration_test/', 'tool/')):
        return 'infrastructure'
    if any(k in p for k in ('/blocs/', '/cubits/', '/screens/', '/widgets/',
                            '/views/', '/pages/')):
        return 'app scaffolding'
    if '/domain/' in p or '/models/' in p or '/repos/' in p:
        return 'app scaffolding'
    return 'other'


def compare_text(mine: dict[str, pathlib.Path], theirs: dict[str, pathlib.Path],
                 norm_a, norm_b, near: float) -> tuple[list, int]:
    shared, lines = [], 0
    for rel, path in mine.items():
        twin = theirs.get(rel)
        if twin is None:
            continue
        try:
            a = norm_a(path.read_text()).splitlines()
            b = norm_b(twin.read_text()).splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        if a == b:
            ratio = 1.0
        else:
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            if ratio < near:
                continue
        shared.append((len(a), rel, ratio))
        lines += len(a)
    return sorted(shared, reverse=True), lines


def compare_bytes(mine: dict[str, pathlib.Path],
                  theirs: dict[str, pathlib.Path]) -> list:
    """Byte-identical images, matched on content rather than on path.

    **Content, not path, and deliberately.** A copied screenshot gets renamed to
    fit its new app's scene order, so matching on path would miss exactly the
    case this exists to catch. There is no near-match tier: two renders of
    different art are never 90% of the same bytes, so a ratio here would be
    noise dressed as a measurement.
    """
    def digest(files):
        out: dict[str, str] = {}
        for rel, f in files.items():
            try:
                out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                continue
        return out

    a, b = digest(mine), digest(theirs)
    theirs_by_hash: dict[str, str] = {}
    for rel, h in b.items():
        theirs_by_hash.setdefault(h, rel)

    shared = []
    for rel, h in sorted(a.items()):
        twin = theirs_by_hash.get(h)
        if twin is not None:
            shared.append((rel, twin))
    return shared


def compare(app: pathlib.Path, other: pathlib.Path, extra: list[str],
            near: float, surfaces: tuple[str, ...]):
    norm_a = normaliser(tokens_for(app, extra))
    norm_b = normaliser(tokens_for(other, extra))

    out: dict = {'sibling': other.name, 'surfaces': {}}

    if 'source' in surfaces:
        mine, theirs = dart_files(app), dart_files(other)
        shared, lines = compare_text(mine, theirs, norm_a, norm_b, near)
        out['surfaces']['source'] = {
            'shared_files': len(shared), 'total_files': len(mine),
            'percent': round(len(shared) * 100 / (len(mine) or 1)),
            'shared_lines': lines, 'files': shared,
            'identical': [r for _, r, x in shared if x == 1.0],
        }

    if 'metadata' in surfaces:
        mine, theirs = meta_files(app), meta_files(other)
        shared, lines = compare_text(mine, theirs, norm_a, norm_b, near)
        out['surfaces']['metadata'] = {
            'shared_files': len(shared), 'total_files': len(mine),
            'percent': round(len(shared) * 100 / (len(mine) or 1)),
            'shared_lines': lines, 'files': shared,
            'identical': [r for _, r, x in shared if x == 1.0],
        }

    if 'screenshots' in surfaces:
        mine, theirs = image_files(app), image_files(other)
        pairs = compare_bytes(mine, theirs)
        out['surfaces']['screenshots'] = {
            'shared_files': len(pairs), 'total_files': len(mine),
            'percent': round(len(pairs) * 100 / (len(mine) or 1)),
            'shared_lines': 0,
            'files': [(0, f'{a}  ==  {b}', 1.0) for a, b in pairs],
            'identical': [a for a, _ in pairs],
        }

    if 'assets' in surfaces:
        mine, theirs = asset_files(app), asset_files(other)
        pairs = compare_bytes(mine, theirs)
        out['surfaces']['assets'] = {
            'shared_files': len(pairs), 'total_files': len(mine),
            'percent': round(len(pairs) * 100 / (len(mine) or 1)),
            'shared_lines': 0,
            'files': [(0, f'{a}  ==  {b}', 1.0) for a, b in pairs],
            'identical': [a for a, _ in pairs],
        }

    out['percent'] = max((s['percent'] for s in out['surfaces'].values()),
                         default=0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--app', default='.', help='app directory (default: cwd)')
    ap.add_argument('--root', default=None,
                    help='directory holding the sibling apps (default: parent)')
    ap.add_argument('--threshold', type=int, default=30,
                    help='fail at or above this percent (default: 30)')
    ap.add_argument('--near', type=float, default=0.9,
                    help='count a file as shared at or above this similarity')
    ap.add_argument('--alias', action='append', default=[],
                    help='extra domain word to normalise away, e.g. --alias candy')
    ap.add_argument('--surface', action='append', default=[], choices=SURFACES,
                    help='limit to one surface (default: all three)')
    ap.add_argument('--top', type=int, default=12, help='shared files to list')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    app = pathlib.Path(args.app).resolve()
    root = pathlib.Path(args.root).resolve() if args.root else app.parent
    surfaces = tuple(args.surface) if args.surface else SURFACES

    siblings = [d for d in sorted(root.iterdir())
                if d.is_dir() and d != app and (d / 'pubspec.yaml').exists()]
    if not siblings:
        print(f'No sibling apps with a pubspec.yaml under {root}', file=sys.stderr)
        return 2

    results = [compare(app, s, args.alias, args.near, surfaces)
               for s in siblings]
    results.sort(key=lambda r: -r['percent'])

    # Per surface, the sibling that shares the most with this app. Reported
    # separately because a clean source number beside a copied description is
    # the exact shape of pass that 4.3(a) rejects anyway.
    worst_by_surface = {
        s: max(results, key=lambda r: r['surfaces'][s]['percent'])
        for s in surfaces
    }
    # **Source is excluded from this list on purpose.** A byte-identical
    # logger, i18n barrel or ad wrapper is what shared infrastructure looks
    # like, and this list is a hard fail — including source would put 774
    # entries under a heading that is supposed to mean "somebody copied
    # something", which is how a real finding gets lost. Source sharing is
    # judged by its percentage and its tier breakdown instead.
    #
    # A copied *description* or a copied *screenshot* has no such excuse: there
    # is no job two apps share that requires the same store text.
    # **A byte-identical file on any of these three is a failure whatever the
    # percentage says.** There is no job two apps share that needs the same
    # store sentence, the same screenshot or the same sound effect — unlike
    # source, where an identical logger is exactly what shared infrastructure
    # looks like.
    HARD = tuple(
        s for s in surfaces if s in ('metadata', 'screenshots', 'assets')
    )
    identical = sorted({
        (s, f, r['sibling'])
        for r in results for s in HARD
        for f in r['surfaces'][s]['identical']
    })

    over = [s for s in surfaces
            if worst_by_surface[s]['surfaces'][s]['percent'] >= args.threshold]
    failed = bool(over) or bool(identical)

    if args.json:
        print(json.dumps({
            'app': app.name, 'threshold': args.threshold,
            'surfaces': {s: {
                'worst_sibling': worst_by_surface[s]['sibling'],
                'percent': worst_by_surface[s]['surfaces'][s]['percent'],
            } for s in surfaces},
            'over_threshold': over,
            'byte_identical': [{'surface': s, 'file': f, 'sibling': sib}
                               for s, f, sib in identical],
            'results': results,
        }, indent=2, default=str))
        return 1 if failed else 0

    print(f'\n{app.name} — threshold {args.threshold}%, '
          f'surfaces: {", ".join(surfaces)}')
    if not args.alias:
        print('  note: no --alias given. Domain nouns that differ between the '
              'apps (a fruit vs a taco) will read as\n'
              '        differences, which UNDERSTATES sharing. Pass them.')

    for s in surfaces:
        w = worst_by_surface[s]
        sw = w['surfaces'][s]
        print(f'\n=== {s.upper()} — {sw["total_files"]} files ===')
        if sw['total_files'] == 0:
            # Not a pass. An empty surface reads as "checked and clean" when
            # nothing was checked at all.
            print('  NOTHING TO COMPARE — this app has no files on this '
                  'surface, so it is\n  unmeasured, not clean.')
            continue
        for r in sorted(results, key=lambda r: -r['surfaces'][s]['percent']):
            rs = r['surfaces'][s]
            if rs['percent'] == 0:
                continue
            flag = '  <-- OVER' if rs['percent'] >= args.threshold else ''
            print(f'  {rs["percent"]:3}%  {rs["shared_files"]:3}/'
                  f'{rs["total_files"]:<3} files   {r["sibling"]}{flag}')

        if sw['percent'] and s == 'source':
            tiers: dict[str, list[int]] = {}
            for n, rel, _ in sw['files']:
                t = tiers.setdefault(bucket(rel), [0, 0])
                t[0] += 1
                t[1] += n
            print(f'\n  what is shared with {w["sibling"]}:')
            for name, (f, l) in sorted(tiers.items(), key=lambda kv: -kv[1][1]):
                print(f'    {name:18} {f:3} files {l:5} lines')

        if sw['files']:
            print(f'\n  largest shared with {w["sibling"]}:')
            for n, rel, ratio in sw['files'][:args.top]:
                kind = 'identical' if ratio == 1.0 else f'{ratio:.0%} same'
                size = f'{n:5}' if n else '    -'
                print(f'    {size}  {rel:<58} {kind}')

    if identical:
        print(f'\nBYTE-IDENTICAL FILES ({len(identical)}) — a hard fail at any '
              'percentage:')
        for s, f, sib in identical[:40]:
            print(f'  [{s}] {f}  ==  {sib}')
        if len(identical) > 40:
            print(f'  ... and {len(identical) - 40} more')

    print()
    if failed:
        reasons = []
        if over:
            reasons.append('over threshold on: ' + ', '.join(over))
        if identical:
            reasons.append(f'{len(identical)} byte-identical file(s)')
        print('FAIL — ' + '; '.join(reasons))
        print('See the skill for what counts as a legitimate fix. Renaming to '
              'defeat the check is not one.')
    else:
        print('OK')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
