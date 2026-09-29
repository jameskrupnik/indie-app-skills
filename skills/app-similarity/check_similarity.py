#!/usr/bin/env python3
"""Measure how much one Flutter app shares with its sibling apps.

App Store guideline 4.3(a) rejects apps that share "the same source code or
assets" with apps already submitted and differ only in minor ways, and it names
"a similar binary, metadata, and/or concept". So this measures four surfaces,
not one: a clean source number proves nothing while two apps ship the same
description, screenshot or sound effect.

  source       non-generated Dart, matched by relative path, near-dupes count
  metadata     fastlane store listing text (.txt), matched by relative path
  screenshots  fastlane store images, byte-identical, matched on content
  assets       bundled audio/fonts/images/icons, byte-identical, on content

Siblings are the directories next to the app (or under --root) that contain a
pubspec.yaml. Standard library only; Python 3.9+.

Exit codes: 0 all clear, 1 over threshold or a byte-identical file on a
non-source surface, 2 usage error (bad path, no siblings).
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import hashlib
import json
import os
import pathlib
import re
import sys

SURFACES = ('source', 'metadata', 'screenshots', 'assets')

# Pruned everywhere. Walking into build/ or .dart_tool/ costs minutes on a
# built app (gigabytes of output) and never holds anything worth comparing.
ALWAYS_SKIP = {'build', '.dart_tool', '.git', '.symlinks', 'Pods',
               'node_modules', 'ephemeral', '.fvm', '.gradle'}
# Platform trees, pruned for the source surface only, and only when they sit
# next to a pubspec.yaml. The assets and store surfaces need `ios` and
# `android` (icons, launch images, and fastlane's own `metadata/ios`).
PLATFORM_DIRS = {'ios', 'android', 'macos', 'windows', 'linux', 'web'}
GENERATED_DART = ('.g.dart', '.freezed.dart', '.config.dart', '.gr.dart',
                  '.mocks.dart')

# Where fastlane lives: one shared dir at the app root, or the per-platform
# layout Flutter's deployment docs use. Override with --fastlane.
FASTLANE_DIRS = ('fastlane', 'ios/fastlane', 'android/fastlane')

# Listing files that belong to the developer, not the app: support/privacy/
# marketing URLs, copyright, and the review contact block. They match on every
# app one publisher ships, like a logger does, and left in they bury the
# surface under permanent matches.
META_EXCLUDE_PATH = ('review_information', 'copyright', '_url.txt')
# Files whose whole content is the app name. The normaliser rewrites the app
# name to X, so any two titles become identical. Unmeasurable this way.
# Matched on exact filename: `subtitle.txt` ends with `title.txt`, and a
# substring test would silently drop real listing copy.
META_EXCLUDE_NAME = {'title.txt', 'name.txt'}

IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp')

ASSET_SUFFIXES = ('.wav', '.mp3', '.ogg', '.m4a', '.aac', '.flac',
                  '.ttf', '.otf',
                  '.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg',
                  '.riv', '.json', '.lottie')
# Every directory named `assets` anywhere in the app (so packages/*/assets in a
# monorepo count), plus the generated launcher icon and launch image trees.
ASSET_DIR_NAME = 'assets'
PLATFORM_ASSET_DIRS = ('ios/Runner/Assets.xcassets', 'android/app/src/main/res')
# Xcode asset-catalog manifests. The icon and splash generators write them, so
# they are identical across apps because the tools are. Same for fastlane's
# Framefile.json, which is not a .txt and so never reaches the metadata set.
ASSET_EXCLUDE_NAME = {'contents.json'}


def _walk(top: pathlib.Path, suffixes: tuple[str, ...],
          prune_platform: bool = False):
    """Yield files under [top] ending in [suffixes], pruning junk directories."""
    if not top.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(top):
        at_package_root = prune_platform and 'pubspec.yaml' in filenames
        dirnames[:] = [
            d for d in dirnames
            if d not in ALWAYS_SKIP and not d.startswith('.')
            and not (at_package_root and d in PLATFORM_DIRS)
        ]
        for name in filenames:
            if name.lower().endswith(suffixes):
                yield pathlib.Path(dirpath) / name


def _rel(app: pathlib.Path, files, ignore: list[str]) -> dict[str, pathlib.Path]:
    out = {}
    for f in files:
        rel = f.relative_to(app).as_posix()
        if not any(fnmatch.fnmatch(rel, g) for g in ignore):
            out[rel] = f
    return out


def dart_files(app, cfg) -> dict[str, pathlib.Path]:
    files = (f for f in _walk(app, ('.dart',), prune_platform=True)
             if not f.name.endswith(GENERATED_DART))
    return _rel(app, files, cfg.ignore)


def meta_files(app, cfg) -> dict[str, pathlib.Path]:
    """Store listing copy a reviewer reads as a description of this app."""
    files = (f for d in cfg.fastlane for f in _walk(app / d / 'metadata', ('.txt',)))
    out = _rel(app, files, cfg.ignore)
    return {k: v for k, v in out.items()
            if not any(x in k.lower() for x in META_EXCLUDE_PATH)
            and v.name.lower() not in META_EXCLUDE_NAME}


def image_files(app, cfg) -> dict[str, pathlib.Path]:
    # Play's feature graphic and phone shots live under metadata/android/.../images.
    files = (f for d in cfg.fastlane for sub in ('screenshots', 'metadata')
             for f in _walk(app / d / sub, IMAGE_SUFFIXES))
    return _rel(app, files, cfg.ignore)


def asset_files(app, cfg) -> dict[str, pathlib.Path]:
    """Bundled assets, including the platform icon and launch-image trees.

    Those trees are where a fork's leftovers show up as a picture rather than as
    code: a template's branded launch image survives regeneration if the tool
    writes density buckets and never the file the launch XML actually loads.
    """
    tops = [app / d for d in (*PLATFORM_ASSET_DIRS, *cfg.asset_dir)]
    for dirpath, dirnames, _ in os.walk(app):
        dirnames[:] = [d for d in dirnames
                       if d not in ALWAYS_SKIP and not d.startswith('.')]
        if pathlib.Path(dirpath).name == ASSET_DIR_NAME:
            tops.append(pathlib.Path(dirpath))
            dirnames[:] = []
    files = (f for t in tops for f in _walk(t, ASSET_SUFFIXES)
             if f.name.lower() not in ASSET_EXCLUDE_NAME)
    return _rel(app, files, cfg.ignore)


COLLECTORS = {'source': dart_files, 'metadata': meta_files,
              'screenshots': image_files, 'assets': asset_files}


def pubspec_name(app: pathlib.Path) -> str | None:
    try:
        text = (app / 'pubspec.yaml').read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    m = re.search(r'^name:\s*["\']?([\w-]+)', text, re.M)
    return m.group(1) if m else None


def name_tokens(app: pathlib.Path) -> set[str]:
    """Every spelling of this app's name that could appear in source or copy."""
    words: set[str] = set()
    for base in filter(None, {pubspec_name(app), app.name}):
        parts = [p for p in re.split(r'[-_\s]+', base) if p]
        words |= {base, ''.join(parts), '_'.join(parts), '-'.join(parts),
                  ' '.join(parts), *parts}
        camel = ''.join(p.capitalize() for p in parts)       # FruitDrop
        words |= {camel, camel[:1].lower() + camel[1:]}      # fruitDrop
    out: set[str] = set()
    for w in words:
        if len(w) >= 3:
            out |= {w, w.lower(), w.upper(), w.capitalize(), w.title()}
    return out


def normaliser(tokens: set[str]):
    if not tokens:
        return lambda text: text
    # **Longest first, and this is the whole correctness of the tool.** Regex
    # alternation is leftmost-first, so with `fruit` before `fruit_drop` the
    # package name `fruit_drop_ui` becomes `X_drop_ui`, and every file that
    # differs only by its package name reads as different. Understated sharing
    # is the error that lets a bad app through.
    rx = re.compile('|'.join(re.escape(t)
                             for t in sorted(tokens, key=len, reverse=True)))
    return lambda text: rx.sub('X', text)


def bucket(path: str) -> str:
    """Group a shared source file by what kind of sameness it represents.

    A shared logger is expected for one developer's two apps; shared gameplay is
    what 4.3 is about. Keyword heuristic on path words, not a parser.
    """
    words = set(re.split(r'[/_.\-]+', path.lower()))
    segs = path.lower().split('/')
    if words & {'log', 'logger', 'logging', 'crash', 'bootstrap', 'firebase',
                'analytics', 'sentry', 'ads', 'ad', 'admob', 'banner',
                'interstitial', 'rewarded', 'consent', 'unity', 'router',
                'routes', 'i18n', 'l10n', 'setup', 'injection', 'di', 'locator',
                'main'}:
        return 'infrastructure'
    if any(s in ('test', 'test_driver', 'integration_test', 'tool')
           for s in segs[:-1]):
        return 'infrastructure'
    if words & {'bloc', 'blocs', 'cubit', 'cubits', 'screen', 'screens',
                'widget', 'widgets', 'view', 'views', 'page', 'pages', 'domain',
                'model', 'models', 'repo', 'repos', 'repository',
                'repositories'}:
        return 'app scaffolding'
    return 'other'


def compare_text(mine, theirs, norm, near: float) -> list[dict]:
    shared = []
    for rel, path in mine.items():
        twin = theirs.get(rel)
        if twin is None:
            continue
        try:
            a = norm(path.read_text(encoding='utf-8')).splitlines()
            b = norm(twin.read_text(encoding='utf-8')).splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        if a == b:
            ratio = 1.0
        else:
            sm = difflib.SequenceMatcher(None, a, b)
            if sm.real_quick_ratio() < near or sm.quick_ratio() < near:
                continue
            ratio = sm.ratio()
            if ratio < near:
                continue
            ratio = min(round(ratio, 3), 0.999)  # 1.0 means identical only
        shared.append({'file': rel, 'lines': len(a), 'ratio': ratio})
    return sorted(shared, key=lambda x: (-x['lines'], x['file']))


def _digests(files) -> dict[str, str]:
    out = {}
    for rel, f in files.items():
        try:
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def compare_bytes(mine, theirs) -> list[dict]:
    """Byte-identical files, matched on content rather than path.

    A copied screenshot or sound gets renamed to suit its new app, so matching
    on path would miss exactly the case this exists to catch. No near tier: two
    encodings of different art are never 90% the same bytes.
    """
    by_hash: dict[str, str] = {}
    for rel, h in sorted(_digests(theirs).items()):
        by_hash.setdefault(h, rel)
    return [{'file': rel, 'twin': by_hash[h], 'lines': 0, 'ratio': 1.0}
            for rel, h in sorted(_digests(mine).items()) if h in by_hash]


def compare(app, other, cfg, mine_files):
    # Normalise both sides with the union of both apps' names. Normalising each
    # side with only its own name is asymmetric: an app called `color-lab` would
    # turn its own `label` into `Xel` while the sibling's stays `label`, and a
    # short common word in either name (lab, log, pie, app) then reads as a
    # difference everywhere it appears.
    norm = normaliser(name_tokens(app) | name_tokens(other) | cfg.alias_tokens)
    out = {'sibling': other.name, 'surfaces': {}}
    for s in cfg.surfaces:
        mine, theirs = mine_files[s], COLLECTORS[s](other, cfg)
        if s in ('source', 'metadata'):
            shared = compare_text(mine, theirs, norm, cfg.near)
        else:
            shared = compare_bytes(mine, theirs)
        out['surfaces'][s] = {
            'shared_files': len(shared), 'total_files': len(mine),
            'percent': round(len(shared) * 100 / (len(mine) or 1)),
            'shared_lines': sum(x['lines'] for x in shared),
            'files': shared,
            'identical': [x['file'] for x in shared if x['ratio'] == 1.0],
        }
    out['percent'] = max((v['percent'] for v in out['surfaces'].values()),
                         default=0)
    return out


def find_siblings(app, root, only, exclude):
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.resolve() == app:
            continue
        if not (d / 'pubspec.yaml').exists():
            continue
        if only and d.name not in only:
            continue
        if any(fnmatch.fnmatch(d.name, g) for g in exclude):
            continue
        out.append(d.resolve())
    return out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split('\n\n')[0] + ' Reports four surfaces '
        '(source, metadata, screenshots, assets) against every sibling app, '
        'for App Store guideline 4.3(a) "spam" checks.',
        epilog='Always pass --alias for the domain nouns of both apps (the '
        'taco, the fruit): without them, files identical except for those '
        'words count as different, which UNDERSTATES sharing. '
        'Exit codes: 0 clear, 1 fail, 2 usage error.')
    ap.add_argument('--app', default='.', help='app to check (default: cwd)')
    ap.add_argument('--root', help='directory holding the sibling apps '
                    '(default: the app\'s parent)')
    ap.add_argument('--sibling', action='append', default=[], metavar='NAME',
                    help='compare only against this sibling directory; '
                    'repeatable (default: every dir under --root with a '
                    'pubspec.yaml)')
    ap.add_argument('--exclude', action='append', default=[], metavar='GLOB',
                    help='skip sibling dirs whose name matches, e.g. '
                    '"*-webdemo" or a plugin package; repeatable')
    ap.add_argument('--alias', action='append', default=[], metavar='WORD',
                    help='domain word to normalise away in text, e.g. '
                    '--alias candy; repeatable')
    ap.add_argument('--surface', action='append', default=[], choices=SURFACES,
                    help='limit to a surface; repeatable (default: all four)')
    ap.add_argument('--threshold', type=int, default=30, metavar='N',
                    help='fail when any surface is at or above N%% (default 30)')
    ap.add_argument('--near', type=float, default=0.9, metavar='R',
                    help='count a text file as shared at or above this '
                    'similarity ratio, 0-1 (default 0.9)')
    ap.add_argument('--fastlane', action='append', default=[], metavar='DIR',
                    help='fastlane dir relative to each app; repeatable '
                    '(default: %s)' % ', '.join(FASTLANE_DIRS))
    ap.add_argument('--asset-dir', action='append', default=[], metavar='DIR',
                    help='extra asset dir relative to each app, beyond every '
                    '"assets/" dir and the iOS/Android icon trees; repeatable')
    ap.add_argument('--ignore', action='append', default=[], metavar='GLOB',
                    help='drop files whose app-relative path matches, on every '
                    'surface, e.g. "assets/fonts/Inter-*.ttf"; repeatable, and '
                    'listed in the report so it is never silent')
    ap.add_argument('--top', type=int, default=12, metavar='N',
                    help='shared files to list per surface (default 12)')
    ap.add_argument('--json', action='store_true',
                    help='machine-readable output for CI or a hook')
    args = ap.parse_args(argv)
    if not 0 < args.near <= 1:
        ap.error('--near must be in (0, 1]')
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    app = pathlib.Path(args.app).resolve()
    # Default root is the parent of the path as given, not of its resolved
    # target, so a directory of symlinked apps works as a sibling set.
    root = pathlib.Path(os.path.abspath(args.root or
                                        os.path.join(args.app, os.pardir)))
    if not (app / 'pubspec.yaml').is_file():
        print(f'error: {app} has no pubspec.yaml — not a Dart/Flutter app',
              file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f'error: --root {root} is not a directory', file=sys.stderr)
        return 2

    args.surfaces = tuple(dict.fromkeys(args.surface)) or SURFACES
    args.fastlane = args.fastlane or list(FASTLANE_DIRS)
    args.alias_tokens = {v for a in args.alias
                         for v in (a, a.lower(), a.capitalize(), a.upper())}

    siblings = find_siblings(app, root, set(args.sibling), args.exclude)
    if not siblings:
        print(f'error: no sibling apps with a pubspec.yaml under {root}',
              file=sys.stderr)
        return 2

    mine_files = {s: COLLECTORS[s](app, args) for s in args.surfaces}
    results = [compare(app, s, args, mine_files) for s in siblings]
    results.sort(key=lambda r: -r['percent'])
    worst = {s: max(results, key=lambda r: r['surfaces'][s]['percent'])
             for s in args.surfaces}

    # Source is left out of the byte-identical hard fail on purpose. An
    # identical logger or i18n barrel is what shared infrastructure looks like;
    # listing it would bury a copied description under hundreds of entries.
    # No job two apps share needs the same store text, screenshot or sound.
    identical = sorted({
        (s, f, r['sibling'])
        for r in results for s in args.surfaces if s != 'source'
        for f in r['surfaces'][s]['identical']
    })
    over = [s for s in args.surfaces
            if mine_files[s] and
            worst[s]['surfaces'][s]['percent'] >= args.threshold]
    unmeasured = [s for s in args.surfaces if not mine_files[s]]
    failed = bool(over or identical)

    if args.json:
        print(json.dumps({
            'app': app.name, 'root': str(root), 'threshold': args.threshold,
            'aliases': args.alias, 'ignored': args.ignore,
            'siblings': [s.name for s in siblings],
            'surfaces': {s: {
                'total_files': len(mine_files[s]),
                'measured': bool(mine_files[s]),
                'worst_sibling': (worst[s]['sibling']
                                  if worst[s]['surfaces'][s]['shared_files']
                                  else None),
                'percent': worst[s]['surfaces'][s]['percent'],
            } for s in args.surfaces},
            'over_threshold': over, 'unmeasured': unmeasured,
            'byte_identical': [{'surface': s, 'file': f, 'sibling': sib}
                               for s, f, sib in identical],
            'failed': failed,
            'results': results,
        }, indent=2))
        return 1 if failed else 0

    print(f'\n{app.name} vs {len(siblings)} sibling(s) under {root}\n'
          f'threshold {args.threshold}%, surfaces: {", ".join(args.surfaces)}')
    if args.ignore:
        print(f'  ignoring: {", ".join(args.ignore)}')
    if not args.alias:
        print('  note: no --alias given. Domain nouns that differ between the '
              'apps (a fruit vs a taco) will read as\n'
              '        differences, which UNDERSTATES sharing. Pass them.')

    for s in args.surfaces:
        w = worst[s]['surfaces'][s]
        print(f'\n=== {s.upper()} — {len(mine_files[s])} files ===')
        if not mine_files[s]:
            # Not a pass: a silent 0% reads as "checked and clean".
            print('  NOTHING TO COMPARE — this app has no files on this '
                  'surface, so it is\n  unmeasured, not clean.')
            continue
        rows = [r for r in sorted(results,
                                  key=lambda r: -r['surfaces'][s]['percent'])
                if r['surfaces'][s]['shared_files']]
        if not rows:
            print('  no sibling shares a file on this surface')
            continue
        for r in rows:
            rs = r['surfaces'][s]
            flag = '  <-- OVER' if rs['percent'] >= args.threshold else ''
            print(f'  {rs["percent"]:3}%  {rs["shared_files"]:3}/'
                  f'{rs["total_files"]:<3} files   {r["sibling"]}{flag}')

        sib = worst[s]['sibling']
        if s == 'source':
            tiers: dict[str, list[int]] = {}
            for x in w['files']:
                t = tiers.setdefault(bucket(x['file']), [0, 0])
                t[0] += 1
                t[1] += x['lines']
            print(f'\n  what is shared with {sib}:')
            for name, (f, n) in sorted(tiers.items(), key=lambda kv: -kv[1][1]):
                print(f'    {name:18} {f:3} files {n:5} lines')

        print(f'\n  largest shared with {sib}:')
        for x in w['files'][:args.top]:
            if 'twin' in x:
                print(f'        -  {x["file"]}  ==  {x["twin"]}')
            else:
                kind = ('identical' if x['ratio'] == 1.0
                        else f"{int(x['ratio'] * 100)}% same")
                print(f'    {x["lines"]:5}  {x["file"]:<58} {kind}')

    if identical:
        print(f'\nBYTE-IDENTICAL FILES ({len(identical)}) — a hard fail at any '
              'percentage:')
        for s, f, sib in identical[:40]:
            print(f'  [{s}] {f}  ==  {sib}')
        if len(identical) > 40:
            print(f'  ... and {len(identical) - 40} more')

    print()
    if unmeasured:
        print('UNMEASURED: ' + ', '.join(unmeasured))
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
        print('OK' + (' (on the surfaces measured)' if unmeasured else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
