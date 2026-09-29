---
name: niche-scout
description: Find and measure a niche for a new mobile app before any code is written — generating candidates, sweeping them against the App Store search API, killing the dead ones with numbers, and costing the ongoing maintenance. Use when asked for app ideas, what to build next, whether a niche is worth it, to check if a market exists, to size up competitors, or to pick a category.
---

# Scouting a niche

This skill ends before any code is written: one niche, measured, with the
numbers that justify it and the named risks written down.

The job is **killing candidates cheaply**. Building a small app costs a
weekend; discovering afterwards that nobody searches for it costs the weekend
plus a listing you have to maintain forever. Every rule below exists because a
measurement reversed a decision that reasoning had already made.

## The constraint that decides everything

**This skill assumes the user acquisition budget is zero** — nothing is paid for
and nothing is promoted. So an app is only
findable if someone types a phrase into App Store search and the app is the
best match for it. That single fact kills most ideas, and it is why this skill
measures *search terms* rather than markets.

Two things follow, and they are not obvious:

- **A descriptive, unownable name beats a brandable one.** "Feet and Inches
  Calculator" (411 ratings, solo dev) outranks Construction Master Pro (39,879)
  for *construction calculator*. Expect copycats; take the traffic anyway.
- **A term nobody searches is worth nothing however good the app is.** Demand
  you cannot be found for is not demand.

## 1. Generate candidates against the portfolio, not in a vacuum

If you already ship apps, a candidate is worth more when an existing app's
engine transfers. Quilting math *is* construction math, so a construction
calculator's exact-fraction and length types can move across untouched, tests
included.

Bias toward a **recurring task**, not a one-time one. RV towing weight is
calculated once per truck; binding yardage is calculated every quilt. The
second gets opened again, which is what ad revenue and ratings both need.

## 2. Sweep the terms

```bash
python3 ${CLAUDE_SKILL_DIR}/sweep.py --limit 10 --sleep 6 \
  "term one" "term two" "term three"
```

Free, no key, no auth. Apple throttles around 20 calls/minute and answers a
burst with a socket timeout, so keep `--sleep 6` and batch 5–6 terms. `--json`
emits the raw rows.

**Write terms the way a user types them: one to three words.** Long phrases do
not index and the result is a false negative. `canning altitude pressure`
returned a wall of *altimeters*; `heat illness youth sports` returned team
schedulers. Both were real niches measured wrongly by a badly-worded query.

Sweep the obvious synonyms too. A niche that only indexes under one phrasing
is a niche with one shot at the name.

## 3. The four kill rules (the script applies these)

These are arithmetic and need no judgment:

| Flag | Rule | Why it kills |
|---|---|---|
| **NO MARKET** | under ~100 ratings across every on-topic result | nobody is there. Evaporative cooler maintenance: 30 |
| **NO INDEX** | results go off-topic by position ~5 | Apple has no index for the phrase, so there is no traffic to catch and an exact-match name has nothing to grab |
| **GOLD RUSH** | 4+ apps shipped in 6 months all at ~0 ratings | others already found it and are being ignored. Beekeeping: 5 |
| **CONSUMABLE-OWNED** | the leaders belong to firms selling the supply | there is no neutral tool to be. Hornady owns reloading at 43,056 and sells the bullets; pool chemistry's every app over 3,000 belongs to a chemical company |

## 4. The one rule the script cannot apply: read the leaders

The winning shape is a **gap** — a large proven audience whose recurring task
has no good purpose-built tool. Quilting: 33,949 ratings of audience, best
actual calculator at 145.

**This cannot be computed, and trying produced confidently wrong answers.**
An automated version scored quilting — the niche that proved the thesis —
"CONTESTED", because Missouri Star name-matches *quilt* with 33,949 ratings.
Missouri Star is a fabric retailer. It is the evidence the audience exists, not
a rival calculator. The same heuristic scored the Zutobi/DMV Genie test-prep
war "OPEN".

So classify every leader by hand into exactly one of:

- **AUDIENCE** — retailer, community, magazine, content app. Proves people
  exist. Not a competitor. *Missouri Star, Bulk Reef Supply, sportsYou.*
- **TOOL** — does the recurring task. The only real competitor.
  *QuiltingCalc, My Row Counter, UDisc.*
- **ADJACENT** — same words, different job. Ignore. *Fishing games under
  "hunting regulations", altimeters under "canning altitude".*

Then: **big AUDIENCE + small-or-bad TOOL is the only buy signal.** Big TOOL is
competition and with no ad spend you lose. No AUDIENCE is no market whatever the TOOL
column says.

A stale or low-starred TOOL is worth more than an absent one — it proves the
task is real *and* that the incumbent is beatable. Monash University invented
the low-FODMAP diet and their $7.99 app sits at 4.2★ while free rivals sit at
4.7★.

**But low stars are not automatically an opening — ask what the app is for.**
State fish-and-game apps rate 2.1–4.3★ against a 4.7–4.9★ norm everywhere else,
the widest quality gap in any sweep behind this skill. They rate badly
because the *transaction* they wrap is painful: buying a licence and carrying
it as legal proof. A third party cannot do that job at all, so the stars are
measuring something unbuildable. Separate "this app is bad" from "this app's
job is available to me".

## 5. Cost the maintenance before recommending

The brief this was written for is **expensive to build, free to run**. Sort every
candidate's content by how often reality changes it:

| Content shape | Backend | Verdict |
|---|---|---|
| Physics, arithmetic, craft math | none, ships in the binary | ideal |
| Ecology, climate, anatomy, protocols | none | ideal |
| Statute and regulation | none, but a yearly review | acceptable if the app is not the authority |
| Prices, schedules, events, closures, listings | a feed forever | **reject** |

A Firebase project is not free in effort even on the free tier: it is a
console, a rules file, a quota and a thing that breaks silently. Prefer none.
Where sync is genuinely the product, on-device storage plus a 6-character share
code and no accounts is the cheapest thing that works.

**Beware the trap in "local".** Local is appealing because nobody optimises for
it, but it fails in two distinct ways at once, and both showed up in
measurement:

- Local *schedules* — trash days, markets, trail closures, event calendars —
  are exactly the feed-forever row above. Local is the most maintenance-heavy
  content there is.
- Local *subjects* have no App Store index of their own. `desert plants care`
  and `citrus tree care` return the identical national result set — Planta at
  113,807, Blossom at 68,752. There is no purpose-built desert app to beat
  because there is no desert shelf. You do not get a quiet local niche; you get
  put in the ring with a subscription giant.

Local only works where the content is **jurisdictional and static**, and even
then check who is liable if it is wrong.

## 6. Report numbers before opinions

State the measured figures, name the shape of every leader, and give the risk
you would be taking. Then recommend.

**Competitor complaints are not demand.** This is the rule that reversed a
finished recommendation. RV towing had specific, documented, unfixed complaints
in every rival's reviews — and ~48 ratings across the whole category, no index
on `gvwr`, and seven entrants in ten weeks. Complaints prove a product is bad.
They say nothing about whether anyone wants a better one.

If nothing survives, **say so**. A sweep that kills everything has done its
job; recording it (below) means the next sweep starts further along.

## 7. Record the result

Append every term swept to a `measured.md` in the project — kept and killed both, with the
numbers and the date. It stops the same dead ends being re-measured, and the
kills are most of the value.

Then hand the survivor to whoever builds it, carrying: the term to name against, the
audience evidence, the incumbent to beat, and the maintenance shape.
