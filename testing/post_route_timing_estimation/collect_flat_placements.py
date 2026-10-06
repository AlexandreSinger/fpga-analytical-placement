#!/usr/bin/env python3
"""
Copy the final flat placements written by the routed tasks into the estimate
tasks.

For each suite (a directory containing a <suite>_routed and a <suite>_estimate
task), the final flat placement of every circuit in the latest run of the
routed task
(<suite>/<suite>_routed/runXXX/<arch>/<circuit>/common/final.fplace) is copied
to <suite>/<suite>_estimate/flat_placements/<circuit name>.fplace, which is
where the estimate task reads it from.

Only the architectures and circuits listed in the routed task's config are
collected; any other directories in the run directory are ignored.
"""

import argparse
import os
import re
import shutil
import sys


def task_dir(base_dir, suite, kind):
    """Get the directory of the given kind of task ("routed" or "estimate") of a suite."""
    return os.path.join(base_dir, suite, f"{suite}_{kind}")


def find_suites(base_dir):
    """Find the suite directories (those with a routed and an estimate task)."""
    return [
        name
        for name in sorted(os.listdir(base_dir))
        if os.path.isdir(task_dir(base_dir, name, "routed"))
        and os.path.isdir(task_dir(base_dir, name, "estimate"))
    ]


def find_run_dir(run_parent_dir, run_name=None):
    """Find the given run directory of a task, or the latest one if not given."""
    if run_name is not None:
        run_dir = os.path.join(run_parent_dir, run_name)
        return run_dir if os.path.isdir(run_dir) else None
    if not os.path.isdir(run_parent_dir):
        return None
    runs = [d for d in os.listdir(run_parent_dir) if re.fullmatch(r"run\d+", d)]
    if not runs:
        return None
    return os.path.join(run_parent_dir, max(runs, key=lambda d: int(d[3:])))


def read_task_config_jobs(config_task_dir):
    """
    Get the (arch, circuit) pairs listed in a task's config. These are the
    names of the arch and circuit directories in the task's run directories.
    """
    archs, circuits = [], []
    config_file = os.path.join(config_task_dir, "config", "config.txt")
    with open(config_file, "r", encoding="utf-8") as config:
        for line in config:
            line = line.split("#")[0].strip()
            if line.startswith("arch_list_add="):
                archs.append(line.split("=", 1)[1].strip())
            elif line.startswith("circuit_list_add="):
                circuits.append(line.split("=", 1)[1].strip())
    return {(arch, circuit) for arch in archs for circuit in circuits}


def find_circuit_dirs(run_dir, config_jobs):
    """
    Find the common directory of every (arch, circuit) of the task's config
    in a task run. Returns a dictionary from (arch, circuit) to the common
    directory, which is None if the circuit's directory does not exist.
    """
    circuit_dirs = {}
    for arch, circuit in sorted(config_jobs):
        common_dir = os.path.join(run_dir, arch, circuit, "common")
        circuit_dirs[(arch, circuit)] = common_dir if os.path.isdir(common_dir) else None
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
        routed_task_dir = task_dir(base_dir, suite, "routed")
        run_dir = find_run_dir(routed_task_dir, args.run)
        if run_dir is None:
            print(f"{suite}: no run of the routed task found in {routed_task_dir}")
            num_missing += 1
            continue

        dest_dir = os.path.join(task_dir(base_dir, suite, "estimate"), "flat_placements")
        os.makedirs(dest_dir, exist_ok=True)
        print(f"{suite}: collecting flat placements from {run_dir}")
        config_jobs = read_task_config_jobs(routed_task_dir)
        for (_, circuit), common_dir in find_circuit_dirs(run_dir, config_jobs).items():
            src = None if common_dir is None else os.path.join(common_dir, "final.fplace")
            if src is None or not os.path.isfile(src):
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
