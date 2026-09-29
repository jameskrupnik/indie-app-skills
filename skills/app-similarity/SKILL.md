---
name: app-similarity
description: Measure how much an app shares with its sibling apps — source, store metadata, screenshots and bundled assets (audio, fonts, icons) — before submitting it to the App Store or Google Play. Use when about to submit, resubmit or create an app that shares a template or code with other apps on the same developer account; when a rejection mentions guideline 4.3, "spam", "similar binary", "repackaged template" or "minimum functionality"; or when asked how similar two apps are, whether an app is too close to another, or to check similarity/overlap/duplication across the app portfolio.
---

# App similarity check

One developer account ships many apps cut from the same templates. Apple's
guideline 4.3(a) rejects apps that share "the same source code or assets" with
others already submitted and differ only in minor ways. **The number is
invisible without measuring it** — the apps that got rejected all looked
completely different on screen.

## Run it

```bash
python3 ${CLAUDE_SKILL_DIR}/check_similarity.py \
  --alias candy --alias fruit
```

Defaults to the current directory against every sibling with a `pubspec.yaml`.
Exits non-zero if any surface is at or above the threshold (default **30%**),
or if any metadata or screenshot file is byte-identical to a sibling's.

| Flag | Use |
|---|---|
| `--alias WORD` | a domain noun to normalise away — see the warning below |
| `--threshold N` | fail at or above N% (default 30) |
| `--surface S` | `source`, `metadata`, `screenshots` or `assets`; repeatable, default all |
| `--app DIR` `--root DIR` | check something other than the cwd |
| `--near F` | count a text file as shared at or above this ratio (default 0.9) |
| `--json` | machine-readable, for a hook or CI |

**Always pass `--alias` for the app's domain nouns** (the fruit, the taco, the
pie) **and for the fork parent's** (the ball, the table). Two files identical
except for `s/taco/candy/` count as *different* without them, so omitting them
understates sharing — which is the direction that lets a bad app through. The
tool warns when none are given.

## The four surfaces, and why there are four

4.3(a)'s own wording is "the same source code **or assets**" and "a similar
binary, **metadata**, and/or **concept**", so a clean source number proves
nothing on its own.

- **source** — non-generated Dart, path-matched, near-duplicate at ≥90%.
- **metadata** — the store listing text under `fastlane/metadata`: subtitle,
  keywords, promotional text, description, release notes, TestFlight and App
  Review notes, and the Play `short_description`/`full_description`/changelogs.
- **screenshots** — store images, compared **byte-identical only**, and matched
  on content rather than path because a copied screenshot gets renamed to suit
  its new app's scene order.
- **assets** — everything the binary ships that is not code or store copy:
  sound effects, fonts, and the generated icon and launch images on both
  platforms. Byte-identical only, matched on content, for the screenshot's
  reason — **and it is the surface where renaming is the norm rather than the
  exception.**

The assets surface earned its place on the run that added it. **A new game
was shipping a live sibling's audio** — its `level_clear.wav` byte-identical to
the live app's `level_up.wav`, and to `race_won.wav`, `cleared.wav` and
`level_up.wav` in three more repos. Five repos, one file, five names: the
generators had been forked and never re-composed, so the same
`_arpeggio([523, 659, 784, 1047, 1319])` call produced the same bytes
everywhere. Another pair read 16% on this surface, with `bomb.wav` and
`crash.wav` the same sound.

It also found **another app's branding inside seventeen repos**:
`android/app/src/main/res/drawable/splash.png` was the template's original
app's fully-branded launch image, referenced live by `launch_background.xml`,
in every app cut from that template. `flutter_native_splash:create` writes the
density buckets (`drawable-hdpi/` and friends) and never the bare `drawable/`,
so regenerating the splash does not replace it and nothing ever has.

Metadata and screenshots earned their place the same way: **one app shared
76% of its listing with a sibling** — byte-identical descriptions in es-ES and
pt-BR on both platforms, describing the first app's spaceships. No source check
would ever have said so, and that app is the one that got the 4.3(a).

**An empty surface is reported as unmeasured, not as a pass.** An app with no
screenshots captured prints `NOTHING TO COMPARE` rather than 0%, because a
silent zero reads as "checked and clean" when nothing was checked.

### What each surface excludes, and why

Excluding the wrong thing hides a real finding; excluding nothing buries it.

- **source**: generated files (`*.g.dart`, `*.config.dart`, `*.freezed.dart`)
  and platform directories.
- **metadata**: `review_information`, `copyright` and `*_url.txt` — one
  publisher's support address, privacy policy and marketing site are identical
  on every app they ship, for the same reason the logger is. Left in, they put
  a 33% on three URL files and buried the surface underneath.
- **assets**: `Contents.json`, the Xcode asset-catalog manifests, for
  `Framefile.json`'s reason — the icon and splash tools write them, so they are
  identical across these apps because the *tools* are. Left in, every app
  reports three permanent matches, and three entries that always mean nothing
  are how the one that means something gets skimmed past.
- **metadata**: `title.txt` and `name.txt`, for a sharper reason — **the
  normaliser makes them match unconditionally.** Their entire content is the
  app's name and the normaliser's job is to rewrite the app's name to `X`, so
  `Asteroid Duel` and `Peel Frenzy` both become `X X`. The tool reported five
  apps with byte-identical titles that share no word. **Any file whose content
  *is* the app name cannot be measured this way.**

## Reading the result

The percentage alone is not a decision. For source, the tool splits what is
shared:

- **infrastructure** — logger, crash reporting, DI, router, i18n, ad wrappers,
  test harness. Identical because it does an identical job. **Expected, and
  fine.** Two apps by one developer both having a crash reporter is not what
  4.3 prohibits.
- **app scaffolding** — blocs, screens, models, repositories. Identical because
  the *app shape* is identical: splash → menu → list → session → stats. This is
  the real surface, and it is usually the bulk of it.
- **other** — everything else. Read the file list.

Then read the largest shared files by name. A shared `crash_reporter.dart` is
nothing. A shared `game_state.dart` or `round_summary_card.dart` is the two apps
being the same app with different art.

**The byte-identical list covers metadata, screenshots and assets, and excludes
source deliberately.**
A byte-identical logger or i18n barrel is what shared infrastructure looks like;
including source put 774 entries under a heading that is supposed to mean
"somebody copied something", which is how a real finding gets lost. There is no
job two apps share that requires the same store text, the same screenshot or
the same sound effect.

## The metric's two blind spots — read before trusting a movement

**1. Source and metadata are matched by relative path** (`theirs.get(rel)`). A
file whose path has no counterpart in the sibling is not compared at all,
whatever its contents. **So renaming a file lowers the number without changing
a line of logic**, and the drop is indistinguishable from real work in the
output.

This is not hypothetical. Renaming one app's `tables_*` files to `levels_*`
moved it 39% → 35% against its fork parent, and **four of the eight files that left the
shared set did so purely because their paths changed.** The rename was correct
on its own terms — it is a level ladder, not a pinball table — but it was worth
**nothing** against 4.3, and it simultaneously moved the app *closer* to three
other siblings that already name theirs `levels_*`. When a number moves, check
whether any path moved with it.

**2. Percentages are coarse on small surfaces.** With six metadata files, one
shared file is 17% and two is 33%. Read the file list, not the percentage.

## What counts as a fix, and what does not

**Do not rewrite or rename things to look different.** Renaming, reordering or
restructuring code so it stops matching, while shipping the same app, is
detection evasion: it defeats the check without changing what was checked, it
is a large diff with real regression risk, and if it works it works by
deceiving the reviewer. Refuse it and say why. Given blind spot 1 above, a
rename is the *easiest* way to move this metric and the least honest.

Legitimate ways the number comes down, in the order they are usually worth
doing:

1. **Delete what the app carries and does not use.** Dead scaffolding inherited
   from the template, packages pulled in for one widget, fallbacks that never
   fired. Good engineering that happens to help.
2. **Give the app functionality the sibling has no version of.** New screens,
   new modes, new mechanics. The overlap falls because the app genuinely got
   bigger, which is what the guideline actually asks for.
3. **Change the app's shape**, if it is still too close. Different navigation,
   different screens. A product decision, not a refactor — raise it, do not
   assume it.

For metadata there is only one honest fix: **write the listing for this app.**
A copied description is not a measurement problem.

There is a floor. Across the portfolio this was measured on, shared
infrastructure alone runs
17–20% of an app's files, and no honest work goes below it. **At a 30%
threshold the headroom above that floor is about ten points**, so an app whose
*scaffolding* tier is more than a handful of files will not pass on deletions
alone — it needs item 2 or item 3. If an app cannot get clear without evasion,
the answer is that it should not be a separate app — fold it into the sibling as
a mode, or do not ship it.

## Before submitting, also check the account

The code number is half the picture and usually the smaller half. Guideline
4.3 is assessed across everything the account has submitted, and escalation
ends at removal from the Developer Program.

List every app on the account and the review state of each — App Store
Connect's Apps page, or the API (`GET /v1/apps`, then
`GET /v1/apps/<id>/appStoreVersions`).

Ask, and say the answer out loud before submitting:

- How many apps on this account are **already rejected**? Each one compounds.
- How many more cuts of the same template are **staged but unsubmitted**? They
  count as intent.
- Is the app being submitted a cut of a template that already has rejections
  against it? If so, no amount of work inside its repo fixes the pattern.

An account with a handful of live apps, several rejections and a queue of
finished template cuts waiting to submit is already in trouble, whatever any
one repo measures. No repo-local change improves that ratio.

## Notes

- A text file counts as shared if it is byte-identical after normalisation or
  at least `--near` the same. Screenshots have no near tier: two renders of
  different art are never 90% of the same bytes, so a ratio there would be
  noise dressed as a measurement.
- **The number is directional.** It is shared files over *this* app's file
  count, so A→B and B→A differ whenever the two apps are different sizes —
  one pair measured 46% one way and 50% the other. Run it from the app you are about to submit, and if a *live*
  sibling is the one over the line, run it from there too.
- The normaliser replaces the longest token first. That is load-bearing: with
  `peel` matched before `peel_frenzy`, the package name `peel_frenzy_ui`
  normalises to `X_frenzy_ui` and every file differing only by its package name
  reads as different. That bug understated a real measurement by four points.
- A repo's own lighter checks (shipped strings, a few assets) do not substitute
  for this one. An app can pass all of those while source sits at 61%.
