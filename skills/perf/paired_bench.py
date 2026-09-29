#!/usr/bin/env python3
"""Benchmark two versions of anything by alternating them, and report the
median per-pair ratio with a control correction.

Why: five runs of one arm followed by five of the other is not a comparison.
A laptop throttles under sustained load, so whichever arm runs second loses,
often by more than the optimization wins. Running the arms in alternating
pairs means both see the same machine, and the order flips every pair
(before/after, then after/before) so a steady drift does not always
penalise the same arm.

You supply two commands:

  --swap   puts the working tree into one arm; `{arm}` is replaced by
           `before` or `after`. Must exit 0, or the run stops, because
           benchmarking the wrong arm is worse than not benchmarking.
  --probe  runs the benchmark and prints numbers to stdout/stderr.

Example (a three-line bench_swap.sh copies saved versions of the changed
files into place for each arm):

  paired_bench.py \\
    --probe 'flutter test tool/perf_probe.dart' \\
    --swap  './bench_swap.sh {arm}' \\
    --pairs 4 --control update

Metrics are parsed from lines in either shape:

  L01  update 33/178/6133  record 86/120/900     -> L01.update, L01.record
  record=86   or   record: 86us                  -> record

In the first shape the first number (the median) is used. A line's first
token labels the row, so the same metric on two rows stays two metrics.

Keep a control metric: something the change cannot affect (for a render
change, `update`). Read it first. If it does not come back near 1.00x the
machine drifted, and the `corrected` column (ratio / control ratio) is the
only usable estimate. Python 3.9+, stdlib only.
"""
from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

# `update 33/178/6133`: a name followed by slash-separated percentiles.
TABLE = re.compile(r"\b([A-Za-z][\w-]*)\s+(\d+(?:\.\d+)?)\s*/\s*[\d.]+\s*/"
                   r"\s*[\d.]+")
# `record=86` or `record: 86us`
INLINE = re.compile(r"\b([A-Za-z][\w-]*)\s*[=:]\s*(\d+(?:\.\d+)?)")
ROW_LABEL = re.compile(r"^\s*(\S+)")
# How far the control may move before the raw column is not trusted.
DRIFT_TOLERANCE = 0.08


def parse(out: str) -> Dict[str, float]:
    """Metrics keyed `row.metric`. A key seen twice gets a `#n` suffix rather
    than overwriting, so two rows that share a label are never merged."""
    found: Dict[str, float] = {}
    seen: Dict[str, int] = {}
    for line in out.splitlines():
        matches = list(TABLE.finditer(line)) or list(INLINE.finditer(line))
        if not matches:
            continue
        label = ROW_LABEL.match(line)
        # The first token labels the row unless it is itself a metric.
        row = label.group(1) if label and label.end() <= matches[0].start() \
            else ""
        for m in matches:
            name, value = m.group(1), float(m.group(2))
            key = f"{row}.{name}" if row else name
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                key = f"{key}#{seen[key]}"
            found[key] = value
    return found


def run(cmd: str) -> Tuple[int, str]:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                            check=False)
    return result.returncode, result.stdout + result.stderr


def summarise(ratios: Dict[str, List[float]], control: str,
              pairs: int) -> List[str]:
    """The report, as lines. Separate from main() so it can be tested."""
    if not ratios:
        return ["No metric was non-zero in both arms; nothing to compare."]
    controls = [statistics.median(v) for k, v in ratios.items()
                if control and control in k]
    control_median = statistics.median(controls) if controls else None

    lines = [f"median after/before over {pairs} alternating pair(s); "
             f"<1.00x is faster\n"]
    width = max(len(k) for k in ratios)
    for key in sorted(ratios):
        values = ratios[key]
        median = statistics.median(values)
        spread = f"{min(values):.2f}-{max(values):.2f}"
        is_control = bool(control) and control in key
        extra = "  <- control" if is_control else ""
        if control_median and not is_control:
            extra = f"   corrected {median / control_median:.2f}x"
        lines.append(f"  {key:<{width}}  {median:.2f}x  (range {spread})"
                     f"{extra}")

    if control_median is None:
        lines.append(f"\nNo metric matched --control '{control}'. Without "
                     "one this table cannot tell a real change from drift.")
    elif abs(control_median - 1) > DRIFT_TOLERANCE:
        lines.append(f"\nThe control moved to {control_median:.2f}x: the "
                     "machine drifted. Read the corrected column, or rerun "
                     "with more pairs on a cooler, quieter machine.")
    else:
        lines.append(f"\nControl at {control_median:.2f}x: the machine held "
                     "still, so the raw column is usable.")
    lines.append("A range that straddles 1.00x is not a demonstrated effect.")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", required=True,
                    help="command that runs the benchmark and prints numbers")
    ap.add_argument("--swap", required=True,
                    help="command that selects an arm; {arm} becomes "
                         "'before' or 'after'")
    ap.add_argument("--pairs", type=int, default=4,
                    help="number of before/after pairs (default: 4)")
    ap.add_argument("--control", default="update",
                    help="substring naming the metric(s) the change cannot "
                         "affect (default: update)")
    args = ap.parse_args()

    if "{arm}" not in args.swap:
        ap.error("--swap must contain {arm}, or both arms run the same code")
    if args.pairs < 1:
        ap.error("--pairs must be at least 1")

    ratios: Dict[str, List[float]] = defaultdict(list)
    for pair in range(1, args.pairs + 1):
        # Flip the order every pair so a steady drift cancels.
        order = ("before", "after") if pair % 2 else ("after", "before")
        arms: Dict[str, Dict[str, float]] = {}
        for arm in order:
            print(f"  pair {pair}/{args.pairs}: {arm} ...", file=sys.stderr,
                  flush=True)
            code, out = run(args.swap.replace("{arm}", arm))
            if code != 0:
                print(f"swap to '{arm}' failed (exit {code}):\n"
                      f"{out.strip()[:500]}", file=sys.stderr)
                return 2
            code, out = run(args.probe)
            if code != 0:
                print(f"  probe exited {code} on '{arm}'; parsing whatever "
                      "it printed", file=sys.stderr)
            arms[arm] = parse(out)

        shared = set(arms["before"]) & set(arms["after"])
        if not shared:
            print("The probe printed nothing parseable in both arms. Print "
                  "metrics as `name 50/95/max` or `name=123`.",
                  file=sys.stderr)
            return 2
        for key in shared:
            before = arms["before"][key]
            if before:
                ratios[key].append(arms["after"][key] / before)

    print("\n".join(summarise(ratios, args.control, args.pairs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
