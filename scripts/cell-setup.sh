#!/usr/bin/env bash
# Uz: cell-setup.sh <task> <run> [--dosar DIR] — vezi scripts/SCRIPTS.md
set -euo pipefail

MAMA="/home/vali/workflow/proiecte/blueprint_pictura"
EXPERIMENTE="/home/vali/workflow/experimente"
CELLS=(cell-opus-low cell-opus-medium cell-sonnet-medium cell-sonnet-low)

TASK="${1:-}"
RUN="${2:-}"
DOSAR=""

if [[ -z "$TASK" || -z "$RUN" ]]; then
  echo "Uz: cell-setup.sh <task> <run> [--dosar DIR]" >&2
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
      echo "Argument necunoscut: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$MAMA/.git" ]]; then
  echo "Mama nu e repo git: $MAMA" >&2
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
    echo "OK (există deja) $WT"
  else
    mkdir -p "$EXPERIMENTE/$TASK"
    git -C "$MAMA" worktree add "$WT" -b "$BRANCH" master
    echo "CREAT $WT (branch $BRANCH)"
  fi

  if [[ -L "$WT/node_modules" ]]; then
    echo "OK (symlink există) $WT/node_modules"
  elif [[ -e "$WT/node_modules" ]]; then
    echo "ATENȚIE: $WT/node_modules există și NU e symlink — nu ating" >&2
  else
    ln -s "$MAMA/node_modules" "$WT/node_modules"
    echo "SYMLINK $WT/node_modules -> $MAMA/node_modules"
  fi

  if [[ -n "$DOSAR" ]]; then
    DEST="$WT/docs/dosar/$TASK"
    if [[ -d "$DEST" ]]; then
      echo "OK (dosar există deja) $DEST"
    else
      mkdir -p "$DEST"
      cp -r "$DOSAR/." "$DEST/"
      echo "COPIAT $DOSAR -> $DEST/"
    fi
  fi
done

# --- baseline: npm run check în primul worktree ---
BASELINE_FILE="$(cd "$(dirname "$0")" && pwd)/cell-baseline-${TASK}.txt"
echo "Rulez 'npm run check' în $FIRST_WT ..."
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
