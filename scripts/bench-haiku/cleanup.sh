#!/usr/bin/env bash
# Usage: cleanup.sh [--dry-run] — see scripts/bench-haiku/README.md
set -uo pipefail
DIR="${BENCH_ROOT:-${HOME}/workflow/experimente/bench-haiku}"
[[ -d "$DIR" ]] || { echo "Nothing to delete ($DIR missing)"; exit 0; }
for P in "$DIR"/explorer/*/ "$DIR"/explorer-max/*/ "$DIR"/scribe/*/; do
  [[ -e "$P" ]] || continue
  case "$(realpath "$P")" in "$(realpath "$DIR")"/*) ;; *) echo "SKIP outside $DIR: $P"; continue ;; esac
  if [[ "${1:-}" == "--dry-run" ]]; then echo "WOULD DELETE $P"; else rm -rf "$P" && echo "DELETED $P"; fi
done
[[ "${1:-}" == "--dry-run" ]] || find "$DIR" -mindepth 1 -type d -empty -delete
echo "kept: tasks/, ref/, audit/, audit-mapping-*.json, summary.*"
