---
name: niche-scout
description: Measure a mobile app idea before any code is written — generate candidate niches, sweep their search terms against the free App Store search API, kill the dead ones with numbers (no market, no index, gold rush, consumable-owned), read the leaders by hand for a real gap, and cost the ongoing maintenance. Built for indie developers with no paid-acquisition budget, where an app is only found through store search. Use when asked for app ideas, what app to build next, whether a niche or app idea is worth it, whether a market exists, how big the competition is, to size up competitors, to pick a category, or to "scout", "validate" or "measure" an app idea.
---

# Scouting a niche

This skill ends before any code is written: one niche, measured, with the
numbers that justify it and the named risks written down. The job is **killing
candidates cheaply**. Building a small app costs a weekend; discovering
afterwards that nobody searches for it costs the weekend plus a listing you
have to maintain forever. Every rule below exists because a measurement
reversed a decision that reasoning had already made. Example figures are dated;
store numbers drift, so re-run rather than trust them.

## The premise: zero acquisition budget

**This skill assumes nothing is paid for and nothing is promoted.** So an app
is only findable if someone types a phrase into App Store search and the app is
the best match for it. That kills most ideas, and it is why the skill measures
*search terms* rather than markets. Two non-obvious things follow:

- **A descriptive, unownable name beats a brandable one.** "Feet and Inches
  Calculator" (411 ratings, solo dev) outranked Construction Master Pro
  (39,879) for *construction calculator* (measured 2026). Expect copycats; take
  the traffic anyway.
- **A term nobody searches is worth nothing however good the app is.** Demand
  you cannot be found for is not demand.

**If you do have a budget**, indexing matters less and a big TOOL incumbent
(step 4) stops being automatically fatal — you can buy the installs search
will not give you. Market size and maintenance cost still apply unchanged.

**Limitation: App Store only.** Google Play has no public search API and ranks
differently. If Play is your main store, treat these numbers as proof the
audience exists and check Play search by hand before committing.

## 1. Generate candidates

Bias toward a **recurring task**, not a one-time one. Towing weight for an RV
is calculated once per truck; binding yardage is calculated every quilt. The
second gets opened again, which is what ad revenue and ratings both need. If
you already ship apps, favour candidates your existing code transfers to.

## 2. Sweep the terms

```bash
python3 ${CLAUDE_SKILL_DIR}/sweep.py --limit 10 --sleep 6 \
  "term one" "term two" "term three"
```

Free, no key, standard-library Python 3.9+. Apple throttles around 20
calls/minute (a burst gets a timeout or HTTP 403), so keep `--sleep 6` and
batch 5–6 terms. Also `--country gb` (default `us`), `--file`, `--json`.
Exit 1 means a term failed to fetch: re-run it, never read it as empty.

**Write terms the way a user types them: one to three words.** Long phrases do
not index and the result is a false negative. `canning altitude pressure`
returned a wall of *altimeters*; `heat illness youth sports` returned team
schedulers. Both were real niches measured wrongly by a badly-worded query.
The script warns on anything longer. Sweep the obvious synonyms too: a niche
that only indexes under one phrasing has one shot at the name.

## 3. The four kill rules

The script flags the first three; the fourth needs you to look at the
sellers. Examples measured 2026.

| Flag | Rule | Why it kills |
|---|---|---|
| **NO MARKET** | under 100 ratings across every on-topic result | nobody is there. Evaporative cooler maintenance: 30 |
| **NO INDEX** | first off-topic result at position 5 or better | Apple has no index for the phrase, so there is no traffic to catch and an exact-match name has nothing to grab |
| **GOLD RUSH** | 4+ on-topic apps launched in the last 6 months, each at 5 ratings or fewer | others already found it and are being ignored. Beekeeping: 5 |
| **CONSUMABLE-OWNED** (by hand) | the leaders belong to firms selling the supply | there is no neutral tool to be. Hornady owns reloading at 43,056 ratings and sells the bullets; every pool-chemistry app over 3,000 belongs to a chemical company |

## 4. The rule the script cannot apply: read the leaders

The winning shape is a **gap** — a large proven audience whose recurring task
has no good purpose-built tool. Quilting (measured Sept 2026): 33,957 ratings
of audience, best actual calculator at 145.

**This cannot be computed; trying produced confidently wrong answers.** An
automated version scored quilting — the niche that proved the idea —
"CONTESTED", because Missouri Star name-matches *quilt* with ~34,000 ratings.
Missouri Star is a fabric retailer: evidence the audience exists, not a rival
calculator. The same heuristic scored the crowded Zutobi/DMV Genie
driving-test-prep market "OPEN".

So classify every leader the script prints into exactly one of:

- **AUDIENCE** — retailer, community, magazine, content app. Proves people
  exist. Not a competitor. *Missouri Star, Bulk Reef Supply, sportsYou.*
- **TOOL** — does the recurring task. The only real competitor.
  *QuiltingCalc, My Row Counter, UDisc.*
- **ADJACENT** — same words, different job. Ignore. *Fishing games under
  "hunting regulations", a generic calculator under "quilt calculator".*

**Big AUDIENCE + small-or-bad TOOL is the only buy signal.** Big TOOL is
competition you lose without ad spend. No AUDIENCE is no market.

A stale or low-starred TOOL beats an absent one: it proves the task is real
*and* the incumbent beatable. Monash University invented the low-FODMAP diet;
its $7.99 app sat at 4.2★ against free rivals at 4.7★ (measured 2026).

**But low stars are not automatically an opening — ask what the app is for.**
US state fish-and-game apps rated 2.1–4.3★ against a 4.7–4.9★ norm elsewhere
(measured 2026). They rate badly because the *transaction* they wrap is
painful: buying a licence and carrying it as legal proof. A third party cannot
do that job at all, so the stars measure something unbuildable. Separate "this
app is bad" from "this app's job is available to me".

## 5. Cost the maintenance before recommending

For a small developer the target is **expensive to build, free to run**. Sort
every candidate's content by how often reality changes it:

| Content shape | Backend | Verdict |
|---|---|---|
| Physics, arithmetic, craft math | none, ships in the binary | ideal |
| Ecology, climate, anatomy, protocols | none | ideal |
| Statute and regulation | none, but a yearly review | acceptable if the app is not the authority |
| Prices, schedules, events, closures, listings | a feed forever | **reject** |

A backend is not free in effort even on a free tier: it is a console, a rules
file, a quota and a thing that breaks silently. Prefer none. Where sync is the
product, on-device storage plus a short share code and no accounts is the
cheapest thing that works.

**Beware the trap in "local".** Local is appealing because nobody optimises for
it, but it fails in two ways at once:

- Local *schedules* — trash days, markets, trail closures, event calendars —
  are exactly the feed-forever row above.
- Local *subjects* have no App Store index of their own. `desert plants care`
  and `citrus tree care` returned the identical national result set — Planta at
  113,807, Blossom at 68,752 (measured 2026). There is no desert shelf and no
  small desert app to beat — just a subscription giant.

Local only works where the content is **jurisdictional and static** — and
check who is liable if it is wrong.

## 6. Report numbers before opinions

State the figures, name every leader's shape, give the risk. Then recommend.

**Competitor complaints are not demand.** This rule reversed a finished
recommendation. RV towing had specific, documented, unfixed complaints
in every rival's reviews — and ~48 ratings across the whole category, no index
on `gvwr`, and seven entrants in ten weeks. Complaints prove a product is bad.
They say nothing about whether anyone wants a better one. If nothing survives,
**say so**: a sweep that kills everything has done its job.

## 7. Record the result

Append every term swept to `measured.md` at the project root — kept and killed
both, with numbers, storefront and date. The kills are most of the value:

```markdown
## quilt calculator — KEPT (us, 2026-09-29)
total 40,645 · on-topic 10/10 · launched 6mo: 2 at ~0
AUDIENCE Missouri Star 33,957 · TOOL QuiltingCalc 145 (4.2★, stale) · ADJACENT Calculator ∞
gap: big audience, weak tool. maintenance: craft math, no backend.

## gvwr — KILLED (us, 2026-09-29)
NO INDEX. ~48 ratings across the category; 7 entrants in 10 weeks.
Rival reviews full of complaints, but complaints are not demand.
```

Then hand the survivor to whoever builds it, carrying: the term to name
against, the audience evidence, the incumbent to beat, the maintenance shape.
