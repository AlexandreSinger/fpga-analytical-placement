#!/usr/bin/env python3
"""
Parse the results of the legality estimation experiment.

For every circuit in every suite, this parses the legality estimate of the
global placement from the VPR log ("Legality Estimate Summary") and the
per-tile penalty from the legality echo file (legality.ap_estimate.echo), and
produces:
    - results/legality_estimation_results.csv: One row per circuit with the
      legality estimate (pins in violation, raw and normalized by the number
      of connected pins), the pins in violation of each rule, the sanity
      counters, the post-global
      placement wirelength / CPD / sTNS estimates, and the run time of global
      placement.
    - results/legality_tile_types.csv: One row per (circuit, tile type) with
      the number of occupied tiles, the number of tiles with a violation, the
      pins in violation of each rule, and the tile pin demand (how many tiles
      are over the capacity of each class of tile pin, and the largest demand
      / capacity ratio).

A summary of each circuit, the share of the pins in violation charged to each
rule per suite, and the tile types with the most pins in violation per suite
are also printed. With --worst_tiles, the worst tiles of each circuit (as
printed in the VPR log) are printed too.

By default the gp tasks are parsed (the legality estimate of the global
placement made in the same run). Use --task reestimate to parse the
re-estimate tasks instead, and --check_reestimate to verify that the
re-estimate of the written global placement matches the estimate made during
global placement (any difference is either a bug in writing / reading the
flat placement, or non-determinism in the estimator).
"""

import argparse
import csv
import math
import os
import re
import sys
from collections import defaultdict
from multiprocessing import Pool

# pylint: disable-next=wrong-import-position
from collect_gp_placements import (
    find_circuit_dirs,
    find_run_dir,
    find_suites,
    read_task_config_jobs,
    task_dir,
)

LEGALITY_ECHO = "legality.ap_estimate.echo"

LEGALITY_SUMMARY_HEADER = "Legality Estimate Summary:"

# Patterns of the values in the legality summary, and the row keys they are
# stored in. Each pattern captures one value per key.
LEGALITY_SUMMARY_PATTERNS = [
    (
        re.compile(r"Pins in violation: (\d+) \((\S+) of (\d+) connected pins\)"),
        ("legality_pins", "legality_norm_pins", "legality_connected_pins"),
    ),
    (
        re.compile(r"Chains with a fixed offset: (\d+) \((\d+) broken\)"),
        ("legality_num_chains", "legality_broken_chains"),
    ),
    (re.compile(r"Primitives placed outside of the device: (\d+)"), ("legality_off_device",)),
    (
        re.compile(r"Evicted primitives with no compatible tile: (\d+)"),
        ("legality_no_compatible_tile",),
    ),
    (re.compile(r"Molecules split across tiles: (\d+)"), ("legality_split_molecules",)),
]
# NOTE: Logs from before the pin-weighted displacement was removed print
#       "<pins> / <displacement>"; the displacement is ignored.
LEGALITY_RULE_PATTERN = re.compile(r"Rule (\w+): (\d+)(?: / \S+)?$")
# A line of the per tile type section: "<tile type>: <pins>".
LEGALITY_TILE_TYPE_PATTERN = re.compile(r"^\t\t(\S+): (\d+)(?: / \S+)?$")
# A line of the worst tiles section.
LEGALITY_WORST_TILE_PATTERN = re.compile(r"^\t\t(\S+ at \(.*\): .*)$")

# Values parsed from the VPR log, and the row keys they are stored in.
LOG_PATTERNS = [
    (re.compile(r"Placement estimated wirelength: (\S+)"), "post_gp_wirelength"),
    (re.compile(r"Placement estimated CPD: (\S+) ns"), "post_gp_cpd_ns"),
    (re.compile(r"Placement estimated sTNS: (\S+) ns"), "post_gp_stns_ns"),
    (re.compile(r"AP Global Placer took (\S+) seconds"), "gp_time_s"),
    (
        re.compile(r"Analytical Placement took (\S+) seconds \(max_rss (\S+) MiB"),
        ("ap_time_s", "ap_max_rss_mib"),
    ),
    (re.compile(r"The entire flow of VPR took (\S+) seconds"), "vpr_time_s"),
]

# The tile pin classes of the echo file: (demand column, capacity column).
PIN_CLASSES = {
    "in_regular": ("in_regular", "in_regular_cap"),
    "in_global": ("in_global", "in_global_cap"),
    "in_clock": ("in_clock", "in_clock_cap"),
    "out": ("out", "out_cap"),
}

CSV_COLUMNS = [
    "suite",
    "arch",
    "circuit",
    "vpr_status",
    "legality_connected_pins",
    "legality_pins",
    "legality_norm_pins",
    "legality_off_device",
    "legality_no_compatible_tile",
    "legality_split_molecules",
    # The per-rule columns are inserted here (see _legality_rule_columns).
    "post_gp_wirelength",
    "post_gp_cpd_ns",
    "post_gp_stns_ns",
    "gp_time_s",
    "ap_time_s",
    "ap_max_rss_mib",
    "vpr_time_s",
    "reestimate_mismatch",
    "error",
]

TILE_TYPE_CSV_COLUMNS = [
    "suite",
    "circuit",
    "tile_type",
    "occupied_tiles",
    "tiles_in_violation",
    "num_prims",
    "num_pins",
    "pins_in_violation",
    # The per-rule columns (rule_<name>) are inserted here.
    *[f"{pin_class}_{stat}" for pin_class in PIN_CLASSES for stat in ("over_cap", "max_ratio")],
]


# ---------------------------------------------------------------------------
# Parsing the VPR logs.
# ---------------------------------------------------------------------------


def parse_log(common_dir):
    """
    Parse the VPR log of a circuit.

    Returns a dict with the VPR status, the values of LOG_PATTERNS, and the
    first legality summary in the log: the total score (legality_pins, raw
    and normalized by legality_connected_pins), the sanity counters, the pins
    in violation of each rule (legality_rule_<name>_pins), the pins in
    violation of each tile type (legality_tile_types: {name: pins}), and the
    worst tiles (legality_worst_tiles: [line]).
    """
    log_file = os.path.join(common_dir, "vpr.out")
    values = {"legality_tile_types": {}, "legality_worst_tiles": []}
    if not os.path.isfile(log_file):
        values["vpr_status"] = "missing"
        return values
    values["vpr_status"] = "unknown"
    # The section of the legality summary currently being parsed (None if
    # not in the summary, "" if in the summary but not in a sub-section).
    section = None
    summary_done = False
    with open(log_file, "r", encoding="utf-8", errors="replace") as log:
        for line in log:
            if "VPR succeeded" in line:
                values["vpr_status"] = "success"
            elif "VPR failed" in line:
                values["vpr_status"] = "failed"

            for pattern, keys in LOG_PATTERNS:
                match = pattern.search(line)
                if match:
                    keys = (keys,) if isinstance(keys, str) else keys
                    values.update(zip(keys, (float(v) for v in match.groups())))
                    break

            if summary_done:
                continue
            if section is None:
                if LEGALITY_SUMMARY_HEADER in line:
                    section = ""
                continue
            # The summary is the block of tab-indented lines after the header.
            if not line.startswith("\t"):
                summary_done = True
                section = None
                continue
            line = line.rstrip("\n")
            if not line.startswith("\t\t"):
                section = line.strip()
            match = LEGALITY_RULE_PATTERN.search(line)
            if match:
                prefix = f"legality_rule_{match.group(1)}"
                values[f"{prefix}_pins"] = float(match.group(2))
                continue
            if section.startswith("Per tile type"):
                match = LEGALITY_TILE_TYPE_PATTERN.match(line)
                if match:
                    values["legality_tile_types"][match.group(1)] = float(match.group(2))
                continue
            if section.startswith("Worst"):
                match = LEGALITY_WORST_TILE_PATTERN.match(line)
                if match:
                    values["legality_worst_tiles"].append(match.group(1))
                continue
            for pattern, keys in LEGALITY_SUMMARY_PATTERNS:
                match = pattern.search(line)
                if match:
                    values.update(zip(keys, (float(v) for v in match.groups())))
                    break
    return values


# ---------------------------------------------------------------------------
# Parsing the legality echo files.
# ---------------------------------------------------------------------------


def parse_legality_echo(filename):
    """
    Parse the per-tile legality echo file, and aggregate it per tile type.

    Returns a dict from tile type name to a dict of the stats of that tile
    type (see TILE_TYPE_CSV_COLUMNS), or None if the file does not exist.
    """
    if not os.path.isfile(filename):
        return None
    tile_types = {}
    header = None
    rule_columns = []
    with open(filename, "r", encoding="utf-8") as echo:
        for line in echo:
            if line.startswith("#") or not line.strip():
                continue
            fields = line.split()
            if header is None:
                header = fields
                rule_columns = [c for c in header if c.startswith("rule_")]
                continue
            tile = dict(zip(header, fields))
            stats = tile_types.get(tile["tile_type"])
            if stats is None:
                stats = defaultdict(float)
                for pin_class in PIN_CLASSES:
                    stats[f"{pin_class}_max_ratio"] = 0.0
                tile_types[tile["tile_type"]] = stats
            pins_in_violation = float(tile["pins_in_viol"])
            stats["occupied_tiles"] += 1
            stats["tiles_in_violation"] += pins_in_violation > 0
            stats["num_prims"] += float(tile["num_prims"])
            stats["num_pins"] += float(tile["num_pins"])
            stats["pins_in_violation"] += pins_in_violation
            for rule_column in rule_columns:
                stats[rule_column] += float(tile[rule_column])
            for pin_class, (demand_column, cap_column) in PIN_CLASSES.items():
                demand, cap = float(tile[demand_column]), float(tile[cap_column])
                stats[f"{pin_class}_over_cap"] += demand > cap
                if cap > 0:
                    ratio = demand / cap
                elif demand > 0:
                    ratio = math.inf
                else:
                    ratio = 0.0
                stats[f"{pin_class}_max_ratio"] = max(stats[f"{pin_class}_max_ratio"], ratio)
    return {name: dict(stats) for name, stats in tile_types.items()}


# ---------------------------------------------------------------------------
# Parsing a circuit.
# ---------------------------------------------------------------------------


def _legality_key_values(row):
    """The legality values of a row which must match between two estimates."""
    return {
        key: value
        for key, value in row.items()
        if key.startswith("legality_") and isinstance(value, float)
    }


def parse_circuit(job):
    """Parse the results of a circuit. Returns (row, tile type rows)."""
    suite, arch, circuit, common_dir, reestimate_dir = job
    row = {"suite": suite, "arch": arch, "circuit": circuit}
    log_values = parse_log(common_dir)
    tile_type_penalties = log_values.pop("legality_tile_types")
    row["legality_worst_tiles"] = log_values.pop("legality_worst_tiles")
    row.update(log_values)

    errors = []
    if "legality_pins" not in row:
        errors.append("no legality summary in vpr.out")
    if row["vpr_status"] != "success":
        errors.append(f"VPR status: {row['vpr_status']}")

    if reestimate_dir is not None:
        reestimate = parse_log(reestimate_dir)
        expected, actual = _legality_key_values(row), _legality_key_values(reestimate)
        mismatches = [
            key
            for key in sorted(set(expected) | set(actual))
            if not math.isclose(expected.get(key, math.nan), actual.get(key, math.nan),
                                rel_tol=1e-6, abs_tol=1e-6)
        ]
        row["reestimate_mismatch"] = " ".join(
            f"{key}={expected.get(key)}->{actual.get(key)}" for key in mismatches
        )

    tile_types = parse_legality_echo(os.path.join(common_dir, LEGALITY_ECHO))
    tile_type_rows = []
    if tile_types is None:
        errors.append(f"no {LEGALITY_ECHO}")
    else:
        for name, stats in sorted(tile_types.items()):
            tile_type_rows.append({"suite": suite, "circuit": circuit, "tile_type": name, **stats})
        # The echo file only has the occupied tiles, so it must agree with
        # the per tile type penalty of the log.
        for name in sorted(set(tile_type_penalties) | set(tile_types)):
            if name == "<off-device>":
                continue
            log_pins = tile_type_penalties.get(name, 0.0)
            echo_pins = tile_types.get(name, {}).get("pins_in_violation", 0.0)
            if echo_pins != log_pins:
                errors.append(f"{name}: {log_pins:.0f} pins in the log, {echo_pins:.0f} in the echo file")

    row["error"] = "; ".join(errors)
    return row, tile_type_rows


# ---------------------------------------------------------------------------
# Writing and printing the results.
# ---------------------------------------------------------------------------


def _legality_rule_columns(rows):
    """The per-rule legality columns of the rows, in the order they first appear."""
    columns = []
    for row in rows:
        for key in row:
            if key.startswith("legality_rule") and key not in columns:
                columns.append(key)
    return columns


def _rule_names(rows):
    """The names of the legality rules of the rows, in the order they first appear."""
    return [
        column[len("legality_rule_"):-len("_pins")]
        for column in _legality_rule_columns(rows)
        if column.endswith("_pins")
    ]


def write_csv(rows, filename):
    """Write the results of every circuit to a CSV file."""
    insert_idx = CSV_COLUMNS.index("post_gp_wirelength")
    fieldnames = CSV_COLUMNS[:insert_idx] + _legality_rule_columns(rows) + CSV_COLUMNS[insert_idx:]
    with open(filename, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_tile_type_csv(tile_type_rows, filename):
    """Write the results of every (circuit, tile type) to a CSV file."""
    rule_columns = []
    for row in tile_type_rows:
        for key in row:
            if key.startswith("rule_") and key not in rule_columns:
                rule_columns.append(key)
    insert_idx = TILE_TYPE_CSV_COLUMNS.index("pins_in_violation") + 1
    fieldnames = (
        TILE_TYPE_CSV_COLUMNS[:insert_idx] + rule_columns + TILE_TYPE_CSV_COLUMNS[insert_idx:]
    )
    with open(filename, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(tile_type_rows)


def _finite(value):
    return value is not None and isinstance(value, float) and math.isfinite(value)


def _fmt(value, spec):
    """Format a value, padding the placeholder of missing values to the width of the column."""
    width = spec.split(".")[0].lstrip("<>")
    return format(value, spec) if _finite(value) else format("-", f">{width}")


def print_circuit_summary(rows, num_worst_tiles):
    """Print the legality estimate of each circuit."""
    rules = _rule_names(rows)
    print(
        f"{'suite':<12} {'circuit':<40} {'conn pins':>10} {'pins':>9} {'norm pins':>9} "
        f"{'off':>5} {'no tile':>7} {'split':>5} "
        + " ".join(f"{rule[:12]:>12}" for rule in rules)
        + f" {'GP (s)':>8}"
    )
    for row in rows:
        print(
            f"{row['suite']:<12} {row['circuit']:<40} "
            f"{_fmt(row.get('legality_connected_pins'), '10.0f')} "
            f"{_fmt(row.get('legality_pins'), '9.0f')} "
            f"{_fmt(row.get('legality_norm_pins'), '9.4f')} "
            f"{_fmt(row.get('legality_off_device'), '5.0f')} "
            f"{_fmt(row.get('legality_no_compatible_tile'), '7.0f')} "
            f"{_fmt(row.get('legality_split_molecules'), '5.0f')} "
            + " ".join(_fmt(row.get(f"legality_rule_{rule}_pins"), "12.0f") for rule in rules)
            + f" {_fmt(row.get('gp_time_s'), '8.1f')}"
            + (f"  ERROR: {row['error']}" if row.get("error") else "")
            + (f"  REESTIMATE MISMATCH: {row['reestimate_mismatch']}"
               if row.get("reestimate_mismatch") else "")
        )
        if num_worst_tiles > 0:
            for tile in row["legality_worst_tiles"][:num_worst_tiles]:
                print(f"\t\t{tile}")


def print_suite_summary(rows):
    """
    Print, per suite, the geomean of the normalized pins in violation, and
    the share of the pins in violation charged to each rule.
    """
    rules = _rule_names(rows)
    print("\nPer suite (geomean over circuits with a non-zero score; share of pins in violation per rule):")
    print(
        f"\t{'suite':<12} {'circuits':>8} {'non-zero':>8} {'norm pins':>9} "
        + " ".join(f"{rule[:12]:>12}" for rule in rules)
    )
    for suite in sorted({row["suite"] for row in rows}):
        suite_rows = [row for row in rows if row["suite"] == suite and _finite(row.get("legality_pins"))]
        nonzero = [row for row in suite_rows if row["legality_pins"] > 0]
        total_pins = sum(row["legality_pins"] for row in suite_rows)
        shares = []
        for rule in rules:
            rule_pins = sum(row.get(f"legality_rule_{rule}_pins", 0.0) for row in suite_rows)
            shares.append(rule_pins / total_pins if total_pins > 0 else math.nan)
        print(
            f"\t{suite:<12} {len(suite_rows):>8} {len(nonzero):>8} "
            f"{_fmt(_geomean([r['legality_norm_pins'] for r in nonzero]), '9.4f')} "
            + " ".join(_fmt(share, "12.3f") for share in shares)
        )


def print_tile_type_summary(tile_type_rows):
    """
    Print, per suite and tile type, the pins in violation of each rule, and
    how many occupied tiles are over the capacity of each class of tile pin.
    """
    rule_columns = list(dict.fromkeys(key for row in tile_type_rows for key in row if key.startswith("rule_")))
    totals = defaultdict(lambda: defaultdict(float))
    for row in tile_type_rows:
        total = totals[(row["suite"], row["tile_type"])]
        for key, value in row.items():
            if isinstance(value, float):
                if key.endswith("_max_ratio"):
                    total[key] = max(total[key], value)
                else:
                    total[key] += value
    print("\nPer suite and tile type (summed over circuits):")
    print(
        f"\t{'suite':<12} {'tile type':<14} {'tiles':>8} {'in viol':>8} {'pins':>9} "
        + " ".join(f"{c[len('rule_'):][:12]:>12}" for c in rule_columns)
        + " " + " ".join(f"{p + ' >cap':>14}" for p in PIN_CLASSES)
        + " " + " ".join(f"{p + ' max':>14}" for p in PIN_CLASSES)
    )
    for (suite, tile_type), total in sorted(totals.items()):
        print(
            f"\t{suite:<12} {tile_type[:14]:<14} {total['occupied_tiles']:>8.0f} "
            f"{total['tiles_in_violation']:>8.0f} {total['pins_in_violation']:>9.0f} "
            + " ".join(f"{total[c]:>12.0f}" for c in rule_columns)
            + " " + " ".join(f"{total[p + '_over_cap']:>14.0f}" for p in PIN_CLASSES)
            + " " + " ".join(_fmt(total[p + "_max_ratio"], "14.2f") for p in PIN_CLASSES)
        )


def _geomean(values):
    values = [v for v in values if _finite(v) and v > 0]
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else math.nan


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------


def collect_jobs(base_dir, suites, args):
    """Find the run directory of every circuit."""
    jobs = []
    for suite in suites:
        parse_task_dir = task_dir(base_dir, suite, args.task)
        run_dir = find_run_dir(parse_task_dir, args.run)
        if run_dir is None:
            print(f"{suite}: skipping, no run of the {args.task} task")
            continue
        reestimate_run_dir = None
        if args.check_reestimate:
            reestimate_run_dir = find_run_dir(
                task_dir(base_dir, suite, "reestimate"), args.reestimate_run
            )
            if reestimate_run_dir is None:
                print(f"{suite}: no run of the reestimate task to check against")
        print(
            f"{suite}: {args.task} {run_dir}"
            + (f", reestimate {reestimate_run_dir}" if reestimate_run_dir else "")
        )
        # Only the circuits in the task's config are parsed; any other
        # directories in the run are ignored.
        config_jobs = read_task_config_jobs(parse_task_dir)
        circuit_dirs = find_circuit_dirs(run_dir, config_jobs)
        reestimate_dirs = (
            find_circuit_dirs(reestimate_run_dir, config_jobs) if reestimate_run_dir else {}
        )
        for key in sorted(config_jobs):
            if circuit_dirs[key] is None:
                print(f"\tskipping {key[1]}: not in the run")
                continue
            jobs.append((suite, key[0], key[1], circuit_dirs[key], reestimate_dirs.get(key)))
    return jobs


def main():
    """Main entry point."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(
        description="Parse the results of the legality estimation experiment."
    )
    parser.add_argument("--suites", nargs="+", default=None, help="Suites to parse (default: all).")
    parser.add_argument(
        "--task",
        choices=["gp", "reestimate"],
        default="gp",
        help="The task to parse the legality estimate of (default: gp).",
    )
    parser.add_argument("--run", default=None, help="Run of the parsed task (default: latest).")
    parser.add_argument(
        "--check_reestimate",
        action="store_true",
        help="Check that the legality estimate of the reestimate task matches the parsed task.",
    )
    parser.add_argument(
        "--reestimate_run",
        default=None,
        help="Run of the reestimate task to check against (default: latest).",
    )
    parser.add_argument(
        "--worst_tiles",
        type=int,
        default=0,
        help="Number of the worst tiles of each circuit to print (default: 0).",
    )
    parser.add_argument(
        "--output_dir",
        default=os.path.join(base_dir, "results"),
        help="Directory to write the results to (default: results).",
    )
    parser.add_argument(
        "-j", type=int, default=1, help="Number of circuits to parse in parallel (default: 1)."
    )
    args = parser.parse_args()

    suites = args.suites if args.suites is not None else find_suites(base_dir, args.task)
    jobs = collect_jobs(base_dir, suites, args)
    if not jobs:
        sys.exit("No circuits to parse.")

    rows, tile_type_rows = [], []
    with Pool(max(1, args.j)) as pool:
        for row, circuit_tile_type_rows in pool.imap(parse_circuit, jobs):
            rows.append(row)
            tile_type_rows.extend(circuit_tile_type_rows)

    print()
    print_circuit_summary(rows, args.worst_tiles)
    print_suite_summary(rows)
    print_tile_type_summary(tile_type_rows)

    os.makedirs(args.output_dir, exist_ok=True)
    write_csv(rows, os.path.join(args.output_dir, "legality_estimation_results.csv"))
    write_tile_type_csv(tile_type_rows, os.path.join(args.output_dir, "legality_tile_types.csv"))
    print(f"\nResults written to {args.output_dir}")


if __name__ == "__main__":
    main()
