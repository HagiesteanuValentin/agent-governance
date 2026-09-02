#!/usr/bin/env bash
# Uz: cell-teardown.sh <task> <run> --yes — vezi scripts/SCRIPTS.md
set -euo pipefail

MAMA="/home/vali/workflow/proiecte/blueprint_pictura"
EXPERIMENTE="/home/vali/workflow/experimente"
CELLS=(cell-opus-low cell-opus-medium cell-sonnet-medium cell-sonnet-low)

TASK="${1:-}"
RUN="${2:-}"
YES="false"

if [[ -z "$TASK" || -z "$RUN" ]]; then
  echo "Uz: cell-teardown.sh <task> <run> --yes" >&2
  exit 1
fi
shift 2 || true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) YES="true"; shift ;;
    *) echo "Argument necunoscut: $1" >&2; exit 1 ;;
  esac
done

for CELL in "${CELLS[@]}"; do
  WT="$EXPERIMENTE/$TASK/${CELL}-${RUN}"
  BRANCH="exp/$TASK/${CELL}-${RUN}"

  if [[ ! -d "$WT" ]]; then
    echo "LIPSĂ $WT"
    continue
  fi

  if [[ "$YES" != "true" ]]; then
    echo "AR ȘTERGE: $WT (branch $BRANCH)"
    continue
  fi

  OK="true"
  if ! git -C "$MAMA" worktree remove --force "$WT" 2>&1; then
    echo "EȘEC: worktree remove pentru $WT" >&2
    OK="false"
  fi
  if ! git -C "$MAMA" branch -D "$BRANCH" 2>&1; then
    echo "EȘEC: branch -D pentru $BRANCH" >&2
    OK="false"
  fi
  if [[ "$OK" == "true" ]]; then
    echo "ȘTERS $WT + branch $BRANCH"
  else
    FAILED="true"
  fi
done

if [[ "${FAILED:-false}" == "true" ]]; then
  exit 1
fi
