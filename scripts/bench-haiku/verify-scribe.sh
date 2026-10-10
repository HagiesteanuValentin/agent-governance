#!/usr/bin/env bash
# Usage: verify-scribe.sh <root> [--only CELL] — see scripts/bench-haiku/README.md
set -uo pipefail
ARMS="${ARMS:-s55-low s55-medium h55-medium h55-high}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:?Usage: verify-scribe.sh <root> [--only CELL]}"; shift
ONLY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --only) ONLY="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
ARM_RE="$(sed 's/ /|/g' <<<"$ARMS")"
n=0; pass=0
for CELL in "$ROOT"/scribe/*/; do
  CELL="${CELL%/}"; NAME="$(basename "$CELL")"
  [[ -d "$CELL/.git" ]] || continue
  [[ -n "$ONLY" && "$NAME" != "$ONLY" ]] && continue
  TASK="$(sed -E "s/-($ARM_RE)-[0-9]+$//" <<<"$NAME")"
  [[ "$TASK" == "$NAME" ]] && { echo "SKIP $NAME (arm not in ARMS)"; continue; }
  IDX="$(mktemp)"; STAT="$(mktemp)"
  cp "$CELL/.git/index" "$IDX"
  GIT_INDEX_FILE="$IDX" git -C "$CELL" add -A
  GIT_INDEX_FILE="$IDX" git -C "$CELL" diff --cached base > "$CELL/diff.patch"
  GIT_INDEX_FILE="$IDX" git -C "$CELL" diff --cached --stat base > "$STAT"
  echo "== $NAME ($TASK)"; cat "$STAT"
  python3 "$HERE/checks.py" "$TASK" "$CELL" --json "$CELL/verify.json" --stat-file "$STAT" && pass=$((pass+1))
  rm -f "$IDX" "$STAT"; n=$((n+1))
done
echo "verified=$n pass=$pass"
(( n > 0 ))
