# Registers

Each surface has its own register. Pass the matching name to `check_voice.py`.
If another skill owns a surface and its rules disagree with this file, that
skill wins. Update this file to match it.

## casual: Reddit, forum replies, comments

- First person, as someone who hit the problem. Contractions everywhere.
- Package and tool names typed the way people type them mid-sentence: `soloud`,
  `audioplayers`, `admob`.
- Quote the exact error string. It's the most credible line in a comment.
- At most one bold phrase, usually none. Short replies beat complete ones.

## pin: Pinterest titles and descriptions

- A parent or homeowner talking: "swap it", "gray", "squished flat". Contractions.
- First person only where it's true: "My kids wanted a game where food falls
  from the sky, so I made one."
- The search phrase leads the title. No emoji walls, at most two hashtags.
- Name the source where it helps, in a different place each time, and sometimes
  not at all.
- Run `--batch` over the whole week's titles and descriptions together.

## email: cold pitches and outreach

- Open on something true and particular to them: what their reviews praise, how
  long they've been open. Never generic flattery.
- A tip should read like a neighbour pointing something out, not an audit.
- Short. A contract pitch can be five sentences: who you are, the proof, the
  offer, the rate, one question.
- Plain words, short paragraphs, no bullet lists, no marketing language.
- A day's batch goes out together, so run `--batch` and vary the structure.
- Never claim to be a customer, or to have visited, unless the user has.

## letter: cover letters and proposals

- Professional, but still the writer. Name a gap in their own voice instead of
  hiding it.
- The worst tells from one audit of 77 letters: the closing "I would welcome
  the chance to talk", "rather than" in nearly every letter, "That is exactly",
  "plainly", a colon followed by a list, and one anecdote reused in 26 letters.
- Biography blocks must be rewritten from the employer's angle each time,
  never pasted. `--batch` against recent letters shows which phrases have
  gone stale.
- The user reads the letter body before any PDF is rendered.

## store: App Store and Play listing copy (`listing-accuracy`)

- Dashes are allowed, but never three in one paragraph. Listings commonly use
  them and no store rule bans them.
- Lists of features are normal here, so the checker skips tricolons.
- Truth comes first. `listing-accuracy` checks every claim against the code.
  This register only covers how it reads.

## site: website pages, articles, FAQs

- Contractions are a split register. FAQ answers, taglines and the home page
  take them. Body copy in reviews and articles stays formal. Don't push either
  to 100%.
- Em dashes stay as part of the voice, but never three in one paragraph. Prefer
  a comma when an unpaired dash is only a pause before "but" or "and".
- Never reuse a meta description template, and keep each under 160 characters.
- Pick one spelling convention (US or UK) and keep to it.
- Describe your own products by what they are, not by what they lack.
- If the site has its own prose or SEO checker, it is the authority for prose
  budgets and wordiness. This checker adds the shared tells on top.
