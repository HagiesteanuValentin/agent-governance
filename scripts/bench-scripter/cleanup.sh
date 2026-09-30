#!/usr/bin/env bash
# Usage: cleanup.sh [--dry-run] — see scripts/bench-scripter/README.md
set -uo pipefail
EXPERIMENTE="${EXPERIMENTE:-${HOME}/workflow/experimente}"
DIR="$EXPERIMENTE/bench-scripter"
[[ -d "$DIR" ]] || { echo "Nothing to delete ($DIR missing)"; exit 0; }
for P in "$DIR"/T*/*/ "$DIR"/T*/.verify-*/; do
  [[ -e "$P" ]] || continue
  case "$(realpath "$P")" in "$(realpath "$DIR")"/*) ;; *) echo "SKIP outside $DIR: $P"; continue ;; esac
  if [[ "${1:-}" == "--dry-run" ]]; then echo "WOULD DELETE $P"; else rm -rf "$P" && echo "DELETED $P"; fi
done
[[ "${1:-}" == "--dry-run" ]] || find "$DIR" -mindepth 1 -type d -empty -delete
