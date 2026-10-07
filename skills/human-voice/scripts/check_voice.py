#!/usr/bin/env python3
"""Score drafts for the tells that make writing read as machine-generated.

    python3 check_voice.py --register casual draft.txt
    python3 check_voice.py --register letter letter-*.md --batch
    python3 check_voice.py --register site page.html
    cat draft.txt | python3 check_voice.py --register email -

Registers (see ../references/registers.md):
    casual  Reddit, forum replies, comments        dashes banned
    pin     Pinterest titles and descriptions      dashes banned
    email   cold pitches, outreach, replies        dashes banned
    letter  cover letters, proposals               dashes banned
    store   App Store and Play listing copy        dashes allowed, not clustered
    site    website pages, articles, FAQs          dashes allowed, not clustered

FAIL lines are hard house rules and make the exit code 1. NOTE lines are tells
to look at; a draft can ship with a note when the sentence is right as written.
--batch also compares the files against each other, for drafts that go out
together (a week of pins, a day of pitches, a run of cover letters).

The dash check uses Python, not grep, on purpose: the `grep -c $'...\\|...'` form
once copied between skills never matched anything on macOS, and every letter
"passed" it for weeks (found 2026-09-17).
"""
import argparse
import html
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

NO_DASH = {"casual", "pin", "email", "letter"}
REGISTERS = NO_DASH | {"site", "store"}

BANNED_CHARS = {"—": "em dash", "–": "en dash", "‘": "curly quote",
                "’": "curly quote", "“": "curly quote", "”": "curly quote"}

# Phrases that announce a point instead of making it, or that no person types.
THROAT = [
    r"\bhere'?s the thing\b", r"\bhere is the thing\b", r"\bthe key (insight|takeaway) is\b",
    r"\bit'?s worth (noting|mentioning|pointing out)\b", r"\bit is worth (noting|mentioning)\b",
    r"\blet'?s dive in\b", r"\bdive into\b", r"\bin today'?s (fast-paced|digital)\b",
    r"\bat the end of the day\b", r"\bthe reason is \w+ rather than\b",
    r"\bthat'?s exactly where\b", r"\bthat is exactly (where|what|why)\b",
    r"\bwhether you'?re an? [^.]{1,40} or an?\b", r"\bin conclusion\b",
    r"\bto be (honest|plain|frank)\b", r"\b(bluntly|frankly)\b",
    # "plainly" only when the writer vouches for themselves. "Calm says plainly
    # that it is final sale" reports a source and is fine.
    r"\b(we|i|i'll|let me|worth) (say|saying|put|putting|state|stating) "
    r"(it |that |this )?plainly\b", r"\bto put it plainly\b",
    r"\bi hope this helps\b", r"\bhappy to help\b", r"\bgreat question\b",
    r"\bnavigate the (complexities|landscape)\b", r"\bin the realm of\b",
    r"\bplays a (crucial|pivotal|vital) role\b", r"\ba testament to\b",
]
HYPE = [
    r"\bultimate\b", r"\bgame[- ]changer\b", r"\bmust[- ]have\b", r"\beffortless(ly)?\b",
    r"\bseamless(ly)?\b", r"\brevolutioni[sz]e\b", r"\belevate\b",
    # Games unlock levels. Only the marketing sense is a tell.
    r"\bunlock (your|the power|new possibilities|the full)\b",
    r"\bsupercharge\b", r"\bleverage\b", r"\brobust\b", r"\bdelve\b", r"\btapestry\b",
    r"\bempower(s|ing)?\b", r"\bcutting[- ]edge\b", r"\bbest[- ]in[- ]class\b",
    r"\b(to|is) the next level\b", r"\bnext-level\b", r"\bharness\b", r"\bstreamline\b",
]
# "It's not X, it's Y" and its expanded form.
REVERSAL = re.compile(
    r"\b(?:it|this|that)(?:'s| is| was) not [^.;:!?]{1,80}[,;.] "
    r"(?:it|that|this)(?:'s| is| was)\b"
    r"|\b(?:is|was|are|were)(?: not|n't) [^.;:!?]{1,90}[.;,] "
    r"(?:it|that|this|they) (?:is|was|are|were)\b", re.I)
# Three parallel items: "fast, cheap, and reliable" / "a, b and c".
TRICOLON = re.compile(r"\b(\w+(?: \w+)?), (\w+(?: \w+)?),? and (\w+(?: \w+)?)\b")
HEDGE = re.compile(r"\b(arguably|perhaps|it seems|it appears|somewhat|potentially|"
                   r"may or may not|generally speaking|in many cases)\b", re.I)
CONTRACTION = re.compile(r"\b\w+'(s|t|re|ve|ll|d|m)\b", re.I)
EXPANDABLE = re.compile(r"\b(it is|that is|do not|does not|did not|is not|are not|"
                        r"can not|cannot|will not|would not|i am|you are|we are|"
                        r"they are|i have|you have|i would|there is)\b", re.I)
BOLD_LEAD = re.compile(r"^\s*(?:[-*] )?\*\*[^*]+\*\*", re.M)

CONTRACTION_FLOOR = {"casual": 0.5, "pin": 0.3, "email": 0.3}
LONG_SENTENCE = {"casual": 30, "pin": 25, "email": 28, "letter": 35, "store": 30, "site": 45}


def plain_text(raw, name):
    if name.endswith((".html", ".htm")):
        # Prose lives in block elements. Head, nav, header and footer are
        # page furniture, and a letter's signature block is not a sentence.
        raw = re.sub(r"(?is)<(head|script|style|code|pre|nav|header|footer|svg)\b[^>]*>.*?</\1>",
                     " ", raw)
        blocks = re.findall(r"(?is)<(p|li|h[1-6]|blockquote|td|dd|figcaption)\b[^>]*>(.*?)</\1>", raw)
        raw = "\n\n".join(re.sub(r"<[^>]+>", " ", b) for _, b in blocks)
        raw = html.unescape(raw)
    # Code spans and fenced blocks are quoted material, not voice.
    raw = re.sub(r"```.*?```", " ", raw, flags=re.S)
    raw = re.sub(r"`[^`\n]+`", "CODE", raw)
    return raw


def paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 4]


def sentences(text):
    # A heading or list item has no full stop, so each block ends its own sentence.
    out = []
    for block in re.split(r"\n\s*\n", text):
        flat = re.sub(r"\s+", " ", block)
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", flat) if s.strip()]
    return out


def check(name, raw, register):
    fails, notes = [], []
    text = plain_text(raw, name)
    words = len(text.split()) or 1

    found = Counter(BANNED_CHARS[c] for c in text if c in BANNED_CHARS)
    if register in NO_DASH:
        for kind, n in found.items():
            plural = (kind + "es" if kind.endswith("sh") else kind + "s") if n > 1 else kind
            fails.append(f"{n} {plural} (house rule: zero in {register})")
    else:
        for p in paragraphs(text):
            # A dash inside a quote is the source's, not ours.
            n = re.sub(r"\u201c[^\u201d]*\u201d|\"[^\"\n]*\"", " ", p).count("\u2014")
            if n >= 3:
                notes.append(f"{n} em dashes in one paragraph, rewrite it: {p[:60]!r}...")

    # Quoted material is someone else's words. Never flag it, never rewrite it.
    low = re.sub(r"\u201c[^\u201d]{0,600}\u201d|\"[^\"\n]{0,600}\"", " ", text).lower()
    for pat in THROAT:
        for m in re.finditer(pat, low):
            notes.append(f"throat-clearing {m.group(0)!r}")
    for pat in HYPE:
        for m in re.finditer(pat, low):
            notes.append(f"hype word {m.group(0)!r}")
    revs = [m.group(0) for m in REVERSAL.finditer(text)]
    if revs and len(revs) > (1 if register == "site" else 0):
        notes.append(f"{len(revs)} 'it's not X, it's Y' reversal(s): {revs[0][:60]!r}")
    # Factual lists are fine on site pages (feet, inches and fractions), so the
    # site skips this.
    # Store copy lists features by nature, so it skips it too.
    tris = ([m.group(0) for m in TRICOLON.finditer(text)]
            if register not in ("site", "store") else [])
    if len(tris) > max(1, words // 250):
        notes.append(f"{len(tris)} three-item lists ({', '.join(repr(t) for t in tris[:3])}); "
                     f"cut one to two items where two do the job")
    hedges = HEDGE.findall(text)
    if len(hedges) > 1:
        notes.append(f"{len(hedges)} hedges ({', '.join(sorted(set(h.lower() for h in hedges)))})")
    genuine = re.findall(r"\bgenuine(?:ly)?\b", low)
    if len(genuine) > 1:
        notes.append(f"'genuine(ly)' {len(genuine)} times")

    bolds = BOLD_LEAD.findall(raw)
    if register in ("casual", "email", "letter", "pin") and len(bolds) > 1:
        notes.append(f"{len(bolds)} bold lead-ins; a person writes at most one")

    floor = CONTRACTION_FLOOR.get(register)
    if floor is not None:
        c, e = len(CONTRACTION.findall(text)), len(EXPANDABLE.findall(text))
        if c + e >= 3 and c / (c + e) < floor:
            notes.append(f"stiff: {c} contractions against {e} expanded forms "
                         f"(say it's, don't, you're)")

    sents = sentences(text)
    limit = LONG_SENTENCE[register]
    longs = [s for s in sents if len(s.split()) > limit]
    if longs:
        notes.append(f"{len(longs)} sentence(s) over {limit} words: {longs[0][:60]!r}...")
    if len(sents) >= 6:
        lens = [len(s.split()) for s in sents]
        cv = statistics.pstdev(lens) / (statistics.mean(lens) or 1)
        if cv < 0.3:
            notes.append(f"sentence lengths too even (spread {cv:.2f}); "
                         f"mix a short one in")
    paras = paragraphs(text)
    if len(paras) >= 4:
        lens = [len(p.split()) for p in paras]
        cv = statistics.pstdev(lens) / (statistics.mean(lens) or 1)
        if cv < 0.25:
            notes.append(f"paragraphs all about {round(statistics.mean(lens))} words "
                         f"(spread {cv:.2f}); real writing is uneven")
    # A page ends on an FAQ answer or a footer, so only messages get this check.
    if len(paras) >= 3 and register in ("casual", "email", "letter"):
        last = sentences(paras[-1])
        first = set(re.findall(r"\b[a-z]{5,}\b", paras[0].lower()))
        if last and len(last) == 1 and len(first & set(re.findall(r"\b[a-z]{5,}\b",
                                                                      last[0].lower()))) >= 3:
            notes.append(f"closing line restates the opening: {last[0][:60]!r}")
    return fails, notes, sents


def ngrams(text, n=6):
    toks = re.findall(r"[a-z']+", text.lower())
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def batch_check(docs):
    """Repetition across drafts that go out together."""
    out = []
    for pos, label in ((0, "opening"), (-1, "closing")):
        seen = Counter()
        for name, sents in docs:
            if sents:
                seen[re.sub(r"\W+", " ", sents[pos].lower()).strip()] += 1
        # A shared salutation or sign-off ("Hi Sam," / "Thanks, Alex") is not a template.
        seen = Counter({s: n for s, n in seen.items() if len(s.split()) >= 5})
        for s, n in seen.items():
            if n > 1:
                out.append(f"{n} drafts share one {label} sentence: {s[:60]!r}")
        # Same first three words is the subtler template.
        stems = Counter(" ".join(s[pos].split()[:3]).lower() for _, s in docs
                        if s and len(s[pos].split()) >= 5)
        for s, n in stems.items():
            if n > 1 and n >= len(docs) / 2:
                out.append(f"{n} of {len(docs)} {label} sentences start {s!r}")
    grams = Counter()
    for name, sents in docs:
        for g in ngrams(" ".join(sents)):
            grams[g] += 1
    shared = [g for g, n in grams.items() if n > 1 and n >= max(2, len(docs) // 2)]
    if shared:
        out.append(f"{len(shared)} six-word phrases repeat across drafts, "
                   f"e.g. {shared[0]!r}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", help="drafts, or - for stdin")
    ap.add_argument("--register", required=True, choices=sorted(REGISTERS))
    ap.add_argument("--batch", action="store_true",
                    help="also compare the drafts with each other")
    a = ap.parse_args()

    failed = False
    docs = []
    for f in a.files:
        raw = sys.stdin.read() if f == "-" else Path(f).read_text(encoding="utf-8")
        fails, notes, sents = check(f, raw, a.register)
        docs.append((f, sents))
        status = "FAIL" if fails else ("notes" if notes else "clean")
        print(f"{f}: {status}")
        for x in fails:
            print(f"  FAIL  {x}")
        for x in notes:
            print(f"  NOTE  {x}")
        failed |= bool(fails)
    if a.batch and len(docs) > 1:
        rep = batch_check(docs)
        print(f"batch of {len(docs)}: {'repetition found' if rep else 'clean'}")
        for x in rep:
            print(f"  NOTE  {x}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
