#!/usr/bin/env bash
# Usage: verify.sh <A|B|C> <worktree> [--base REV] [--no-build] — see scripts/SCRIPTS.md
set -uo pipefail
TASK="${1:?task A|B|C}"; WT="$(cd "${2:?worktree}" && pwd)"; shift 2
LOG="${TMPDIR:-/tmp}/verify-${TASK}-$(basename "$WT").log"
BASE="HEAD"; BUILD="true"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --no-build) BUILD="false"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
BUILD_EXIT=0
if [[ "$BUILD" == "true" ]]; then
  (cd "$WT" && npm run build >"$LOG" 2>&1); BUILD_EXIT=$?
  if [[ $BUILD_EXIT -eq 0 ]]; then echo "PASS npm run build exit 0"; else echo "FAIL npm run build exit $BUILD_EXIT (log: $LOG)"; fi
fi
python3 "$(dirname "$0")/checks.py" "$TASK" "$WT" --base "$BASE"; CHECK_EXIT=$?
[[ $BUILD_EXIT -eq 0 && $CHECK_EXIT -eq 0 ]]
