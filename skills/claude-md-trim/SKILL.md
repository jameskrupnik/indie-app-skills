---
name: claude-md-trim
description: Bring a CLAUDE.md back under Claude Code's 150k-character limit without losing a single rule, by moving the evidence behind each rule into docs/ and leaving the rule and a link. Use the moment a warning says CLAUDE.md is over the limit, over 150k chars, too long, truncated, or not being fully loaded; when asked to trim, shrink, compact, split, clean up or reorganise CLAUDE.md or AGENTS.md; and before adding a long new section to one that is already near the cap.
---

# Trimming CLAUDE.md

**A CLAUDE.md over 150,000 characters is silently truncated**, and the part that
gets cut is the end of the file — usually Architecture, Errors and Gotchas, the
sections an agent needs most when it is about to break something. A file that is
1% over is not 1% worse; it is a file with an invisible hole in it.

The fix is never "delete the least important paragraph". It is **a split along
the seam these files already have**: a rule, and the evidence the rule was
decided on. `CLAUDE.md` keeps the rule. `docs/` keeps the evidence.

## The rule

**Nothing is deleted. Everything moves.** If a paragraph is not worth keeping in
`docs/`, it was not worth writing, and deleting it is a separate decision that
belongs to the user rather than to a size limit.

## Run it

```bash
python3 ${CLAUDE_SKILL_DIR}/check_size.py            # measure
python3 ${CLAUDE_SKILL_DIR}/check_size.py --links    # verify after
```

It prints the total, the headroom against 150k, a per-heading byte breakdown
biggest-first, and — with `--links` — every internal anchor and `docs/*.md#…`
link that no longer resolves.

## The procedure

1. **Measure first.** Run the script. Note the total and the ten biggest
   sections. Do not start editing from a guess about which section is long.

2. **Aim at 135k, not 149k.** These files grow every build — a TestFlight row, a
   probe result, a fault someone just found. Landing at 149k means doing this
   again next week, and each pass is a chance to lose a rule. 10% headroom is
   the point of the exercise.

   **But 135k is an aim, not a quota.** A file that is all rules has a floor, and
   grinding past it means paraphrasing rules into mush — which costs more than
   truncation would. **Stop when the evidence runs out, say where you stopped and
   what the floor was**, and let the user decide whether to cut content. That
   decision is theirs; the limit does not make it for them.

3. **Classify, section by section, biggest first.** Two questions, and only the
   second one moves anything:

   - *Is this a rule?* — something that tells the next agent what to do or not
     do. **Rules never move.** A number, a constraint, a "do not reach for X",
     a "check Y before Z", the reason a decision cannot be reversed.
   - *Is this evidence?* — the probe table, the run counts, the dates, the four
     things that were tried and thrown out, the narrative of how a fault was
     found. **Evidence moves**, and takes its detail with it.

   The tell is tense and specificity. "1,223 probe rows against a merge-disabled
   build, zero differ" is evidence. "Collision-neutral, measured" is the rule
   that survives it.

4. **Pick the destination file.** Reuse what the repo already has before
   inventing anything:

   | Content | Goes to |
   |---|---|
   | probe tables, runs, tried-and-rejected fixes | `docs/measurements.md` |
   | service records, provisioning, store state, how a console was wired | `docs/release.md` |
   | anything else | a new `docs/<topic>.md` with a two-line preamble saying what it holds |

   Every one of these files opens by saying that `CLAUDE.md` keeps the rule and
   this file keeps the evidence, so that when the two disagree a reader knows
   which is out of date.

5. **Leave the rule and a link.** The stub in `CLAUDE.md` is a compressed
   version of the finding — never a bare "see docs". An agent that does not
   follow the link must still come away knowing what not to do. A good stub is
   the bolded claim plus one clause of why, then
   `[what it was](docs/measurements.md#anchor)`.

6. **Compress tables to ids and verdicts.** A state table whose cells carry
   paragraphs is the single easiest win in these files: keep every id, every
   name, every **Real** / **not yet entered** verdict, and move the "how it was
   created and what lied on the way" prose out. Ids are what an agent needs in
   the file; provenance is what it needs when something breaks.

7. **Verify before saying it is done:**

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/check_size.py --links
   ```

   - under target, with headroom;
   - **zero broken links** — moving a heading breaks every `#anchor` that named
     it, and a broken anchor in a file agents navigate by is worse than the
     paragraph it replaced;
   - `git diff --stat` shows lines *moved*, not lines gone. If `CLAUDE.md` lost
     4,000 characters and `docs/` gained 600, four rules went in the bin.

8. **Report what moved**, section by section, so the user can object to a call
   they would have made differently. They wrote the file; you reorganised it.

## What not to do

- **Do not summarise a rule into vagueness.** "Be careful with the camera
  projection" replaces a rule with a mood. If a rule is long because it is
  precise, it stays long.
- **Do not drop the numbers.** A constant, a duration, a byte count, a rung
  number and a version are the whole value of these files. Move the paragraph
  around a number; keep the number.
- **Do not reflow paragraphs you are not otherwise touching.** It buries the
  real change in a whitespace diff and makes step 7's `git diff --stat` check
  useless.
- **Do not move the top-of-file orientation.** Whatever tells an agent what the
  app is and what to read first stays, however long. Trim the sections it points
  at instead.
- **Do not "fix" the file's voice.** These files are written in a house style;
  match it in the stubs and in the moved prose.
