#!/usr/bin/env python3
"""Run a benchmark alternately against two arms and report the median ratio.

**This exists because a straight before-then-after comparison lied.** Five runs
of an optimized build followed by five of the original reported every metric
doubling — including one the change could not possibly affect. A laptop
throttles under sustained benchmarking, so whichever arm runs second loses,
and the effect is bigger than most optimizations.

Alternating before/after/before/after and taking the median of the *per-pair*
ratio cancels the drift, because both arms see the same machine on each pass.

Give it a probe command that prints numbers, and a swap command that puts the
tree into one arm or the other:

    paired_bench.py \\
      --probe 'flutter test tool/tuning/perf_probe.dart' \\
      --swap  './bench_swap.sh {arm}' \\
      --pairs 4

The probe's stdout is scanned for `label metric=NUMBER` pairs and for the
table shape `LABEL ... name 123/456/789` (median/p95/max), so most harnesses
need no adapting.

**Always keep a control metric** — something the change cannot affect. If the
control does not come back near 1.00x, the run is drift and the rest of the
table means nothing.
"""
from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
from collections import defaultdict

# `update 33/178/6133` — a name followed by slash-separated percentiles. The
# first is taken, because a median is what survives a noisy machine.
TABLE = re.compile(r"\b([A-Za-z][\w-]*)\s+(\d+)\s*/\s*\d+\s*/\s*\d+")
# `record=86` or `record: 86us`
INLINE = re.compile(r"\b([A-Za-z][\w-]*)\s*[=:]\s*(\d+(?:\.\d+)?)")
# A leading label that groups the metrics on a line, e.g. `L50 Boss Rush`.
ROW_LABEL = re.compile(r"^\s*(\S+)")


def parse(out: str) -> dict[str, float]:
    """Metrics keyed by `row.metric`, so two rows cannot collide.

    Duplicate keys get a `#n` suffix rather than overwriting. A table whose
    first column is `L 1` and `L 2` labels both rows `L`, and silently keeping
    only the last one would compare a level against a different level.
    """
    found: dict[str, float] = {}
    seen: dict[str, int] = {}
    for line in out.splitlines():
        matches = list(TABLE.finditer(line)) or list(INLINE.finditer(line))
        if not matches:
            continue
        label_match = ROW_LABEL.match(line)
        row = label_match.group(1) if label_match else ""
        for m in matches:
            name, value = m.group(1), float(m.group(2))
            if name == row:
                continue
            key = f"{row}.{name}" if row else name
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                key = f"{key}#{seen[key]}"
            found[key] = value
    return found


def run(cmd: str) -> str:
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, check=False
    )
    return result.stdout + result.stderr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", required=True,
                    help="command that runs the benchmark and prints numbers")
    ap.add_argument("--swap", required=True,
                    help="command to select an arm; {arm} is 'before'/'after'")
    ap.add_argument("--pairs", type=int, default=4,
                    help="alternating before/after rounds (default: 4)")
    ap.add_argument("--control", default="update",
                    help="substring of the metric the change cannot affect")
    args = ap.parse_args()

    ratios: dict[str, list[float]] = defaultdict(list)

    for pair in range(1, args.pairs + 1):
        arms: dict[str, dict[str, float]] = {}
        for arm in ("before", "after"):
            print(f"  pair {pair}/{args.pairs}: {arm} …",
                  file=sys.stderr, flush=True)
            swap = run(args.swap.replace("{arm}", arm))
            if "error" in swap.lower() and "0 error" not in swap.lower():
                print(f"swap reported: {swap.strip()[:200]}", file=sys.stderr)
            arms[arm] = parse(run(args.probe))

        shared = set(arms["before"]) & set(arms["after"])
        if not shared:
            print("The probe printed nothing this tool could parse. Print "
                  "metrics as `name 50/95/max` or `name=123`.", file=sys.stderr)
            return 2
        for key in shared:
            before = arms["before"][key]
            if before:
                ratios[key].append(arms["after"][key] / before)

    control = [statistics.median(v) for k, v in ratios.items()
               if args.control in k]
    control_median = statistics.median(control) if control else None

    print(f"\nmedian after/before over {args.pairs} alternating pairs\n")
    width = max(len(k) for k in ratios)
    for key in sorted(ratios):
        median = statistics.median(ratios[key])
        tag = "  <- control" if args.control in key else ""
        corrected = ""
        if control_median and args.control not in key:
            corrected = f"   corrected {median / control_median:.2f}x"
        print(f"  {key:<{width}}  {median:.2f}x{corrected}{tag}")

    if control_median is None:
        print("\nNo control metric matched. Add one the change cannot "
              "affect, or this table is unfalsifiable.")
    elif abs(control_median - 1) > 0.08:
        print(f"\nThe control moved {control_median:.2f}x. The machine "
              f"drifted between arms — read the corrected column, or rerun "
              f"with more pairs on a quieter machine.")
    else:
        print(f"\nControl at {control_median:.2f}x: the machine held still, "
              f"so the raw column is trustworthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
