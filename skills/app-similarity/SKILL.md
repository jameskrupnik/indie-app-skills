---
name: app-similarity
description: Measure how much a Flutter, React Native or Expo app shares with its sibling apps (source, store listing text, screenshots, bundled assets like audio, fonts and icons, and the shapes of its screens: the same menu, title bar, list and stats layouts in a new colour) before submitting it to the App Store or Google Play. Use when about to submit, resubmit or fork an app that shares a template or code with other apps on the same developer account; when a rejection mentions guideline 4.3, 4.3(a), "spam", "similar binary", "repackaged template", "same source code or assets" or "minimum functionality"; or when asked how similar two apps are, whether an app is too close to another, whether its screens or interface look like a sibling's, or to check similarity, overlap or duplication across several apps.
---

# App similarity check

One developer account shipping several apps cut from the same template runs
into Apple's guideline 4.3(a): apps that share "the same source code or
assets" with others already submitted and differ only in minor ways get
rejected, and repeated rejections escalate to the whole account. **The number
is invisible without measuring it** — apps that get rejected this way often
look different on screen. And the reverse is just as real: an app can differ
on every file and still **look** like its sibling, because its screens have
the same shapes. Both halves are below: the measured surfaces, then the
screens sheet, which is read by eye.

## Quick start

```bash
python3 ${CLAUDE_SKILL_DIR}/check_similarity.py --alias candy --alias fruit
```

Run it from the app you are about to submit. Siblings are every directory next
to it that has a `pubspec.yaml` or a `package.json` naming `react-native`,
whatever the app's own stack: a reviewer compares listings and assets, not
frameworks, so a React Native port of a Flutter app is measured against it.
Standard library only, Python 3.9+, except the `look` surface and
`screens_sheet.py`, which need Pillow (`python3 -m pip install Pillow`);
without it `look` is reported unmeasured.

**Exit codes:** `0` clear; `1` any surface at or above the threshold (default
**30%**), or any metadata, screenshot or asset file byte-identical to a
sibling's; `2` usage error (no `pubspec.yaml` or React Native `package.json`,
bad `--root`, no siblings).

| Flag | Use |
|---|---|
| `--alias WORD` | a domain noun to normalise away — see below; repeatable |
| `--app DIR` `--root DIR` | check something other than the cwd / its parent |
| `--sibling NAME` | compare against only these sibling dirs; repeatable |
| `--exclude GLOB` | skip sibling dirs by name, e.g. `'*-webdemo'`; repeatable |
| `--surface S` | `source`, `metadata`, `screenshots`, `assets`; repeatable, default all |
| `--threshold N` | fail at or above N% (default 30) |
| `--near R` | a text file counts as shared at or above this ratio (default 0.9) |
| `--fastlane DIR` | where fastlane lives (default `fastlane`, `ios/fastlane`, `android/fastlane`) |
| `--asset-dir DIR` | extra bundled-asset dir to scan; repeatable |
| `--ignore GLOB` | drop matching app-relative paths on every surface; printed in the report |
| `--json` | machine-readable, for a hook or CI |

**Always pass `--alias` for the app's domain nouns** (the fruit, the taco, the
pie) **and for the fork parent's** (the ball, the table). App names are
normalised automatically from each `pubspec.yaml` (or `package.json` name and
`app.json` expo name/slug) and directory name, in every
casing (`fruit_drop`, `FruitDrop`, `Fruit Drop`), but domain words are not. Two
files identical except for `s/taco/candy/` count as *different* without them,
which understates sharing — the direction that lets a bad app through.

**Exclude anything under the root that is a copy of the app itself** — a web
demo, a backup, a plugin package — or it will read 100% and bury the real
siblings.

### What it assumes about layout

- Each app is a directory with a `pubspec.yaml` or a React Native
  `package.json`, and siblings are the direct children of one root. Nested layouts need `--root` pointed at the right level.
- Store copy and screenshots are in fastlane's layout (`metadata/`,
  `screenshots/`, with Play images under `metadata/android/<locale>/images/`).
  An Expo app's EAS Metadata `store.config.json` (App Store fields) is read
  too, each field compared as the fastlane file it corresponds to
  (`description` as `metadata/<locale>/description.txt`), so a copied listing
  is caught across the two layouts. Without either, those two surfaces report
  `NOTHING TO COMPARE`.
- Bundled assets are every directory named `assets` (monorepo packages
  included), `android/app/src/main/res`, and `ios/Runner/Assets.xcassets`
  (Flutter) or `ios/<App>/*.xcassets` (React Native). A managed Expo app with
  no `ios/`/`android/` is measured on `assets/` alone.

## The five surfaces, and why there are five

4.3(a)'s wording is "the same source code **or assets**" and "a similar
binary, **metadata**, and/or **concept**", so a clean source number proves
nothing on its own.

- **source** — non-generated Dart (Flutter) or `.ts`/`.tsx`/`.js`/`.jsx`
  (React Native, Expo: `src/`, expo-router's `app/`, root files like
  `App.tsx`), matched by relative path; a file counts if
  it is identical after normalisation or at least `--near` the same.
- **metadata** — store listing `.txt` under `fastlane/metadata`: subtitle,
  keywords, promotional text, description, release notes, TestFlight notes,
  and Play's short/full descriptions and changelogs. Matched by path.
- **screenshots** — store images, **byte-identical only**, matched on content
  rather than path, because a copied screenshot gets renamed to suit the new
  app's scene order.
- **assets** — what the binary ships that is not code or store copy: sound
  effects, fonts, and the generated icon and launch images on both platforms.
  Byte-identical, on content, for the same reason — **and this is the surface
  where renaming is the norm, not the exception.**

- **look** — the app icon, the launch image and the in-app splash
  (`assets/splash/splash.png`), compared by **how they look**, not by bytes.
  Each is cropped to its subject (what differs from the background, or the
  opaque part of a transparent image), stretched to 64x64, and scored two
  ways: **shape**, a 128-bit gradient hash (rows and columns), and
  **palette**, the overlap of 512-bin colour histograms. Icons are compared
  with the sibling's icon *and* splash, since a fork's splash is often its
  parent's icon. Needs Pillow; without it the surface is reported unmeasured.

Why look matters: a redrawn icon is a new file to sha256 and the same picture
to a reviewer scrolling the developer's other apps. A 4.3(a) rejection can
land on an app whose files are all new but whose icon is its sibling's,
redrawn.

**Look-alike rule:** shape ≥ 0.90 on its own, or shape ≥ 0.75 with palette ≥
0.40 (`LOOK_*` constants). Calibrated on ~190 images from ~115 apps (about
17,000 pairs): unrelated pairs sit at a median shape of 0.52, p99 0.81. It
flags two client-demo apps with the same letter icon (0.95) and two
coin-on-navy icons (0.77 shape, 0.56 palette), which a person also reads as
one family. The next pair down is 0.72/0.20. Two traps
found while calibrating: padding a tall splash to a square gave every splash
the same grey bars, which matched (now stretched instead), and at 64 colour
bins dark teal and dark navy were one colour (now 512). Re-calibrate before
moving a threshold: a shape-only match below 0.9 came from round badges in
unrelated colours (0.80, palette 0).

Why assets matter: a forked sound generator produces the same bytes in every
repo, so one `.wav` can ship in five apps under five names (`level_up`,
`cleared`, `race_won`...). And a template's **branded launch image can survive
in every fork**: `flutter_native_splash` writes the density buckets
(`drawable-hdpi/` and friends) but never the bare `drawable/splash.png`, so if
the template had one and `launch_background.xml` references it, regenerating
the splash never replaces it.

Why metadata matters: a copied listing is invisible to any source check. The
real case this was built for shared 76% of its listing with a sibling —
byte-identical descriptions in two locales, still describing the other app.

**An empty surface is reported as unmeasured, not as a pass.** No screenshots
captured prints `NOTHING TO COMPARE` and `UNMEASURED`, not 0%, because a silent
zero reads as "checked and clean" when nothing was checked.

### What each surface excludes, and why

Excluding the wrong thing hides a real finding; excluding nothing buries it.

- **source**: generated files (`*.g.dart`, `*.freezed.dart`, `*.config.dart`,
  `*.gr.dart`, `*.mocks.dart`; `*.d.ts`), platform directories next to a
  `pubspec.yaml` or `package.json`, and `build/`, `.dart_tool/`, `Pods/`,
  `node_modules/`, `.expo/`, `dist/`. Across stacks the source surface is
  always 0%: Dart and TypeScript never share a path.
- **metadata**: `review_information/` (contact details and review notes; in
  `store.config.json`, `apple.review`),
  `copyright.txt` and `*_url.txt`. One publisher's support address, privacy
  policy and marketing site are identical on every app they ship, for the same
  reason the logger is; left in, they put a permanent 33% on three URL files.
- **metadata**: `title.txt` and `name.txt` (and `store.config.json` titles),
  for a sharper reason — **the
  normaliser makes them match unconditionally.** Their whole content is the
  app's name, which normalises to `X`, so any two titles read as identical.
  Compare titles by eye.
- **assets**: `Contents.json`, the Xcode asset-catalog manifests. The icon and
  splash tools write them, so they are identical because the *tools* are.
  Three entries that always mean nothing are how the one that means something
  gets skimmed past.
- **assets**: any **1x1 PNG**. `flutter_native_splash` writes a 69-byte
  transparent pixel as `LaunchImage*.png` whenever the splash is a
  full-screen background with no centre image, so nine apps read as
  byte-identical over an image nobody can see. Only an exact 1x1 is dropped.
- **assets**: published third-party fonts, by **SHA-256** in
  `THIRD_PARTY_ASSET_SHA256` (Google's Roboto, embedded for PDF export).
  Identical because the app needs that exact file, as with a pub package.
  Matched on bytes, not names: a custom font renamed `Roboto-*.ttf` is still
  compared. Add a hash only for an unmodified upstream release, with its
  source and licence in the comment.

`--ignore` exists for the same reason, but everything it drops is listed in
the report. Use it for things that are genuinely not yours to vary, such as an
open-source font family, and name the files, not whole directories.

## Reading the result

The percentage alone is not a decision. For source, the tool splits what is
shared by path keywords:

- **infrastructure** — logging, crash reporting, analytics, ads, DI, router,
  i18n, `main.dart`, tests (`__tests__/` included) and tooling. Identical because it does an identical
  job. **Expected, and fine.** Two apps by one developer both having a crash
  reporter is not what 4.3 prohibits.
- **app scaffolding** — blocs/cubits, screens, widgets, pages, models,
  repositories. Identical because the *app shape* is identical: splash → menu
  → list → session → stats. This is the real surface, and usually the bulk.
- **other** — everything else. Read the file list.

Then read the largest shared files by name. A shared `crash_reporter.dart` is
nothing. A shared `game_state.dart` or `round_summary_card.dart` is the two
apps being the same app with different art.

**The byte-identical list covers metadata, screenshots and assets, and
excludes source deliberately.** An identical logger or i18n barrel is what
shared infrastructure looks like; including source put hundreds of entries
under a heading that is supposed to mean "somebody copied something". There is
no job two apps share that requires the same store text, screenshot or sound
effect.

## Screens: the shape check, read by eye

The surfaces above compare files. None of them can say that two apps open on
the same *screen shape*: one wide accent button over a grid of nav tiles, a
back-arrow title bar on every inner screen, a column of rounded coloured rows,
a grid of number-over-label tiles. A reviewer scrolling the developer's other
apps sees those first, and a new palette does not hide them. Measured on a
real app: its source, listing, icon, palette and art were all its
own, and four screen shapes were still shared with three siblings.

```bash
python3 ${CLAUDE_SKILL_DIR}/screens_sheet.py \
    [--exclude GLOB ...] [--sibling NAME ...] [--rows 8]
```

It finds each app's screens (raw captures under `build/screenshots/raw`
first, then store images), ranks siblings by a layout hash, and draws
`build/similarity/screens.png`: this app on the top row, the closest siblings
under it. **Pass `--sibling` for the fork parent and every app cut from the
same template**: the hash ranks on light and dark more than on shape, so the
sibling that matters may not be in the top rows.

**Then read the sheet** against
[references/screen-shapes.md](references/screen-shapes.md), which lists the
shapes that give a template away and what counts as a fix. The script never
fails a run: its ranking is uncalibrated and points at where to look. A
sibling with no screens to find is printed as UNMEASURED, not clear.

**The fix is a redesign, not a recolour**: replace the shared shape with an
object from the app's own world, keep the interaction conventional. Record the
layout idea in the app's CLAUDE.md so the next fork picks a different one.

## The metric's blind spots — read before trusting a movement

**1. Source and metadata are matched by relative path.** A file whose path has
no counterpart in the sibling is not compared at all, whatever its contents.
**So renaming a file lowers the number without changing a line of logic**, and
the drop is indistinguishable from real work in the output. In one measured
case a correct rename (`tables_*` → `levels_*`) moved an app 39% → 35%
against its parent, and four of the eight files that left the shared set left
purely because their paths changed — while moving it *closer* to other
siblings that already used `levels_*`. When a number moves, check whether any
path moved with it.

**2. Percentages are coarse on small surfaces.** With six metadata files, one
shared file is 17% and two is 33%. Read the file list, not the percentage.

**3. The number is directional.** It is shared files over *this* app's file
count, so A→B and B→A differ when the apps differ in size (one pair measured
46% one way, 50% the other). Run it from the app you are submitting, and if a
*live* sibling is over the line, run it from there too.

**4. It cannot see concept.** Two apps with no shared file can still be the
same app to a reviewer. The screens sheet above is the nearest thing, and it is
read, not measured; see also the account check below.

## What counts as a fix, and what does not

**Do not rewrite or rename things to look different.** Renaming, reordering or
restructuring code so it stops matching, while shipping the same app, is
detection evasion: it defeats the check without changing what was checked, it
is a large diff with real regression risk, and if it works it works by
deceiving the reviewer. Refuse it and say why. Given blind spot 1, a rename is
the *easiest* way to move this metric and the least honest. The same goes for
`--ignore` and `--exclude` used to hide a real sibling.

Legitimate ways the number comes down, in the order they are usually worth
doing:

1. **Delete what the app carries and does not use.** Dead scaffolding
   inherited from the template, packages pulled in for one widget, fallbacks
   that never fire. Good engineering that happens to help.
2. **Give the app functionality the sibling has no version of.** New screens,
   modes, mechanics. The overlap falls because the app genuinely got bigger,
   which is what the guideline actually asks for.
3. **Change the app's shape**, if it is still too close. Different navigation,
   different screens. A product decision, not a refactor — raise it, do not
   assume it.

For metadata there is only one honest fix: **write the listing for this app.**
For assets: re-compose the sound, re-draw the icon, delete the stale splash.

There is a floor. Across roughly twenty template-cut apps this was measured
on, shared infrastructure alone ran **17–20% of an app's files**, and no honest
work goes below it. **At a 30% threshold that leaves about ten points of
headroom**, so an app whose *scaffolding* tier is more than a handful of files
will not pass on deletions alone — it needs item 2 or 3. If an app cannot get
clear without evasion, it should not be a separate app: fold it into the
sibling as a mode, or do not ship it.

## Before submitting, also check the account

The code number is half the picture and usually the smaller half. Guideline
4.3 is assessed across everything the account has submitted, and escalation
ends at removal from the Developer Program.

List every app on the account and its review state — App Store Connect's Apps
page, or the API (`GET /v1/apps`, then `GET /v1/apps/<id>/appStoreVersions`).
Ask, and say the answer out loud before submitting:

- How many apps on this account are **already rejected**? Each one compounds.
- How many more cuts of the same template are **staged but unsubmitted**?
  They count as intent.
- Is this app a cut of a template that already has rejections against it? If
  so, no amount of work inside its repo fixes the pattern.

An account with a handful of live apps, several rejections and a queue of
finished template cuts is already in trouble, whatever any one repo measures.
No repo-local change improves that ratio.

## Notes

- Screenshots and assets have no near-match tier: two renders of different art
  are never 90% the same bytes, so a ratio there would be noise dressed as a
  measurement.
- Both apps in a pair are normalised with the union of their names and your
  aliases. Normalising each side with only its own name is asymmetric: an app
  named `color-lab` would turn its own `label` into `Xel` while the sibling's
  stays `label`, understating sharing everywhere the word appears.
- The normaliser replaces the longest token first. That is load-bearing: with
  `fruit` matched before `fruit_drop`, the package name `fruit_drop_ui`
  normalises to `X_drop_ui` and every file differing only by its package
  name reads as different — enough to understate a real measurement by four
  points.
