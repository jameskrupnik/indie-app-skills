---
name: listing-accuracy
description: Check that a Flutter app's store listing describes the app that actually exists, before submitting or after changing what the app does. Compares fastlane metadata (description, subtitle, keywords, promotional text, release notes, Android changelogs, App Review notes) against the Dart code and strings, flagging feature names the app does not contain, ad/purchase/sign-in/online/leaderboard claims the code contradicts, and stale counts. Use when about to submit, resubmit or update an app on the App Store or Google Play; after adding, removing or renaming a feature, mode, screen or currency; when writing or reviewing description.txt, full_description.txt, keywords, promotional text, release notes or review notes; when a rejection cites guideline 2.3, "accurate metadata", "we were unable to locate" or "could not find the feature described"; or when asked whether the listing, store copy or review notes are still true.
---

# Listing accuracy

The listing is the only part of an app that no test runs against. The
compiler never reads it, fastlane uploads it without comparing it to
anything, and the one person who does read it closely is the reviewer
deciding whether to approve the build.

**The failure is never a typo. It is a sentence that reads perfectly and is
false.** A mode that was deleted last month. A promise of no adverts of a kind
the binary now serves. "Twelve tables" after the twelfth was cut. Each of these
survives a green test suite forever, because nothing in the repo relates the
two.

## Quick start

```bash
python3 ${CLAUDE_SKILL_DIR}/check_listing.py              # app in the cwd
python3 ${CLAUDE_SKILL_DIR}/check_listing.py --app path/to/app --locale en-GB
python3 ${CLAUDE_SKILL_DIR}/check_listing.py --json       # for a hook or CI
```

Python 3.9+, stdlib only. Exit codes: **0** no FAIL (warnings allowed),
**1** at least one FAIL, **2** nothing was checked (no listing files for that
locale, or no Dart under a `lib/`). Other flags: `--listing FILE` for copy kept
outside fastlane, `--allow WORD` for a capitalised word that is not a feature
name (a brand, a place). `--help` lists them.

**Assumed layout** is fastlane's own. It looks for `metadata/` under
`fastlane/`, `ios/fastlane/` and `android/fastlane/`, and reads every `.txt` in
the chosen locale directory at any depth (`metadata/en-US/`,
`metadata/android/en-US/changelogs/`, `metadata/ios/en-US/`), in `default/`,
and `review_information/notes.txt`. URLs, copyright and reviewer contact files
are skipped. The app side is every non-generated `.dart` under a `lib/`
directory (so `lib/` and `packages/*/lib/`), plus `.arb`, slang `.i18n.*` and
text files under `assets/`.

## What it checks

| Check | Result | Catches |
|---|---|---|
| Names | FAIL | A capitalised mid-sentence word or a "Quoted Name" that appears nowhere in the app's code, strings or assets |
| Capabilities | FAIL / WARN | Rewarded video, in-app purchase, banner/interstitial ads, sign-in, online or multi-device play, leaderboards: claimed-but-absent, denied-but-present, or present-but-undisclosed |
| Counts | WARN | "twelve tables", "six themes" against `const` lists and enums whose name matches the noun |

Title, name, subtitle, keywords and promotional text are skipped by the name
check only, because title case there is branding. The name check is
English-centric: in a language that capitalises every noun, rely on the other
two checks.

## Reading the output

- **Name FAIL.** Either the feature is gone, or the app calls it something
  else. Both are real: the reviewer will search the UI for exactly the string
  you wrote.
- **"Says no X, and the code has one."** Before rewriting the copy, check
  whether X is reachable in a *release* build. A full implementation often
  sits behind a false flag or test-only ad unit ids, which makes the denial
  true; add that gate to the claim's `absent_if` and say so in the review
  notes, because a reviewer cannot see a blank unit id.
- **"Code implements it, but it looks switched off."** The listing sells a
  feature a release build will not show. Wire the production ids first, or
  cut it from the copy.
- **"Has X and no listing file mentions it."** Undisclosed, not absent.
- **Count WARN.** Advisory, because mapping a noun to a list is a guess. Read
  the sentence and decide which side is stale.

## The rule this exists to enforce

**Re-read the listing whenever you change what the app does.** Adding a mode,
removing a feature, renaming a screen, changing a count: each makes some
sentence false, and the sentence does not move on its own. On one app, copy
went stale four times in a single working session, every time written by
someone who had just read the file.

## The review notes are the worst offender

`review_information/notes.txt` is written once, read by exactly one person who
can reject the app, and revisited by nobody. It is where a deleted feature
survives longest.

The most expensive thing it can contain is **an instruction to try something
that is not there**. A reviewer told to test a Wi-Fi mode will look for it,
fail, and reject on 2.3. A numbered list of steps gives them something
specific to fail at. Check by hand, every time:

- Does every named screen and button still exist, spelled the same way?
- Do the stated controls still work? Key bindings drift and nobody tests notes.
- Are the ad, purchase, tracking and data-deletion claims still true?
- Is anything described as available that is actually gated or locked?

## What it cannot check

**It passes a listing that sells a button the app no longer has**, as long as
the button's word survives anywhere in the code: a leftover string, an
identifier, a test fixture. A deleted "aim button" stays green while `aim`
appears in any identifier. **After any change to controls or any removed
feature, read the listing's controls paragraph and the review notes against
the current input code**, not the vocabulary. Then pin the deleted phrases in
a listing test of your own, so a translation made from an old draft cannot
bring them back.

It compares words to code. It cannot tell whether a true sentence is the
*right* one:

- **Emphasis.** Four paragraphs on the mode nobody plays is accurate and
  useless.
- **Ambiguity.** "Six tables" was true (six skins) in an app with twelve
  tables. Read every count aloud and ask whether it could mean another noun.
- **Depth for guideline 4.2.** Showing the app is more than one loop is a
  judgement about what to include, not a fact to verify.
- **Capabilities outside its table.** Anything else you added and described
  nowhere, only reading finds.
- **Ad unit ids from outside Dart.** With `--dart-define` or a config file,
  the rewarded gate finds no ids and assumes the feature ships.

## Fixing a failure

Fix the listing to match the app, or the app to match the listing. **Never fix
it by deleting the claim and leaving the feature undisclosed.** An undeclared
rewarded video is worse than a wrongly declared one: the first surprises the
reviewer, the second is a correction.

If a name is flagged and the feature exists under another name, make the two
agree rather than adding the word to the listing.

## Extending it: a check that cannot fail is worse than none

`CAPABILITY_CLAIMS` near the top of the script is a list of dicts: `asserts`
and `denies` (regexes over the lowercased listing), `code` (regexes over
comment-stripped Dart) and optional `absent_if` (the release gate). Adding a
capability is one dict; adding a stop word is one word in `STOPWORDS`. Four
rules, each learned by getting it wrong first:

1. **Strip comments before matching code.** Good code explains at length what
   it deliberately does *not* do; a search over comments found a rewarded
   video in an app whose only mention of one was a note saying it had none.
2. **A capability behind a compile-time false flag is not shipped.** Match the
   gate, not the implementation; that is what `absent_if` is for. The default
   in-app-purchase gate matches `<something>selling|purchases|iap<something> =
   false`; adapt it to your flag.
3. **A denial contains an assertion.** "There are no in-app purchases" matches
   "in-app purchase". The script ignores an assertion preceded by a negator in
   the same clause, and a `denies` match wins over its sentence. Keep `denies`
   to whole-app statements: "no second device" describes one mode of an app
   that may have another, and "no ads on this screen" is not "no ads".
4. **Never prefix-match a noun against a type name.** "tables" prefix-matched
   `TableSpec`, `TableTheme` and `TableEnd` and produced three warnings about
   one sentence, two of them nonsense. Counts match exactly, one plural
   stripped.

The general form of all four: **verify a new check against a listing you know
is broken, not only one you believe is fine.** Passing a good input proves
nothing; a check that always passes does that too. `git show` the copy from
before a fix and run against it.

## Related

- `app-similarity`: whether the *code* is too close to a sibling (4.3). This
  skill is whether the *copy* is true (2.3). An app can fail either alone.
- `play-release`: its preflight checks Play metadata field lengths and the
  built bundle. Length limits are that skill's job, not this one's.
