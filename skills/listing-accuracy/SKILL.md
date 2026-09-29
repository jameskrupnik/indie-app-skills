---
name: listing-accuracy
description: Check that an app's store listing describes the app that actually exists, before submitting or after changing what the app does. Use when about to submit, resubmit or update an app on the App Store or Google Play; after adding, removing or renaming a feature, mode, screen or currency; when writing or reviewing description.txt, keywords, promotional text, release notes or App Review notes; when a rejection mentions guideline 2.3, "accurate metadata", "we were unable to locate", "could not find the feature described"; or when asked whether the listing, store copy or review notes are still true.
---

# Listing accuracy

The listing is the only part of an app that no test runs against. A compiler
will not read it, `deliver` uploads it without comparing it to anything, and
the one person who does read it closely is the reviewer deciding whether to
approve the build.

**The failure is never a typo. It is a sentence that reads perfectly and is
false.** A mode that was deleted last month. A promise that there are no
adverts of a kind the binary now serves. "Twelve tables" after the twelfth was
cut. Every one of these survives a green test suite indefinitely, because
nothing in the repo relates the two.

## Run it

```bash
python3 ${CLAUDE_SKILL_DIR}/check_listing.py
```

Defaults to the current directory. Exits non-zero on any FAIL; WARNs never do.
`--app DIR` to check elsewhere, `--json` for a hook.

It reads every file under `fastlane/metadata/*/en-US/` **and the App Review
notes**, and checks three things:

| Check | Catches |
|---|---|
| Names | A screen, mode or character named in the listing that appears nowhere in the app's strings or source |
| Capabilities | Adverts, purchases, accounts, online play and leaderboards claimed-but-absent, denied-but-present, or present-but-undisclosed |
| Counts | "twelve tables", "six themes" against the real lists and enums (advisory) |

## The rule this exists to enforce

**Re-read the listing whenever you change what the app does.** Adding a mode,
removing a feature, renaming a screen, changing a count — each of those makes
some sentence in the listing false, and the sentence does not move on its own.

In one session on one app, listing copy went stale **four separate times**:
once when a rewarded video was added to an app whose description said it had
none, once when the theme catalogue went from four to six, once when a second
game mode was added and the description described only the first, and once when
a heading said "six tables" in an app with twelve. Every one was written by
somebody who had just read the file.

The script catches the first three. It cannot catch the fourth kind — see
below.

## The review notes are the worst offender, and are in scope

`review_information/notes.txt` is written once, read by exactly one person who
can reject the app, and revisited by nobody. It is where a deleted feature
survives longest.

The most expensive thing this file can contain is **an instruction to try
something that is not there**. A reviewer told to test a Wi-Fi mode will look
for it, fail to find it, and reject on 2.3 — and unlike a vague description,
a numbered list of steps gives them something specific to fail at.

Check by hand, every time:

- Does every named screen and button still exist, spelled the same way?
- Do the stated controls work? (Key bindings drift silently and nobody tests
  the notes.)
- Are the ad, purchase, tracking and data-deletion claims still true?
- Is anything described as unlocked/available that is actually gated?

## A deleted control outlives its code in the listing

**The script passes a listing that sells a button the app no longer has**, as
long as the button's *word* survives anywhere in the source — a doc comment, a
removed-feature note, a test that asserts it is gone. one platformer's listing
sold a weapon "swap" button and an "aim button" for two days after both were
deleted, and its review notes told Apple the controls were "not taps on the
game itself" on the day the bow became exactly that. Every word was still in
the code, so every check was green.

**After any change to the controls or a removed feature, read the listing's
controls paragraph and the review notes by hand**, against the current input
code — not against the vocabulary. Then pin the deleted phrases in the app's
own listing test, so they cannot come back through a translation made from an
old English draft.

## What a script cannot check

The script compares words to code. It cannot tell you whether a true sentence
is the *right* sentence.

- **Emphasis.** A listing that spends four paragraphs on the mode nobody plays
  is accurate and useless.
- **Ambiguity.** "Six tables to look at" was every word true — the app has six
  skins — in an app with twelve tables. Read every count aloud with the
  question "could this be read as a different noun?"
- **Depth for 4.2.** The listing has to *show* the app is more than one loop.
  That is a judgement about what to include, not a fact to verify.
- **A feature you added but described nowhere.** The script warns for the
  capability classes it knows; for anything else, only reading does it.

## Fixing a failure

Fix the listing to match the app, or the app to match the listing. **Do not
fix it by deleting the claim and leaving the feature undisclosed** — an
undeclared rewarded video is worse than a wrongly-declared one, because the
first is a surprise to the reviewer and the second is a correction.

If a name is flagged and the feature genuinely exists, the app is calling it
something else. Make the two agree rather than adding the word to the
listing — the reviewer will search the UI for exactly the string you wrote.

## Extending it: a check that cannot fail is worse than none

Every claim in `CAPABILITY_CLAIMS` is a regex pair over the listing and a regex
list over the code. Adding one is a dict. Four rules learned by getting each of
them wrong first:

1. **Strip comments before matching code.** These repos explain at length what
   they deliberately do *not* do, so a capability search over doc comments
   finds a rewarded video in an app whose only mention of one is a note saying
   it has none.
2. **A capability behind a compile-time false flag is not shipped.** Whole
   purchase implementations sit behind `selling = false` and are unreachable.
   Match the gate, not the implementation — that is what `absent_if` is for.
3. **A denial contains an assertion.** "There are no in-app purchases" matches
   the phrase "in-app purchase". Check denials first and let them win, or every
   honest disclaimer reads as a claim.
4. **Never prefix-match a noun against a type name.** In a codebase where half
   the types begin with the same word, "tables" matched `TableSpec`,
   `TableTheme` and `TableEnd` and produced three warnings about one sentence,
   two of them nonsense.

And the general form of all four: **verify a new check against a listing you
know is broken, not only against one you believe is fine.** Passing on a good
input proves nothing — a check that always passes also does that. `git show`
the copy from before a fix and run against that.

## Related

- `app-similarity` — whether the *code* is too close to a sibling (4.3).
  This skill is about whether the *copy* is true (2.3). An app can fail either
  alone.
- `play-release` — its `preflight.sh` checks the Play metadata field limits
  and the built bundle. Length limits are that skill's job, not this one's.
