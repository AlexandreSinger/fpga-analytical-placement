#!/usr/bin/env bash
#
# collect_blif.sh - Copy all *.pre-vpr.blif files from a source tree into a
#                   single destination directory, renaming them to *.blif
#
# Usage: ./collect_blif.sh [-p] SOURCE_DIR DEST_DIR
#   -p   prefix each file with its parent directory name to avoid collisions
#
set -euo pipefail

prefix_parent=0

usage() {
    echo "Usage: $0 [-p] SOURCE_DIR DEST_DIR" >&2
    echo "  -p   prefix each copied file with its parent directory name" >&2
    exit 1
}

while getopts ":p" opt; do
    case "$opt" in
        p) prefix_parent=1 ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))

[ "$#" -eq 2 ] || usage

src=$1
dest=$2

if [ ! -d "$src" ]; then
    echo "Error: source directory '$src' does not exist" >&2
    exit 1
fi

mkdir -p "$dest"

count=0
while IFS= read -r -d '' f; do
    base=$(basename "$f" .pre-vpr.blif)
    if [ "$prefix_parent" -eq 1 ]; then
        base="$(basename "$(dirname "$f")")_${base}"
    fi
    target="$dest/${base}.blif"
    if [ -e "$target" ]; then
        echo "Warning: '$target' already exists, overwriting (consider -p)" >&2
    fi
    cp "$f" "$target"
    count=$((count + 1))
done < <(find "$src" -type f -name '*.pre-vpr.blif' -print0)

echo "Copied $count file(s) into '$dest'"
