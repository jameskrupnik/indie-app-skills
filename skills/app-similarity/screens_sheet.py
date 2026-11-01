#!/usr/bin/env python3
"""Put an app's screens next to its siblings' screens, for a person to read.

The look surface in check_similarity.py compares icons and splash images. It
cannot say whether two apps share a *screen shape*: the same primary button
over a grid of nav tiles, the same back-arrow title bar, the same list of
rounded coloured rows, the same grid of number tiles. A reviewer sees those
first, in the screenshots, and a palette change does not hide them.

This script does not decide anything. It finds each app's screens, ranks the
siblings by how close their screens' layout hashes come to this app's, and
draws one contact sheet: this app on the top row, the closest siblings below.
Read the sheet against references/screen-shapes.md.

The ranking is a pointer to where to look, not a verdict. It hashes whole
screens at 64x64, so two dark screens with a bar at the top score alike
whatever is in them, and a redesign with a new metaphor can score close
because it kept the dark ground. It has not been calibrated the way the icon
thresholds were, so it never fails a run.

Usage (from the app's directory, or with --app):
    python3 screens_sheet.py [--app DIR] [--root DIR] [--rows 8]
        [--per-app 5] [--sibling NAME ...] [--exclude GLOB ...] [--out PNG]

Needs Pillow.
"""
from __future__ import annotations

import argparse
import fnmatch
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from check_similarity import _dhash, find_siblings, is_app  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    sys.exit('screens_sheet.py needs Pillow: python3 -m pip install Pillow')


def _numbered(folder: pathlib.Path) -> list[pathlib.Path]:
    """The scene captures in a folder, in order, without a failed scene's frame."""
    return sorted(
        p for p in folder.glob('*.png')
        if p.name[:2].isdigit() and not p.name.startswith('99_')
    )


def _tall(p: pathlib.Path) -> bool:
    with Image.open(p) as im:
        return im.height > im.width


def screens_of(app: pathlib.Path, per_app: int) -> list[pathlib.Path]:
    """An app's phone screens, rawest first.

    Raw captures beat store images: a store image carries a caption band and
    a device frame, which every app composed by one script shares, and which
    would make every listing look alike to the hash.
    """
    raw = app / 'build' / 'screenshots' / 'raw'
    if raw.is_dir():
        folders = sorted({p.parent for p in raw.rglob('*.png')})
        # Phones first: an iPhone or Android phone folder over a tablet one.
        folders.sort(key=lambda f: (
            not any(k in str(f).lower() for k in ('iphone', 'phone', 'pixel')),
            str(f)))
        for f in folders:
            shots = [p for p in _numbered(f) if _tall(p)]
            if shots:
                return shots[:per_app]
    for rel in (
        'fastlane/metadata/android/en-US/images/phoneScreenshots',
        'fastlane/screenshots/en-US',
    ):
        shots = _numbered(app / rel) or sorted((app / rel).glob('*.png'))
        if shots:
            return shots[:per_app]
    store = app / 'screenshots'
    if store.is_dir():
        for f in sorted({p.parent for p in store.rglob('*.png')}):
            shots = [p for p in sorted(f.glob('*.png')) if _tall(p)]
            if shots:
                return shots[:per_app]
    return []


def _layout_hash(p: pathlib.Path) -> int:
    with Image.open(p) as im:
        return _dhash(im.convert('RGB').resize((64, 64), Image.LANCZOS))


def _shape(a: int, b: int) -> float:
    return 1 - bin(a ^ b).count('1') / 128


def _font(size: int):
    for path in ('/System/Library/Fonts/Supplemental/Arial Bold.ttf',
                 '/System/Library/Fonts/Helvetica.ttc',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_sheet(rows, out: pathlib.Path, height: int = 420) -> None:
    """One row per app: its name, then its screens at a common height."""
    label_w, gap = 260, 12
    widths = []
    for _, shots, _ in rows:
        w = 0
        for p in shots:
            with Image.open(p) as im:
                w += int(im.width * height / im.height) + gap
        widths.append(w)
    sheet = Image.new('RGB', (label_w + max(widths + [1]),
                              len(rows) * (height + gap) + gap), 'white')
    draw = ImageDraw.Draw(sheet)
    font, small = _font(26), _font(20)
    y = gap
    for name, shots, score in rows:
        draw.text((12, y + 10), name, fill='black', font=font)
        if score is not None:
            draw.text((12, y + 46), f'closest layout {score:.2f}',
                      fill='#555', font=small)
        x = label_w
        for p in shots:
            with Image.open(p) as im:
                im = im.convert('RGB')
                w = int(im.width * height / im.height)
                sheet.paste(im.resize((w, height), Image.LANCZOS), (x, y))
            x += w + gap
        y += height + gap
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--app', default='.')
    ap.add_argument('--root')
    ap.add_argument('--rows', type=int, default=8,
                    help='siblings to draw under this app (default 8)')
    ap.add_argument('--per-app', type=int, default=5)
    ap.add_argument('--sibling', action='append', default=[],
                    help='always draw this sibling; repeatable')
    ap.add_argument('--exclude', action='append', default=[])
    ap.add_argument('--out', help='default build/similarity/screens.png')
    args = ap.parse_args(argv)

    app = pathlib.Path(args.app).resolve()
    if not is_app(app):
        print(f'error: {app} is not an app directory', file=sys.stderr)
        return 2
    root = pathlib.Path(args.root).resolve() if args.root else app.parent
    mine = screens_of(app, args.per_app)
    if not mine:
        print('error: no screens found. Capture them first '
              '(flutter-store-screenshots), then run this again.',
              file=sys.stderr)
        return 2
    my_hashes = [_layout_hash(p) for p in mine]

    ranked = []
    for sib in find_siblings(app, root, [], args.exclude):
        shots = screens_of(sib, args.per_app)
        if not shots:
            continue
        best, pair = 0.0, None
        for p in shots:
            h = _layout_hash(p)
            for q, mh in zip(mine, my_hashes):
                s = _shape(mh, h)
                if s > best:
                    best, pair = s, (q.name, p.name)
        ranked.append((best, sib.name, shots, pair))
    ranked.sort(key=lambda r: -r[0])

    chosen = ranked[:args.rows]
    for r in ranked[args.rows:]:
        if any(fnmatch.fnmatch(r[1], g) for g in args.sibling):
            chosen.append(r)

    print(f'{app.name}: {len(mine)} screens; {len(ranked)} siblings have screens')
    print('closest layouts (advisory, uncalibrated; read the sheet):')
    for best, name, _, pair in chosen:
        print(f'  {best:.2f}  {name:<28} {pair[0]} ~ {pair[1]}')
    unmeasured = [d.name for d in find_siblings(app, root, [], args.exclude)
                  if not screens_of(d, 1)]
    if unmeasured:
        print(f'{len(unmeasured)} siblings have no screens to compare '
              '(UNMEASURED, not clear): ' + ', '.join(unmeasured[:12])
              + (' ...' if len(unmeasured) > 12 else ''))

    out = pathlib.Path(args.out) if args.out else (
        app / 'build' / 'similarity' / 'screens.png')
    draw_sheet([(app.name, mine, None)]
               + [(n, s, b) for b, n, s, _ in chosen], out)
    print(f'sheet: {out}')
    print('Next: read the sheet against references/screen-shapes.md.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
