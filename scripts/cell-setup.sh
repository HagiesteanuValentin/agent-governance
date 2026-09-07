#!/usr/bin/env bash
# Usage: cell-setup.sh <task> <run> [--dosar DIR] — see scripts/SCRIPTS.md
set -euo pipefail

# set to your project
MAMA="${MAMA:-${PROJECT:-${HOME}/workflow/proiecte/your-project}}"
EXPERIMENTE="${HOME}/workflow/experimente"
CELLS=(cell-opus-low cell-opus-medium cell-sonnet-medium cell-sonnet-low)

TASK="${1:-}"
RUN="${2:-}"
DOSAR=""

if [[ -z "$TASK" || -z "$RUN" ]]; then
  echo "Usage: cell-setup.sh <task> <run> [--dosar DIR]" >&2
  exit 1
fi
shift 2 || true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dosar)
      DOSAR="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$MAMA/.git" ]]; then
  echo "MAMA is not a git repo: $MAMA" >&2
  exit 1
fi

FIRST_WT=""

for CELL in "${CELLS[@]}"; do
  WT="$EXPERIMENTE/$TASK/${CELL}-${RUN}"
  BRANCH="exp/$TASK/${CELL}-${RUN}"

  if [[ -z "$FIRST_WT" ]]; then
    FIRST_WT="$WT"
  fi

  if [[ -d "$WT/.git" || -f "$WT/.git" ]]; then
    echo "OK (already exists) $WT"
  else
    mkdir -p "$EXPERIMENTE/$TASK"
    git -C "$MAMA" worktree add "$WT" -b "$BRANCH" master
    echo "CREATED $WT (branch $BRANCH)"
  fi

  if [[ -L "$WT/node_modules" ]]; then
    echo "OK (symlink already exists) $WT/node_modules"
  elif [[ -e "$WT/node_modules" ]]; then
    echo "WARNING: $WT/node_modules exists and is NOT a symlink — leaving it alone" >&2
  else
    ln -s "$MAMA/node_modules" "$WT/node_modules"
    echo "SYMLINK $WT/node_modules -> $MAMA/node_modules"
  fi

  if [[ -n "$DOSAR" ]]; then
    DEST="$WT/docs/dosar/$TASK"
    if [[ -d "$DEST" ]]; then
      echo "OK (dosar already exists) $DEST"
    else
      mkdir -p "$DEST"
      cp -r "$DOSAR/." "$DEST/"
      echo "COPIED $DOSAR -> $DEST/"
    fi
  fi
done

# --- baseline: npm run check in the first worktree ---
BASELINE_FILE="$(cd "$(dirname "$0")" && pwd)/cell-baseline-${TASK}.txt"
echo "Running 'npm run check' in $FIRST_WT ..."
set +e
CHECK_OUT="$(cd "$FIRST_WT" && npm run check 2>&1)"
CHECK_EXIT=$?
set -e

ERR_COUNT=$(grep -oiE '[0-9]+ error' <<<"$CHECK_OUT" | grep -oE '^[0-9]+' | head -1 || true)
WARN_COUNT=$(grep -oiE '[0-9]+ warning' <<<"$CHECK_OUT" | grep -oE '^[0-9]+' | head -1 || true)
ERR_COUNT="${ERR_COUNT:-0}"
WARN_COUNT="${WARN_COUNT:-0}"

{
  echo "task=$TASK run=$RUN worktree=$FIRST_WT"
  echo "exit=$CHECK_EXIT errors=$ERR_COUNT warnings=$WARN_COUNT"
  echo "--- output ---"
  echo "$CHECK_OUT"
} > "$BASELINE_FILE"

echo "BASELINE: exit=$CHECK_EXIT errors=$ERR_COUNT warnings=$WARN_COUNT -> $BASELINE_FILE"
