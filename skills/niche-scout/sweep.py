#!/usr/bin/env python3
"""Measure App Store niches with the public iTunes Search API.

No key, no auth, no rate-limit headers -- but Apple throttles around 20
calls/minute, so this sleeps between terms.

Usage:
    ./sweep.py "term one" "term two" ...
    ./sweep.py --file terms.txt
    ./sweep.py --json "term"          # raw rows for further analysis

Reads four things per term, per app-store-search-api-measurement:
  1. total ratings across purpose-built results  -> demand
  2. whether the term indexes at all             -> is there traffic to catch
  3. clustering of currentVersionReleaseDate     -> gold rush vs opening
  4. who owns the big apps                       -> is there a neutral tool
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SEARCH = "https://itunes.apple.com/search"
TODAY = datetime(2026, 9, 22, tzinfo=timezone.utc)


def fetch(term, country="us", limit=12, media="software"):
    qs = urllib.parse.urlencode(
        {"term": term, "country": country, "entity": "software", "media": media, "limit": limit}
    )
    req = urllib.request.Request(
        f"{SEARCH}?{qs}", headers={"User-Agent": "niche-scout/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def age_days(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (TODAY - d).days


def relevant(app, term):
    """Crude on-topic test: does any meaningful term word appear in name or
    subtitle/description head? Apple falls through to unrelated apps once it
    runs out of matches, and that fall-through is itself the signal."""
    words = [w for w in term.lower().split() if len(w) > 3]
    if not words:
        words = term.lower().split()
    hay = " ".join(
        [
            app.get("trackName", ""),
            app.get("trackCensoredName", ""),
            (app.get("description", "") or "")[:300],
        ]
    ).lower()
    return sum(1 for w in words if w in hay) >= max(1, len(words) // 2)


def name_match(app, term):
    """Does the app NAME (not description) carry the term's words? An exact-match
    descriptive name outranks a bigger app. If
    nothing here name-matches, the name is still available."""
    words = [w for w in term.lower().split() if len(w) > 3] or term.lower().split()
    name = app.get("trackName", "").lower()
    return sum(1 for w in words if w in name) >= max(1, len(words) - 1)


def summarize(term, results):
    rows = []
    for i, a in enumerate(results, 1):
        rows.append(
            {
                "rank": i,
                "name": a.get("trackName", "?"),
                "seller": a.get("sellerName", "?"),
                "ratings": a.get("userRatingCount", 0) or 0,
                "stars": a.get("averageUserRating", 0) or 0,
                "price": a.get("formattedPrice", "?"),
                "genre": a.get("primaryGenreName", "?"),
                "updated": (a.get("currentVersionReleaseDate") or "")[:10],
                "age_days": age_days(a.get("currentVersionReleaseDate")),
                "on_topic": relevant(a, term),
                "name_match": name_match(a, term),
            }
        )

    on = [r for r in rows if r["on_topic"]]
    # where does Apple stop having on-topic results
    fallthrough = next((r["rank"] for r in rows if not r["on_topic"]), None)
    total = sum(r["ratings"] for r in on)
    fresh = [r for r in on if r["age_days"] is not None and r["age_days"] <= 180]
    zero_fresh = [r for r in fresh if r["ratings"] <= 5]

    # THE GAP: a big proven audience whose recurring task has no purpose-built
    # tool is the buy signal (quilting: 33,949 audience / 145 best calculator).
    # A big audience with a big purpose-built tool is just competition.
    named = [r for r in on if r["name_match"]]
    ceiling = max((r["ratings"] for r in on), default=0)
    best_tool = max((r["ratings"] for r in named), default=0)

    return {
        "term": term,
        "on_topic_count": len(on),
        "fallthrough_rank": fallthrough,
        "total_ratings": total,
        "audience_ceiling": ceiling,
        # NB: name-matching is NOT the same as being a competing tool, and must
        # not be read as one -- Missouri Star name-matches "quilt" at 33,949 and
        # is a fabric shop. Kept only as a raw signal for name availability.
        "biggest_name_match": best_tool,
        "name_match_apps": [r["name"] for r in named],
        "top": sorted(on, key=lambda r: -r["ratings"])[:4],
        "shipped_6mo": len(fresh),
        "shipped_6mo_at_zero": len(zero_fresh),
        "genres": sorted({r["genre"] for r in on}),
        "rows": rows,
    }


def verdict(s):
    flags = []
    if s["total_ratings"] < 100:
        flags.append("NO MARKET (<100 ratings across category)")
    if s["fallthrough_rank"] is not None and s["fallthrough_rank"] <= 5:
        flags.append(f"NO INDEX (off-topic by #{s['fallthrough_rank']})")
    if s["shipped_6mo_at_zero"] >= 4:
        flags.append(f"GOLD RUSH ({s['shipped_6mo_at_zero']} new at ~0 ratings)")
    if not flags:
        flags.append("no kill-flag -- READ THE LEADERS")
    return flags


def render(s):
    print(f"\n{'='*72}\nTERM: {s['term']}")
    print(
        f"  on-topic {s['on_topic_count']:>2}  |  fall-through at #{s['fallthrough_rank'] or '-'}"
        f"  |  TOTAL RATINGS {s['total_ratings']:,}"
    )
    print(
        f"  shipped in 6mo: {s['shipped_6mo']} (of which ~0 ratings: {s['shipped_6mo_at_zero']})"
        f"  |  genres: {', '.join(s['genres']) or '-'}"
    )
    print(f"  VERDICT: {'; '.join(verdict(s))}")
    print(f"  audience ceiling {s['audience_ceiling']:,}")
    if s["top"]:
        # The GAP -- big proven audience, no good purpose-built tool -- is the buy
        # signal. It CANNOT be computed: Missouri Star name-matches
        # "quilt" with 33,949 ratings but is a fabric shop, i.e. audience evidence,
        # not a rival calculator. Classify each leader by hand:
        #   AUDIENCE  community/retail/content app  -> proves people exist
        #   TOOL      does the recurring task       -> the real competitor
        #   ADJACENT  different job, same words     -> ignore
        print("  leaders:  (classify each as AUDIENCE / TOOL / ADJACENT)")
        for r in s["top"]:
            print(
                f"      {r['ratings']:>7,} ★{r['stars']:.1f}  {r['price']:<8} "
                f"{r['name'][:40]:<40} [{r['seller'][:22]}] upd {r['updated']}"
            )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("terms", nargs="*")
    p.add_argument("--file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--country", default="us")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--sleep", type=float, default=3.0)
    a = p.parse_args()

    terms = list(a.terms)
    if a.file:
        with open(a.file) as f:
            terms += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if not terms:
        p.error("no terms")

    out = []
    for i, t in enumerate(terms):
        try:
            s = summarize(t, fetch(t, a.country, a.limit))
        except Exception as e:  # noqa: BLE001 - keep sweeping past one bad term
            print(f"!! {t}: {e}", file=sys.stderr)
            continue
        out.append(s)
        if not a.json:
            render(s)
        if i < len(terms) - 1:
            time.sleep(a.sleep)

    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"\n{'='*72}\nRANKED BY TOTAL RATINGS")
        for s in sorted(out, key=lambda x: -x["total_ratings"]):
            print(f"  {s['total_ratings']:>9,}  {s['term']:<38} {'; '.join(verdict(s))}")


if __name__ == "__main__":
    main()
