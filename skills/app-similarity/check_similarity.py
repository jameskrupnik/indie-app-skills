#!/usr/bin/env python3
"""Measure how much one Flutter, React Native or Expo app shares with its siblings.

App Store guideline 4.3(a) rejects apps that share "the same source code or
assets" with apps already submitted and differ only in minor ways, and it names
"a similar binary, metadata, and/or concept". So this measures four surfaces,
not one: a clean source number proves nothing while two apps ship the same
description, screenshot or sound effect.

  source       non-generated Dart (Flutter) or TS/JS (React Native, Expo),
               matched by relative path, near-dupes count
  metadata     fastlane store listing text (.txt), and an Expo app's EAS
               Metadata store.config.json, matched by relative path
  screenshots  fastlane store images, byte-identical, matched on content
  assets       bundled audio/fonts/images/icons, byte-identical, on content
  look         app icon, launch image and in-app splash, by how they look
               (shape hash + palette), so a redrawn look-alike still shows;
               needs Pillow, reported unmeasured without it

Siblings are the directories next to the app (or under --root) that contain a
pubspec.yaml or a package.json naming react-native, whichever stack the app
itself is: a store reviewer compares listings and assets, not frameworks.
Standard library only, except Pillow for `look`; Python 3.9+.

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

try:  # Optional: only the `look` surface needs it, and it says so when missing.
    from PIL import Image, ImageChops
except ImportError:
    Image = ImageChops = None

SURFACES = ('source', 'metadata', 'screenshots', 'assets', 'look')

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
# React Native / Expo source. Platform trees next to package.json are pruned
# for the source surface, like Flutter's; `.d.ts` files are generated or typings.
JS_SUFFIXES = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')
JS_GENERATED = ('.d.ts',)
JS_SKIP = {'dist', 'web-build', 'coverage', 'vendor'}

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
# React Native names the iOS target after the app, so its catalogs are found
# by pattern (ios/<App>/Images.xcassets).
RN_PLATFORM_ASSET_GLOBS = ('ios/*/*.xcassets', 'android/app/src/main/res')
# Xcode asset-catalog manifests. The icon and splash generators write them, so
# they are identical across apps because the tools are. Same for fastlane's
# Framefile.json, which is not a .txt and so never reaches the metadata set.
ASSET_EXCLUDE_NAME = {'contents.json'}


# Published third-party files, by SHA-256, that an app bundles unmodified
# because it needs *that* file: the same reason two apps share a pub package.
# Keyed by exact bytes, not by name, so a custom font renamed `Roboto-*.ttf`
# is still compared, and a different Roboto release shows up until added here.
THIRD_PARTY_ASSET_SHA256 = {
    # Google's Roboto (Apache 2.0), as shipped in Flutter's font cache. Apps
    # embed it for PDF export: `pdf`'s Helvetica lacks common glyphs.
    '79e851404657dac2106b3d22ad256d47824a9a5765458edb72c9102a45816d95': 'Roboto-Regular',
    '7d0b991ee3e0be7af01ad7ea8cd2beea6c00a25e679a0226b6737f079aafff86': 'Roboto-Bold',
    # SIL's Andika (OFL 1.1), byte-for-byte google/fonts ofl/andika/. A
    # beginning-reader face; kids' apps that use it need that exact file, as
    # with a pub package.
    '202b96b1f174a4a43baefe885b40dacacb81786755efd08ed4b7704e79c45515': 'Andika-Regular',
    '4361126189a2d0e0da66999352db58aaf1b4ca940faf8a8239d725f8303d890d': 'Andika-Bold',
}


def _is_third_party(f: pathlib.Path) -> bool:
    if not f.name.lower().endswith(('.ttf', '.otf')):
        return False
    try:
        return hashlib.sha256(f.read_bytes()).hexdigest() in THIRD_PARTY_ASSET_SHA256
    except OSError:
        return False


def _is_placeholder_pixel(f: pathlib.Path) -> bool:
    """True for a 1x1 PNG: a generator's stand-in, not a picture.

    `flutter_native_splash` writes a 69-byte transparent pixel as
    `LaunchImage*.png` whenever the splash is a full-screen background image
    with no centre image, so every app configured that way ships the same
    bytes because the *tool* does, as with `Contents.json`. It flagged nine
    apps as byte-identical over an image nobody can see. Only an exact 1x1 is
    excluded; any real icon or splash is far larger and is still compared.
    """
    if f.suffix.lower() != '.png':
        return False
    try:
        with f.open('rb') as fh:
            head = fh.read(24)
    except OSError:
        return False
    if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        return False
    return int.from_bytes(head[16:20], 'big') == 1 and int.from_bytes(head[20:24], 'big') == 1


def is_rn(app: pathlib.Path) -> bool:
    """A package.json naming react-native, and no pubspec.yaml (which wins)."""
    if (app / 'pubspec.yaml').exists():
        return False
    try:
        pkg = json.loads((app / 'package.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    deps = {**(pkg.get('dependencies') or {}), **(pkg.get('devDependencies') or {})}
    return 'react-native' in deps


def stack_of(app: pathlib.Path) -> str:
    if (app / 'pubspec.yaml').exists():
        return 'flutter'
    if not is_rn(app):
        return ''
    try:
        app_json = json.loads((app / 'app.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        app_json = {}
    pkg = (app / 'package.json').read_text(encoding='utf-8', errors='ignore')
    if ('"expo"' in pkg or 'expo' in app_json
            or (app / 'app.config.js').exists() or (app / 'app.config.ts').exists()):
        return 'expo'
    return 'react-native'


def is_app(d: pathlib.Path) -> bool:
    return (d / 'pubspec.yaml').exists() or is_rn(d)


def _walk(top: pathlib.Path, suffixes: tuple[str, ...],
          prune_platform: bool = False, root_marker: str = 'pubspec.yaml',
          extra_skip: frozenset = frozenset()):
    """Yield files under [top] ending in [suffixes], pruning junk directories."""
    if not top.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(top):
        at_package_root = prune_platform and root_marker in filenames
        dirnames[:] = [
            d for d in dirnames
            if d not in ALWAYS_SKIP and not d.startswith('.')
            and d not in extra_skip
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
    if is_rn(app):
        return js_files(app, cfg)
    files = (f for f in _walk(app, ('.dart',), prune_platform=True)
             if not f.name.endswith(GENERATED_DART))
    return _rel(app, files, cfg.ignore)


def js_files(app, cfg) -> dict[str, pathlib.Path]:
    """TS/JS source of a React Native or Expo app: src/, app/ (expo-router),
    root files like App.tsx; never node_modules, build output or ios/android."""
    files = (f for f in _walk(app, JS_SUFFIXES, prune_platform=True,
                              root_marker='package.json',
                              extra_skip=frozenset(JS_SKIP))
             if not f.name.endswith(JS_GENERATED))
    return _rel(app, files, cfg.ignore)


class StoreConfigText:
    """One text field of an EAS Metadata store.config.json, read like a file."""

    def __init__(self, text: str):
        self.text = text
        self.name = ''

    def read_text(self, encoding='utf-8'):
        return self.text

    def read_bytes(self):
        return self.text.encode('utf-8')


# EAS Metadata fields that are listing copy; title and URLs are left out for
# the reasons META_EXCLUDE_* gives, and `review` like review_information/.
STORE_CONFIG_FIELDS = {'subtitle': 'subtitle.txt', 'description': 'description.txt',
                       'keywords': 'keywords.txt', 'releaseNotes': 'release_notes.txt',
                       'promoText': 'promotional_text.txt'}
STORE_CONFIG_PREFIX = 'store.config.json#'


def store_config_files(app) -> dict[str, StoreConfigText]:
    """Keyed `store.config.json#<locale>/<fastlane name>`, so canon() can
    match them against a sibling's fastlane/metadata/<locale>/<name>."""
    try:
        data = json.loads((app / 'store.config.json').read_text(encoding='utf-8'))
        info = (data.get('apple') or {}).get('info') or {}
    except (OSError, ValueError, AttributeError):
        return {}
    out = {}
    for locale, fields in sorted(info.items()):
        if not isinstance(fields, dict):
            continue
        for key, fname in STORE_CONFIG_FIELDS.items():
            v = fields.get(key)
            if isinstance(v, list):
                v = ','.join(str(x) for x in v)
            if isinstance(v, str) and v.strip():
                out[f'{STORE_CONFIG_PREFIX}{locale}/{fname}'] = StoreConfigText(v)
    return out


def canon(rel: str) -> str:
    """Match key for a metadata file: EAS Metadata fields compare as the
    fastlane deliver file they correspond to. Identity for everything else."""
    if rel.startswith(STORE_CONFIG_PREFIX):
        return 'fastlane/metadata/' + rel[len(STORE_CONFIG_PREFIX):]
    return rel


def meta_files(app, cfg) -> dict[str, pathlib.Path]:
    """Store listing copy a reviewer reads as a description of this app."""
    files = (f for d in cfg.fastlane for f in _walk(app / d / 'metadata', ('.txt',)))
    out = _rel(app, files, cfg.ignore)
    out = {k: v for k, v in out.items()
           if not any(x in k.lower() for x in META_EXCLUDE_PATH)
           and v.name.lower() not in META_EXCLUDE_NAME}
    if is_rn(app):
        have = {canon(k) for k in out}
        for k, v in store_config_files(app).items():
            if canon(k) not in have and not any(fnmatch.fnmatch(k, g)
                                                for g in cfg.ignore):
                out[k] = v
    return out


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
    if is_rn(app):
        tops = [p for g in RN_PLATFORM_ASSET_GLOBS for p in sorted(app.glob(g))]
        tops += [app / d for d in cfg.asset_dir]
    else:
        tops = [app / d for d in (*PLATFORM_ASSET_DIRS, *cfg.asset_dir)]
    for dirpath, dirnames, _ in os.walk(app):
        dirnames[:] = [d for d in dirnames
                       if d not in ALWAYS_SKIP and not d.startswith('.')]
        if pathlib.Path(dirpath).name == ASSET_DIR_NAME:
            tops.append(pathlib.Path(dirpath))
            dirnames[:] = []
    files = (f for t in tops for f in _walk(t, ASSET_SUFFIXES)
             if f.name.lower() not in ASSET_EXCLUDE_NAME
             and not _is_placeholder_pixel(f) and not _is_third_party(f))
    return _rel(app, files, cfg.ignore)


def _look_candidates(app: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    """Where each picture a reviewer sees first lives, most preferred first."""
    if is_rn(app):
        icon = sorted(app.glob('ios/*/Images.xcassets/AppIcon.appiconset/*.png'))
        launch = sorted(app.glob('ios/*/Images.xcassets/SplashScreen*.imageset/*.png'))
    else:
        icon = sorted(app.glob('ios/Runner/Assets.xcassets/AppIcon.appiconset/*.png'))
        launch = sorted(app.glob('ios/Runner/Assets.xcassets/LaunchImage.imageset/*.png'))
    icon = icon or sorted(app.glob('android/app/src/main/res/mipmap-*/ic_launcher.png'))
    launch = launch or sorted(app.glob('android/app/src/main/res/drawable*/splash.png'))
    in_app = [p for p in (app / 'assets/splash/splash.png',) if p.exists()]
    return {'icon': icon, 'launch image': launch, 'in-app splash': in_app}


def look_files(app, cfg) -> dict[str, pathlib.Path]:
    """The app icon and the splash images, keyed by role, largest file each.

    Compared by how they look, not by bytes: a redrawn icon with the same
    window, the same palette and the same composition is a new file to
    sha256 and the same picture to a reviewer scrolling the developer's apps.
    """
    if Image is None:
        return {}
    out = {}
    for role, files in _look_candidates(app).items():
        best, area = None, 1
        for f in files:
            if any(fnmatch.fnmatch(f.relative_to(app).as_posix(), g)
                   for g in cfg.ignore):
                continue
            try:
                with Image.open(f) as im:
                    a = im.size[0] * im.size[1]
            except OSError:
                continue
            if a > area:            # skips the generator's 1x1 placeholder
                best, area = f, a
        if best is not None:
            out[role] = best
    return out


def _subject(path: pathlib.Path):
    """The picture's subject on a neutral ground, stretched to 64x64.

    A splash is mostly flat background, and a flat area hashes the same in
    every app, so two unrelated splash logos would read as alike. Cropping to
    what differs from the background compares the logos themselves.
    """
    im = Image.open(path).convert('RGBA')
    alpha = im.getchannel('A')
    if alpha.getextrema()[0] < 250:                      # has transparency
        box = alpha.point(lambda v: 255 if v > 16 else 0).getbbox()
        ground = Image.new('RGBA', im.size, (128, 128, 128, 255))
        im = Image.alpha_composite(ground, im)
    else:
        rgb = im.convert('RGB')
        bg = Image.new('RGB', im.size, rgb.getpixel((0, 0)))
        diff = ImageChops.difference(rgb, bg).convert('L')
        box = diff.point(lambda v: 255 if v > 24 else 0).getbbox()
    im = im.convert('RGB')
    if box and (box[2] - box[0]) * (box[3] - box[1]) > im.size[0] * im.size[1] * 0.02:
        im = im.crop(box)
    # Stretched, not padded: padding a tall phone splash to a square adds two
    # identical grey bars to every one, and the bars alone read as a match.
    return im.resize((64, 64), Image.LANCZOS)


def _pixels(im) -> list:
    """Pillow 12 deprecates getdata(); its replacement is new in 12."""
    get = getattr(im, 'get_flattened_data', None) or im.getdata
    return list(get())


def _dhash(im) -> int:
    """128-bit gradient hash, rows and columns: the picture's shape."""
    g = im.convert('L')
    h = _pixels(g.resize((9, 8), Image.LANCZOS))
    v = _pixels(g.resize((8, 9), Image.LANCZOS))
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (h[y * 9 + x] > h[y * 9 + x + 1])
            bits = (bits << 1) | (v[y * 8 + x] > v[(y + 1) * 8 + x])
    return bits


def _palette(im) -> list[float]:
    """Share of pixels in each of 512 colour bins: the picture's palette.

    Eight levels a channel, not four: at four, dark teal and dark navy fall in
    the same bin and two unrelated dark splashes read as one palette.
    """
    counts = [0] * 512
    for r, g, b in _pixels(im.resize((32, 32), Image.LANCZOS)):
        counts[(r >> 5) * 64 + (g >> 5) * 8 + (b >> 5)] += 1
    return [c / 1024 for c in counts]


def look_signature(path: pathlib.Path):
    im = _subject(path)
    return _dhash(im), _palette(im)


def look_similarity(a, b) -> tuple[float, float]:
    """(shape, palette), each 0-1. Unrelated pictures sit near 0.5 on shape."""
    shape = 1 - bin(a[0] ^ b[0]).count('1') / 128
    palette = sum(min(x, y) for x, y in zip(a[1], b[1]))
    return shape, palette


def look_alike(shape: float, palette: float) -> bool:
    """Thresholds calibrated on ~190 images from ~115 apps: see SKILL.md."""
    return shape >= LOOK_SHAPE or (shape >= LOOK_SHAPE_WITH_PALETTE
                                   and palette >= LOOK_PALETTE)


LOOK_SHAPE = 0.9
LOOK_SHAPE_WITH_PALETTE = 0.75
LOOK_PALETTE = 0.4


def compare_look(mine, theirs) -> list[dict]:
    """Same role (icon to icon, splash to splash) and across roles, since a
    fork's splash is often its parent's icon."""
    sigs = {}

    def sig(p):
        if p not in sigs:
            try:
                sigs[p] = look_signature(p)
            except OSError:
                sigs[p] = None
        return sigs[p]

    out = []
    for role, path in mine.items():
        best = None
        for their_role, their_path in theirs.items():
            a, b = sig(path), sig(their_path)
            if a is None or b is None:
                continue
            shape, palette = look_similarity(a, b)
            if look_alike(shape, palette) and (best is None or shape > best['shape']):
                best = {'file': role, 'twin': their_role, 'lines': 0,
                        'shape': round(shape, 2), 'palette': round(palette, 2),
                        'ratio': 1.0 if a == b else min(round(shape, 3), 0.999)}
        if best:
            out.append(best)
    return out


COLLECTORS = {'source': dart_files, 'metadata': meta_files,
              'screenshots': image_files, 'assets': asset_files,
              'look': look_files}


def rn_names(app: pathlib.Path) -> set[str]:
    """package.json name, and app.json's expo name and slug."""
    out: set[str] = set()
    for f, keys in (('package.json', (('name',),)),
                    ('app.json', (('expo', 'name'), ('expo', 'slug'), ('name',)))):
        try:
            data = json.loads((app / f).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for path in keys:
            v = data
            for k in path:
                v = v.get(k) if isinstance(v, dict) else None
            if isinstance(v, str) and re.fullmatch(r'[\w\- ]+', v):
                out.add(v.strip())
    return out


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
    bases = {pubspec_name(app), app.name}
    if is_rn(app):
        bases |= rn_names(app)
    for base in filter(None, bases):
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
    if any(s in ('test', 'test_driver', 'integration_test', 'tool',
                 '__tests__', '__mocks__')
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
    theirs = {canon(k): v for k, v in theirs.items()}
    for rel, path in mine.items():
        twin = theirs.get(canon(rel))
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
        elif s == 'look':
            shared = compare_look(mine, theirs)
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


def git_repo_of(d: pathlib.Path) -> pathlib.Path | None:
    """The repository a checkout belongs to, shared by all its worktrees.

    A worktree's `.git` is a file reading `gitdir: <repo>/.git/worktrees/<n>`;
    the main checkout's is the `.git` directory itself.
    """
    g = d / '.git'
    if g.is_dir():
        return g.resolve()
    if g.is_file():
        line = g.read_text(errors='replace').strip()
        if line.startswith('gitdir:'):
            p = pathlib.Path(line[len('gitdir:'):].strip())
            p = (d / p).resolve() if not p.is_absolute() else p.resolve()
            if p.parent.name == 'worktrees':
                return p.parent.parent
            return p
    return None


def find_siblings(app, root, only, exclude):
    """Sibling apps under root, one per repository.

    A git worktree is a second checkout of one app, not a sibling: comparing
    against it reports the app as a copy of itself. Worktrees of the app's own
    repo are skipped, and another repo's worktrees collapse to its main
    checkout (or its first worktree when the main one is not under root).
    """
    mine = git_repo_of(app)
    out, seen = [], {}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.resolve() == app:
            continue
        if not is_app(d):
            continue
        if only and d.name not in only:
            continue
        if any(fnmatch.fnmatch(d.name, g) for g in exclude):
            continue
        repo = git_repo_of(d)
        if repo is not None and not only:
            if repo == mine:
                continue
            if repo in seen:
                if (d / '.git').is_dir():
                    out[seen[repo]] = d.resolve()
                continue
            seen[repo] = len(out)
        out.append(d.resolve())
    return out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.split('\n\n')[0] + ' Reports four surfaces '
        '(source, metadata, screenshots, assets, look) against every sibling app, '
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
                    'pubspec.yaml or a React Native package.json)')
    ap.add_argument('--exclude', action='append', default=[], metavar='GLOB',
                    help='skip sibling dirs whose name matches, e.g. '
                    '"*-webdemo" or a plugin package; repeatable')
    ap.add_argument('--alias', action='append', default=[], metavar='WORD',
                    help='domain word to normalise away in text, e.g. '
                    '--alias candy; repeatable')
    ap.add_argument('--surface', action='append', default=[], choices=SURFACES,
                    help='limit to a surface; repeatable (default: all five)')
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
    if not is_app(app):
        print(f'error: {app} has no pubspec.yaml or React Native package.json '
              '— not a Flutter, React Native or Expo app', file=sys.stderr)
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
        print(f'error: no sibling apps with a pubspec.yaml or React Native '
              f'package.json under {root}', file=sys.stderr)
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
            'app': app.name, 'stack': stack_of(app), 'root': str(root),
            'threshold': args.threshold,
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
            if s == 'look' and Image is None:
                print('  NOT MEASURED — needs Pillow (pip install Pillow).')
            else:
                print('  NOTHING TO COMPARE — this app has no files on this '
                      'surface, so it is\n  unmeasured, not clean.')
            continue
        rows = [r for r in sorted(results,
                                  key=lambda r: -r['surfaces'][s]['percent'])
                if r['surfaces'][s]['shared_files']]
        if not rows:
            print('  no sibling looks alike' if s == 'look' else
                  '  no sibling shares a file on this surface')
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
            if 'shape' in x:
                print(f'        -  {x["file"]}  looks like  {sib}\'s {x["twin"]}'
                      f'  (shape {int(x["shape"] * 100)}%, palette '
                      f'{int(x["palette"] * 100)}%)')
            elif 'twin' in x:
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
