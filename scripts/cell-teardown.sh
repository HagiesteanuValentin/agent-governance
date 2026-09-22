#!/usr/bin/env bash
# Usage: cell-teardown.sh <task> <run> --yes — see scripts/SCRIPTS.md
set -euo pipefail

# set to your project
MAMA="${MAMA:-${PROJECT:-${HOME}/workflow/proiecte/your-project}}"
EXPERIMENTE="${HOME}/workflow/experimente"
CELLS=(cell-opus-low cell-opus-medium cell-sonnet-medium cell-sonnet-low cell-opus55-low cell-opus55-medium)

TASK="${1:-}"
RUN="${2:-}"
YES="false"

if [[ -z "$TASK" || -z "$RUN" ]]; then
  echo "Usage: cell-teardown.sh <task> <run> --yes" >&2
  exit 1
fi
shift 2 || true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) YES="true"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for CELL in "${CELLS[@]}"; do
  WT="$EXPERIMENTE/$TASK/${CELL}-${RUN}"
  BRANCH="exp/$TASK/${CELL}-${RUN}"

  if [[ ! -d "$WT" ]]; then
    echo "MISSING $WT"
    continue
  fi

  if [[ "$YES" != "true" ]]; then
    echo "WOULD DELETE: $WT (branch $BRANCH)"
    continue
  fi

  OK="true"
  if ! git -C "$MAMA" worktree remove --force "$WT" 2>&1; then
    echo "FAILED: worktree remove for $WT" >&2
    OK="false"
  fi
  if ! git -C "$MAMA" branch -D "$BRANCH" 2>&1; then
    echo "FAILED: branch -D for $BRANCH" >&2
    OK="false"
  fi
  if [[ "$OK" == "true" ]]; then
    echo "DELETED $WT + branch $BRANCH"
  else
    FAILED="true"
  fi
done

if [[ "${FAILED:-false}" == "true" ]]; then
  exit 1
fi
