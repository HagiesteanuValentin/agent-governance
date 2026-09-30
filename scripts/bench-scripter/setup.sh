#!/usr/bin/env bash
# Usage: setup.sh <T1..T3> <run|from-to> [--ref] — see scripts/bench-scripter/README.md
set -euo pipefail
PROIECTE="${PROIECTE:-${HOME}/workflow/proiecte}"
BENCH_ROOT="${BENCH_ROOT:-${HOME}/workflow/experimente/bench-scripter}"
DEFAULT_CELLS="cell-scripter-o55-low cell-scripter-s55-medium"
read -r -a CELLS <<<"${CELLS:-$DEFAULT_CELLS}"
HERE="$(cd "$(dirname "$0")" && pwd)"

TASK="${1:-}"; RUNS="${2:-}"; REF_MODE="false"
[[ -z "$TASK" || -z "$RUNS" ]] && { echo "Usage: setup.sh <T1..T3> <run|from-to> [--ref]" >&2; exit 1; }
[[ "${3:-}" == "--ref" ]] && REF_MODE="true"
[[ "$RUNS" =~ ^([0-9]+)(-([0-9]+))?$ ]] || { echo "Bad run: $RUNS (N or N-M)" >&2; exit 1; }
RUN_FROM="${BASH_REMATCH[1]}"; RUN_TO="${BASH_REMATCH[3]:-$RUN_FROM}"

case "$TASK" in
  T1) REPO=promo-site; BASE=c41e0f7; EXTRA="" ;;
  T2) REPO=blueprint_prezentare; BASE=e3e41cb; EXTRA="1fbd216:docs/polish/produs.dosar.md" ;;
  T3) REPO=blueprint_prezentare; BASE=e3e41cb; EXTRA="33be8a8:docs/polish/index.dosar.md" ;;
  *) echo "Unknown task: $TASK" >&2; exit 1 ;;
esac
MAMA="$PROIECTE/$REPO"

next_port() {
  local max=4399 p
  for p in $(cat "$BENCH_ROOT"/T*/*/CELL.env 2>/dev/null | sed -n 's/^PORT=//p'); do
    (( p > max )) && max=$p
  done
  echo $((max + 1))
}

make_cell() {
  local WT="$BENCH_ROOT/$TASK/$1" IS_REF="$2"
  if [[ -d "$WT/.git" ]]; then
    echo "OK (already exists) $WT ($(cat "$WT/CELL.env"))"
    return
  fi
  mkdir -p "$WT"
  git -C "$MAMA" archive "$BASE" | tar -x -C "$WT"
  if [[ -n "$EXTRA" ]]; then
    git -C "$MAMA" archive "${EXTRA%%:*}" -- "${EXTRA#*:}" | tar -x -C "$WT"
  fi
  git -C "$WT" init -q
  printf 'node_modules\nCELL.env\n' >> "$WT/.git/info/exclude"
  git -C "$WT" add -A
  git -C "$WT" -c user.name=bench -c user.email=bench@local commit -qm base
  echo "PORT=$(next_port)" > "$WT/CELL.env"
  cp -r --reflink=auto "$MAMA/node_modules" "$WT/node_modules"
  if [[ "$TASK" == "T1" ]]; then
    PW_NPX="$(dirname "$(grep -l '"version": "1.63.0"' "$HOME"/.npm/_npx/*/node_modules/playwright/package.json | head -1)")"
    [[ "$PW_NPX" == */playwright ]] || { echo "playwright 1.63.0 missing in ~/.npm/_npx" >&2; exit 1; }
    cp -r --reflink=auto "$PW_NPX" "$PW_NPX-core" "$WT/node_modules/"
  fi
  echo "CREATED $WT (base = $REPO $BASE${EXTRA:+ + $EXTRA}, $(cat "$WT/CELL.env"))"
  if [[ "$IS_REF" == "true" ]]; then
    case "$TASK" in
      T1) git -C "$MAMA" archive 3da413b -- scripts/verify-studii-caz.mjs | tar -x -C "$WT" ;;
      T2) git -C "$MAMA" archive 1fbd216 -- scripts/verifica-produs.mjs docs/polish/produs.masuratori.md | tar -x -C "$WT" ;;
      T3) cp "$HERE/ref/T3-verifica-index-miscare.mjs" "$WT/scripts/verifica-index-miscare.mjs"
          cp "$HERE/ref/T3-index.masuratori.md" "$WT/docs/polish/index.masuratori.md" ;;
    esac
    echo "OVERLAID ref files (uncommitted)"
  fi
}

if [[ "$REF_MODE" == "true" ]]; then
  make_cell "ref-$RUN_FROM" true
  exit 0
fi
for RUN in $(seq "$RUN_FROM" "$RUN_TO"); do
  for CELL in "${CELLS[@]}"; do
    make_cell "${CELL}-${RUN}" false
  done
done
make_cell ref-1 true
make_cell base-1 false
