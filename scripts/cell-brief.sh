#!/usr/bin/env bash
# Usage: cell-brief.sh <task> <run> <template> — see scripts/SCRIPTS.md
set -euo pipefail

EXPERIMENTE="${HOME}/workflow/experimente"
CELLS=(cell-opus-low cell-opus-medium cell-sonnet-medium cell-sonnet-low)

TASK="${1:-}"
RUN="${2:-}"
TEMPLATE="${3:-}"

if [[ -z "$TASK" || -z "$RUN" || -z "$TEMPLATE" ]]; then
  echo "Usage: cell-brief.sh <task> <run> <template>" >&2
  exit 1
fi

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Template not found: $TEMPLATE" >&2
  exit 1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUTDIR="$REPO/metrics-local/experiments/$TASK/input"
BASE="$(basename "$TEMPLATE")"
BASE="${BASE%.md}"
BASE="${BASE%.template}"

mkdir -p "$OUTDIR"

for CELL in "${CELLS[@]}"; do
  WT="$EXPERIMENTE/$TASK/${CELL}-${RUN}"
  DEST="$OUTDIR/${BASE}.${CELL}-${RUN}.md"
  sed "s|__ROOT__|$WT|g" "$TEMPLATE" > "$DEST"
  echo "WROTE $DEST (root $WT)"
done
