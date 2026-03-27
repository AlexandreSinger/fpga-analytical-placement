#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Update --seed value in script_params lines of all config.txt files in a directory."
    )
    parser.add_argument("path", type=Path, help="Path to the directory to search")
    parser.add_argument("--seed", type=int, required=True, help="Seed value to set")
    return parser.parse_args()


def update_seed_in_file(filepath: Path, seed: int) -> bool:
    """
    Update the --seed value in the script_params line of a config file.
    Returns True if the file was modified, False otherwise.
    """
    lines = filepath.read_text().splitlines(keepends=True)

    new_lines = []
    modified = False

    for line in lines:
        if line.startswith("script_params="):
            if re.search(r"--seed\s+\d+", line):
                # Replace existing --seed value
                new_line = re.sub(r"--seed\s+\d+", f"--seed {seed}", line)
            else:
                # Append --seed to the end of the line
                new_line = line.rstrip("\n") + f" --seed {seed}\n"

            if new_line != line:
                modified = True
            new_lines.append(new_line)
        else:
            new_lines.append(line)

    if modified:
        filepath.write_text("".join(new_lines))

    return modified


def main():
    args = parse_args()

    if not args.path.is_dir():
        print(f"Error: '{args.path}' is not a valid directory.")
        sys.exit(1)

    config_files = list(args.path.rglob("config.txt"))

    if not config_files:
        print(f"No config.txt files found in '{args.path}'.")
        sys.exit(0)

    updated = 0
    skipped = 0

    for cfg in config_files:
        if not cfg.is_file():
            continue
        if update_seed_in_file(cfg, args.seed):
            print(f"  [updated] {cfg}")
            updated += 1
        else:
            print(f"  [skip]    {cfg}  (no script_params line found)")
            skipped += 1

    print(f"\nDone. {updated} file(s) updated, {skipped} file(s) skipped.")


if __name__ == "__main__":
    main()
