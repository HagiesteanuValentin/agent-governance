#!/usr/bin/env bash
# Usage: setup.sh <T1..T4> <run> [--ref] — see scripts/SCRIPTS.md
set -euo pipefail
PROIECTE="${PROIECTE:-${HOME}/workflow/proiecte}"
EXPERIMENTE="${EXPERIMENTE:-${HOME}/workflow/experimente}"
PREFIX="${PREFIX:-bench-simple}"
DEFAULT_CELLS="cell-sonnet55-medium cell-opus55-low"
read -r -a CELLS <<<"${CELLS:-$DEFAULT_CELLS}"
CHECK="${CHECK:-npm run check}"

TASK="${1:-}"; RUN="${2:-}"; REF_MODE="false"
[[ -z "$TASK" || -z "$RUN" ]] && { echo "Usage: setup.sh <T1..T4> <run> [--ref]" >&2; exit 1; }
[[ "${3:-}" == "--ref" ]] && REF_MODE="true"

case "$TASK" in
  T1) REPO=site_ac; REF=4efdb02; FILES="src/components/SEO.astro" ;;
  T2) REPO=blueprint_pictura; REF=2c7ad6a; FILES="src/components/CardLucrare.astro src/components/Galerie3D.astro" ;;
  T3) REPO=site_ac; REF=b1a1dcf; FILES="src/content/faq" ;;
  T4) REPO=blueprint_prezentare; REF=a1c6197; FILES="src/pages/produs/[slug].astro src/styles/produs.css" ;;
  *) echo "Unknown task: $TASK" >&2; exit 1 ;;
esac
MAMA="$PROIECTE/$REPO"
BASE="$REF^"

if [[ "$REF_MODE" == "true" ]]; then CELLS=(ref); fi

FIRST_WT=""
for CELL in "${CELLS[@]}"; do
  WT="$EXPERIMENTE/$PREFIX/$TASK/${CELL}-${RUN}"
  [[ -z "$FIRST_WT" ]] && FIRST_WT="$WT"
  if [[ -d "$WT/.git" ]]; then
    echo "OK (already exists) $WT"
  else
    mkdir -p "$WT"
    git -C "$MAMA" archive "$BASE" | tar -x -C "$WT"
    if [[ "$TASK" == "T1" ]]; then
      git -C "$MAMA" archive "$REF" public/og/termclima.png | tar -x -C "$WT"
    fi
    git -C "$WT" init -q
    git -C "$WT" add -A
    git -C "$WT" -c user.name=bench -c user.email=bench@local commit -qm base
    echo "CREATED $WT (base = $REPO $BASE, no history)"
    if [[ "$REF_MODE" == "true" ]]; then
      # shellcheck disable=SC2086
      git -C "$MAMA" archive "$REF" -- $FILES | tar -x -C "$WT"
      echo "OVERLAID ref $REF files onto working tree (uncommitted)"
    fi
  fi
  if [[ -L "$WT/node_modules" ]]; then
    echo "OK (symlink already exists) $WT/node_modules"
  else
    ln -s "$MAMA/node_modules" "$WT/node_modules"
    echo "SYMLINK $WT/node_modules -> $MAMA/node_modules"
  fi
  grep -qx "node_modules" "$WT/.git/info/exclude" 2>/dev/null || echo "node_modules" >> "$WT/.git/info/exclude"
done

[[ "$REF_MODE" == "true" ]] && exit 0
BASELINE_FILE="$(cd "$(dirname "$0")" && pwd)/baseline-${TASK}.txt"
set +e
CHECK_OUT="$(cd "$FIRST_WT" && bash -c "$CHECK" 2>&1)"; CHECK_EXIT=$?
set -e
{ echo "task=$TASK run=$RUN worktree=$FIRST_WT"; echo "exit=$CHECK_EXIT"; echo "--- output ---"; echo "$CHECK_OUT"; } > "$BASELINE_FILE"
echo "BASELINE: exit=$CHECK_EXIT -> $BASELINE_FILE"
