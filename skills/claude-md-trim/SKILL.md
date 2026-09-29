---
name: claude-md-trim
description: Bring a CLAUDE.md or AGENTS.md back under Claude Code's size warning without losing a single rule, by moving the evidence behind each rule into docs/ and leaving the rule and a link. Use the moment Claude Code warns that CLAUDE.md is over the limit, "Large CLAUDE.md will impact performance", "over the 150.0k-char limit", "instruction files add up to", too long, or not being fully followed; when asked to trim, shrink, compact, split, slim down, clean up or reorganise CLAUDE.md, CLAUDE.local.md, AGENTS.md or .claude/rules; and before adding a long new section to one that is already near the cap. Works for any language or stack.
---

# Trimming CLAUDE.md

**Every character of CLAUDE.md is paid for in every session and every subagent,
and past a size threshold Claude Code tells you so on every launch.** The warning
is per file ("CLAUDE.md is over the 150.0k-char limit") and for the set that loads
at startup together ("9 instruction files add up to 192.2k chars, over the
150.0k-char total limit"). Older versions and smaller context windows warn at 40k
("Large CLAUDE.md will impact performance"). **Read the number off your own
warning** and pass it as `--limit`.

What the official docs say: a CLAUDE.md is loaded in full up to 4 MiB and skipped
above that; files under ~200 lines are followed better; `@path` imports load at
launch and so do not reduce anything. Reports that the end of an oversized file is
silently cut are not confirmed by the docs — treat the warning as a cost warning,
not a truncation notice, and do not tell the user rules are "being cut off" unless
you have seen it happen.

The fix is never "delete the least important paragraph". It is **a split along
the seam these files already have**: a rule, and the evidence it was decided on.
`CLAUDE.md` keeps the rule. `docs/` keeps the evidence. Everything here applies
equally to `AGENTS.md`, `CLAUDE.local.md` and unscoped `.claude/rules/*.md` files.

## The rule

**Nothing is deleted. Everything moves.** If a paragraph is not worth keeping in
`docs/`, deleting it is a separate decision that belongs to the user, not to a
size limit.

## Run it

```bash
python3 ${CLAUDE_SKILL_DIR}/check_size.py                  # measure the project's files
python3 ${CLAUDE_SKILL_DIR}/check_size.py --limit 40000    # match a 40k warning
python3 ${CLAUDE_SKILL_DIR}/check_size.py --links          # verify after
```

With no paths it measures `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` (or
`AGENTS.md` if there is no CLAUDE.md), every file they `@`-import, and every
`.claude/rules/*.md` without a `paths:` field. It prints characters per file (UTF-16
units after frontmatter and block HTML comments are stripped, which is how Claude
Code has been observed to count), the launch-set total, and the biggest sections.
`--links` checks every relative link and `#anchor` in those files and in the docs
they link to. `--json` for scripts; exit code 1 on anything over or broken.

## The procedure

1. **Measure first.** Note each file's size and its ten biggest sections. Do not
   start from a guess about which section is long.

2. **Aim for 10% headroom, not 1 under.** These files grow with every task.
   Landing just under means doing this again next week, and each pass is a chance
   to lose a rule. The script prints the target.

   **But the target is an aim, not a quota.** A file that is all rules has a
   floor, and grinding past it means paraphrasing rules into mush — which costs
   more than the warning does. **Stop when the evidence runs out, say where you
   stopped and what the floor was**, and let the user decide whether to cut.

3. **Classify, section by section, biggest first.** Two questions, and only the
   second one moves anything:

   - *Is this a rule?* — it tells the next agent what to do or not do. **Rules
     never move.** A number, a constraint, a "do not reach for X", a "check Y
     before Z", the reason a decision cannot be reversed.
   - *Is this evidence?* — benchmark tables, run logs, dates, the four approaches
     that were tried and thrown out, the story of how a bug was found. **Evidence
     moves**, and takes its detail with it.

   The tell is tense and specificity. "Ran the suite 40 times with the pool at 8,
   16 and 32; 16 was the only size with zero deadlocks" is evidence. "Keep the DB
   pool at 16 — 8 and 32 both deadlock under the test suite" is the rule.

4. **Pick the destination.** Reuse what the repo already has before inventing:

   | Content | Goes to |
   |---|---|
   | benchmarks, experiments, tried-and-rejected fixes | `docs/measurements.md` |
   | incident write-ups, how a bug was tracked down | `docs/incidents.md` |
   | deploy, infra, account and environment setup history | `docs/operations.md` |
   | a rule that only matters in one directory | `.claude/rules/<topic>.md` with `paths:` |
   | anything else | `docs/<topic>.md`, opening with a two-line preamble |

   Each docs file opens by saying that the instruction file keeps the rule and
   this file keeps the evidence, so when they disagree a reader knows which is
   stale. **Do not replace moved text with an `@` import** — imports load at
   launch and save nothing.

5. **Leave the rule and a link.** The stub is a compressed version of the finding,
   never a bare "see docs". An agent that does not follow the link must still know
   what not to do: the bolded claim, one clause of why, then
   `[how we know](docs/measurements.md#anchor)`.

6. **Compress tables to ids and verdicts.** A table whose cells carry paragraphs
   is the easiest win: keep every id, name, version and status, and move the
   "how it got that way" prose out. Ids are what an agent needs every session;
   provenance is what it needs when something breaks.

7. **Fix relative links in the moved text.** A link to `src/db.ts` or `#gotchas`
   that worked in the root file is broken once the paragraph lives in `docs/`
   (it now needs `../src/db.ts` or `../CLAUDE.md#gotchas`).

8. **Verify before saying it is done:**

   - `check_size.py --links`: under target, **zero broken links** — moving a
     heading breaks every `#anchor` that named it;
   - `git diff --stat` shows lines *moved*, not lines gone. If `CLAUDE.md` lost
     4,000 characters and `docs/` gained 600, rules went in the bin.

9. **Report what moved**, section by section, so the user can object to a call
   they would have made differently. They wrote the file; you reorganised it.

## What not to do

- **Do not summarise a rule into vagueness.** "Be careful with the cache" replaces
  a rule with a mood. If a rule is long because it is precise, it stays long.
- **Do not drop the numbers.** Constants, timeouts, sizes, versions and limits are
  the value of these files. Move the paragraph around a number; keep the number.
- **Do not reflow paragraphs you are not otherwise touching.** It buries the real
  change in a whitespace diff and defeats the `git diff --stat` check.
- **Do not move the top-of-file orientation.** Whatever tells an agent what the
  project is and what to read first stays. Trim the sections it points at.
- **Do not "fix" the file's voice.** Match its existing style in stubs and in the
  moved prose.
