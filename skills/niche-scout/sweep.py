#!/usr/bin/env python3
"""Measure App Store niches with the public iTunes Search API.

No key, no auth, no rate-limit headers -- but Apple throttles at roughly
20 calls/minute and answers a burst with a timeout or HTTP 403, so this
sleeps between terms and retries once with a longer back-off.

Reads four things per term:
  1. total ratings across on-topic results       -> demand
  2. where results go off-topic                  -> does the term index at all
  3. clustering of recent release dates          -> gold rush vs opening
  4. the leaders, for you to classify by hand    -> is there a gap

App Store only. Google Play has no equivalent public search API.

Exit codes: 0 all terms measured, 1 one or more terms failed, 2 usage error.
Standard library only; Python 3.9+.
"""

import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SEARCH = "https://itunes.apple.com/search"
NOW = datetime.now(timezone.utc)

# Kill-rule thresholds. SKILL.md's table quotes these; keep them in step.
NO_MARKET_RATINGS = 100   # total ratings across on-topic results
NO_INDEX_RANK = 5         # first off-topic result at or above this rank
GOLD_RUSH_COUNT = 4       # recent launches sitting at ~0 ratings
RECENT_DAYS = 180
ZERO_RATINGS = 5


class FetchError(Exception):
    pass


def fetch(term, country, limit, retries=1, backoff=20.0):
    qs = urllib.parse.urlencode(
        {"term": term, "country": country, "entity": "software",
         "media": "software", "limit": limit}
    )
    req = urllib.request.Request(
        f"{SEARCH}?{qs}", headers={"User-Agent": "niche-scout/1.1"}
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode("utf-8"))
            return body.get("results", [])
        except urllib.error.HTTPError as e:
            # 403 and 429 are Apple's throttle; anything else will not improve.
            if e.code not in (403, 429, 503) or attempt == retries:
                hint = " (throttled: raise --sleep)" if e.code in (403, 429) else ""
                raise FetchError(f"HTTP {e.code}{hint}") from e
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            if attempt == retries:
                raise FetchError(f"network: {getattr(e, 'reason', e)}") from e
        except ValueError as e:
            raise FetchError(f"bad JSON from API: {e}") from e
        print(f"   .. {term!r}: retrying in {backoff:.0f}s", file=sys.stderr)
        time.sleep(backoff)
    return []


def age_days(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (NOW - d).days)


def _words(term):
    words = term.lower().split()
    return [w for w in words if len(w) > 3] or words


def relevant(app, term):
    """Crude on-topic test on name plus the head of the description. Apple
    falls through to unrelated apps once it runs out of matches, and where
    that happens is itself the signal."""
    words = _words(term)
    hay = " ".join([
        app.get("trackName", "") or "",
        (app.get("description", "") or "")[:300],
    ]).lower()
    return sum(1 for w in words if w in hay) >= max(1, len(words) // 2)


def name_match(app, term):
    """Does the app NAME carry the term's words? A raw signal for whether an
    exact-match name is still free -- NOT a competitor test (see SKILL.md)."""
    words = _words(term)
    name = (app.get("trackName", "") or "").lower()
    return sum(1 for w in words if w in name) >= max(1, len(words) - 1)


def summarize(term, results):
    rows = []
    for i, a in enumerate(results, 1):
        rows.append({
            "rank": i,
            "name": a.get("trackName", "?"),
            "seller": a.get("sellerName", "?"),
            "ratings": a.get("userRatingCount", 0) or 0,
            "stars": a.get("averageUserRating", 0) or 0,
            "price": a.get("formattedPrice", "?"),
            "genre": a.get("primaryGenreName", "?"),
            "updated": (a.get("currentVersionReleaseDate") or "")[:10],
            "released": (a.get("releaseDate") or "")[:10],
            "age_days": age_days(a.get("currentVersionReleaseDate")),
            "launch_age_days": age_days(a.get("releaseDate")),
            "url": a.get("trackViewUrl", ""),
            "on_topic": relevant(a, term),
            "name_match": name_match(a, term),
        })

    on = [r for r in rows if r["on_topic"]]
    fallthrough = next((r["rank"] for r in rows if not r["on_topic"]), None)
    # Gold rush counts new LAUNCHES, not updates: an old app that shipped a
    # patch last month says nothing about newcomers crowding in.
    launched = [r for r in on
                if r["launch_age_days"] is not None and r["launch_age_days"] <= RECENT_DAYS]
    launched_zero = [r for r in launched if r["ratings"] <= ZERO_RATINGS]
    named = [r for r in on if r["name_match"]]

    return {
        "term": term,
        "result_count": len(rows),
        "on_topic_count": len(on),
        "fallthrough_rank": fallthrough,
        "total_ratings": sum(r["ratings"] for r in on),
        "audience_ceiling": max((r["ratings"] for r in on), default=0),
        "biggest_name_match": max((r["ratings"] for r in named), default=0),
        "name_match_apps": [r["name"] for r in named],
        "launched_6mo": len(launched),
        "launched_6mo_at_zero": len(launched_zero),
        "updated_6mo": sum(1 for r in on
                           if r["age_days"] is not None and r["age_days"] <= RECENT_DAYS),
        "genres": sorted({r["genre"] for r in on}),
        "top": sorted(on, key=lambda r: -r["ratings"])[:4],
        "rows": rows,
    }


def verdict(s):
    flags = []
    if s["result_count"] == 0:
        return ["NO RESULTS (term returned nothing)"]
    if s["total_ratings"] < NO_MARKET_RATINGS:
        flags.append(f"NO MARKET ({s['total_ratings']} ratings across on-topic results)")
    if s["fallthrough_rank"] is not None and s["fallthrough_rank"] <= NO_INDEX_RANK:
        flags.append(f"NO INDEX (off-topic by #{s['fallthrough_rank']})")
    if s["launched_6mo_at_zero"] >= GOLD_RUSH_COUNT:
        flags.append(f"GOLD RUSH ({s['launched_6mo_at_zero']} launched in 6mo at ~0 ratings)")
    if not flags:
        flags.append("no kill-flag -- READ THE LEADERS (and check CONSUMABLE-OWNED)")
    return flags


def render(s):
    print(f"\n{'=' * 72}\nTERM: {s['term']}")
    print(f"  on-topic {s['on_topic_count']:>2}/{s['result_count']}"
          f"  |  fall-through at #{s['fallthrough_rank'] or '-'}"
          f"  |  TOTAL RATINGS {s['total_ratings']:,}")
    print(f"  launched in 6mo: {s['launched_6mo']} (at ~0 ratings: {s['launched_6mo_at_zero']})"
          f"  |  updated in 6mo: {s['updated_6mo']}"
          f"  |  genres: {', '.join(s['genres']) or '-'}")
    print(f"  VERDICT: {'; '.join(verdict(s))}")
    print(f"  audience ceiling {s['audience_ceiling']:,}")
    if s["top"]:
        # The gap cannot be computed: a retailer that name-matches the term is
        # audience evidence, not a rival tool. Classify by hand (SKILL.md step 4).
        print("  leaders:  (classify each as AUDIENCE / TOOL / ADJACENT)")
        for r in s["top"]:
            print(f"      {r['ratings']:>7,} *{r['stars']:.1f}  {r['price']:<8} "
                  f"{r['name'][:40]:<40} [{r['seller'][:22]}] upd {r['updated']}")


def read_terms(path):
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def main():
    p = argparse.ArgumentParser(
        description="Measure App Store search terms before building an app. "
                    "Flags NO MARKET, NO INDEX and GOLD RUSH; the leaders "
                    "still have to be read by hand.",
        epilog='example: %(prog)s --limit 10 --sleep 6 "row counter" "quilt calculator"',
    )
    p.add_argument("terms", nargs="*",
                   help="search terms, 1-3 words each, as a user would type them")
    p.add_argument("--file", help="read more terms from a file, one per line (# comments ok)")
    p.add_argument("--json", action="store_true", help="print raw rows and summaries as JSON")
    p.add_argument("--country", default="us",
                   help="two-letter App Store storefront code (default: us)")
    p.add_argument("--limit", type=int, default=12,
                   help="results per term, 1-200 (default: 12)")
    p.add_argument("--sleep", type=float, default=6.0,
                   help="seconds between terms; Apple throttles near 20/min (default: 6)")
    a = p.parse_args()

    if not re.fullmatch(r"[A-Za-z]{2}", a.country):
        p.error("--country must be a two-letter code such as us, gb, de")
    if not 1 <= a.limit <= 200:
        p.error("--limit must be between 1 and 200")

    terms = list(a.terms)
    if a.file:
        try:
            terms += read_terms(a.file)
        except OSError as e:
            p.error(f"cannot read --file: {e}")
    if not terms:
        p.error("no terms given")

    for t in terms:
        if len(t.split()) > 3:
            print(f"   warning: {t!r} is over 3 words; long phrases rarely index "
                  "and give false negatives", file=sys.stderr)

    out, failed = [], []
    for i, t in enumerate(terms):
        if i:
            time.sleep(a.sleep)
        try:
            s = summarize(t, fetch(t, a.country.lower(), a.limit))
        except FetchError as e:
            print(f"!! {t}: {e}", file=sys.stderr)
            failed.append(t)
            continue
        out.append(s)
        if not a.json:
            render(s)

    if a.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif out:
        print(f"\n{'=' * 72}\nRANKED BY TOTAL RATINGS ({a.country.lower()})")
        for s in sorted(out, key=lambda x: -x["total_ratings"]):
            print(f"  {s['total_ratings']:>9,}  {s['term']:<38} {'; '.join(verdict(s))}")
    if failed:
        print(f"\n!! {len(failed)} term(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        # Non-UTF-8 terminals would otherwise crash on app names like "Calculator ∞".
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
