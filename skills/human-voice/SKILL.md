---
name: human-voice
description: Make anything written in the user's name or for their business read like a person wrote it, not a model - Reddit and forum comments, Pinterest pins, cold emails and pitches, cover letters and proposals, store listings and website pages. Holds the shared list of tells (em dashes, "it's not X, it's Y", tricolons, throat-clearing, hype words, even paragraphs, tidy closing lines, templated batches), a register for each surface, and a checker script other skills can run before showing a draft. Use when drafting or reviewing any outward-facing text, when asked to make something sound more human, less robotic, less like AI or ChatGPT, more like the user, or when a batch of drafts starts sounding alike.
---

# Human voice

Writing that goes out under a person's name should sound like that person,
not like a model. When several skills each keep their own copy of these rules,
the copies drift; one copy once carried a dash check that never matched
anything. Keep the rules here in one place. Other skills keep only what is
specific to their surface and point here.

The substance is almost never the problem. The polish is. A correct draft that
reads as generated is worse than none, because it attaches to the user's name.

## The loop, for every draft

1. **Write from the facts in front of you, in the register for the surface.**
   Pick it from `references/registers.md`. Lifting the substance of one of the
   user's own comments or edits and loosening the grammar gets there
   faster than writing fresh.
2. **Run the checker.** Every FAIL must be fixed. Read every NOTE and fix it
   unless the sentence is right as written.
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_voice.py" --register <r> <files>
   # several drafts going out together (a week of pins, a day of pitches):
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_voice.py" --register <r> --batch <files>
   ```
   Registers: `casual`, `pin`, `email`, `letter`, `store`, `site`. Use `-` for
   stdin. If the project has its own site prose or SEO checker, run it too;
   this script only adds the shared tells.
3. **Read it out loud,** the whole batch together. If two drafts sound like
   siblings, rewrite one. The script can't hear this.
4. **Show the user.** They are the only real check on "this does not sound
   like me". When they rewrite a sentence, keep their words exactly. Don't
   smooth them. Their phrasing is the target, not a draft of it.

## The tells

**Mechanical.** The checker catches all of these.

- **Em dashes, en dashes and curly quotes,** in every register except `site`
  and `store`. Use a comma, a full stop or a new sentence. On the site and in
  listings, dashes are part of the voice, but never three in one paragraph.
- **Bold lead-ins** on paragraph after paragraph. At most one in a comment,
  email or letter, and usually none.
- **Even paragraphs and even sentences.** Real writing puts a two-line paragraph
  next to a seven-line one, and a four-word sentence next to a long one.
- **Too few contractions** in a casual register. "It is not" in a Reddit reply
  reads stiff.
- **Long sentences.** The limit depends on the register.

**Rhetorical.** The checker flags most of these, but read for them anyway.

| Cut | Why |
|---|---|
| "It's not X, it's Y" | The single most recognisable model sentence shape |
| Three parallel items where two would do | A writing habit, not a speech habit |
| "Here's the thing", "The key insight is", "It's worth noting" | Announces a point instead of making it |
| "That's exactly where", "the reason is X rather than Y" | Too neat a landing, and it sets up a strawman |
| "Whether you're a ... or a ..." | Ad copy |
| "plainly", "to be honest", "bluntly" | Signals honesty instead of being honest |
| Hype: ultimate, seamless, effortless, leverage, robust, elevate, game-changer | Nobody says these out loud |
| A hedge on every claim | You either hit the bug or you didn't |
| A closing line that ties back to the opening | Essays do this. People stop when they're done |

**Batch.** The checker's `--batch` flag catches these.

- The same opening or closing sentence across drafts. 70 of 77 cover letters
  once ended "I would welcome the chance to talk."
- The same biography block or anecdote pasted in near-verbatim. The writer's real
  differentiators should keep appearing, phrased fresh each time from the
  reader's angle.
- One description shape across a week of pins, such as every one ending with
  "Guidance from X".

## What to put in instead

- **The cost, in plain words.** "Took me way too long." "Lost most of a day to it."
  These are memories, so they can't be generated credibly.
- **One specific thing only someone who did it would mention.** The exact error
  string. The arrow on the filter points toward the furnace. Both engines failed
  in the same place.
- **The thing itself, not its absence.** Lead with what the game does, not
  "a game with no ads".

## Never, in any register

- Invent a motivation, an achievement, a visit or a customer relationship. If
  a draft says the user is excited about something, they must be able to say
  it out loud.
- Change quoted source material while editing for style.
- Add a statistic, time or claim the source doesn't make.

`references/before-after.md` has a full rewrite of a real Reddit comment, with
the same facts both times. Read it once if a draft feels off and you can't say
why.
