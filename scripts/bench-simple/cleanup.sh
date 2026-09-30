#!/usr/bin/env bash
# Usage: cleanup.sh [--dry-run] — see scripts/SCRIPTS.md
set -uo pipefail
EXPERIMENTE="${EXPERIMENTE:-${HOME}/workflow/experimente}"
PREFIX="${PREFIX:-bench-simple}"
DIR="$EXPERIMENTE/$PREFIX"
[[ -d "$DIR" ]] || { echo "Nothing to delete ($DIR missing)"; exit 0; }
for WT in "$DIR"/T*/*/; do
  [[ -d "$WT" ]] || continue
  if [[ "${1:-}" == "--dry-run" ]]; then echo "WOULD DELETE $WT"; else rm -rf "$WT" && echo "DELETED $WT"; fi
done
[[ "${1:-}" == "--dry-run" ]] || find "$DIR" -type d -empty -delete
