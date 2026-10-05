#!/usr/bin/env python3
"""
Copy the final flat placements written by the routed tasks into the estimate
tasks.

For each suite (a directory containing a "routed" and an "estimate" task), the
final flat placement of every circuit in the latest run of the routed task
(<suite>/routed/runXXX/<arch>/<circuit>/common/final.fplace) is copied to
<suite>/estimate/flat_placements/<circuit name>.fplace, which is where the
estimate task reads it from.
"""

import argparse
import os
import re
import shutil
import sys


def find_suites(base_dir):
    """Find the suite directories (those with a routed and an estimate task)."""
    suites = []
    for name in sorted(os.listdir(base_dir)):
        suite_dir = os.path.join(base_dir, name)
        if os.path.isdir(os.path.join(suite_dir, "routed")) and os.path.isdir(
            os.path.join(suite_dir, "estimate")
        ):
            suites.append(name)
    return suites


def find_run_dir(task_dir, run_name=None):
    """Find the given run directory of a task, or the latest one if not given."""
    if run_name is not None:
        run_dir = os.path.join(task_dir, run_name)
        return run_dir if os.path.isdir(run_dir) else None
    runs = [d for d in os.listdir(task_dir) if re.fullmatch(r"run\d+", d)]
    if not runs:
        return None
    return os.path.join(task_dir, max(runs, key=lambda d: int(d[3:])))


def find_circuit_dirs(run_dir):
    """
    Find the common directory of every (arch, circuit) in a task run.
    Returns a dictionary from (arch, circuit) to the common directory.
    """
    circuit_dirs = {}
    for arch in sorted(os.listdir(run_dir)):
        arch_dir = os.path.join(run_dir, arch)
        if not os.path.isdir(arch_dir):
            continue
        for circuit in sorted(os.listdir(arch_dir)):
            common_dir = os.path.join(arch_dir, circuit, "common")
            if os.path.isdir(common_dir):
                circuit_dirs[(arch, circuit)] = common_dir
    return circuit_dirs


def circuit_base_name(circuit):
    """Get the name of a circuit without its file extension (e.g. bgm.blif -> bgm)."""
    return os.path.splitext(circuit)[0]


def main():
    """Main entry point."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument(
        "--suites",
        nargs="+",
        default=None,
        help="Suites to collect the flat placements of (default: all suites in this directory).",
    )
    parser.add_argument(
        "--run",
        default=None,
        help="Run of the routed tasks to collect from, e.g. run002 (default: the latest run).",
    )
    args = parser.parse_args()

    suites = args.suites if args.suites is not None else find_suites(base_dir)
    num_missing = 0
    for suite in suites:
        routed_task_dir = os.path.join(base_dir, suite, "routed")
        run_dir = find_run_dir(routed_task_dir, args.run)
        if run_dir is None:
            print(f"{suite}: no run of the routed task found in {routed_task_dir}")
            num_missing += 1
            continue

        dest_dir = os.path.join(base_dir, suite, "estimate", "flat_placements")
        os.makedirs(dest_dir, exist_ok=True)
        print(f"{suite}: collecting flat placements from {run_dir}")
        for (_, circuit), common_dir in find_circuit_dirs(run_dir).items():
            src = os.path.join(common_dir, "final.fplace")
            if not os.path.isfile(src):
                print(f"\tMISSING: {circuit} (no final.fplace; did the routed run fail?)")
                num_missing += 1
                continue
            dest = os.path.join(dest_dir, circuit_base_name(circuit) + ".fplace")
            shutil.copyfile(src, dest)
            print(f"\t{circuit} -> {os.path.relpath(dest, base_dir)}")

    if num_missing > 0:
        print(f"\n{num_missing} flat placement(s) could not be collected.")
        sys.exit(1)


if __name__ == "__main__":
    main()
