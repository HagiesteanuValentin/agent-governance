#!/usr/bin/env bash
# Re-analyze the records in metrics-local/ against their session transcript.
set -uo pipefail

DRY_RUN=0
LIMIT=0
DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --limit) LIMIT="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] [--limit N] DIR"
      exit 0
      ;;
    *) DIR="$1"; shift ;;
  esac
done

if [ -z "$DIR" ]; then
  echo "Usage: $0 [--dry-run] [--limit N] DIR" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL="$SCRIPT_DIR/tools/session_metrics.py"
PROJECTS_DIR="$HOME/.claude/projects"

total=0
reanalyzed=0
no_transcript=0
errors=0
processed=0

for record in "$DIR"/*.json; do
  [ -e "$record" ] || continue
  base="$(basename "$record")"
  case "$base" in
    pending-rating.json|cells*.json) continue ;;
  esac

  total=$((total + 1))

  if [ "$LIMIT" -gt 0 ] && [ "$processed" -ge "$LIMIT" ]; then
    continue
  fi

  session="$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
row = d[0] if isinstance(d, list) else d
print(row.get('session', ''))
" "$record" 2>/dev/null)"

  if [ -z "$session" ]; then
    echo "NO SESSION: $base"
    no_transcript=$((no_transcript + 1))
    continue
  fi

  jsonl="$(find "$PROJECTS_DIR" -maxdepth 2 -name "${session}.jsonl" -print -quit 2>/dev/null)"

  if [ -z "$jsonl" ]; then
    echo "NO TRANSCRIPT: $base (session=$session)"
    no_transcript=$((no_transcript + 1))
    continue
  fi

  processed=$((processed + 1))

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "$base → $jsonl"
    continue
  fi

  if python3 "$TOOL" "$jsonl" --json --md --out-dir "$DIR" >/tmp/reanalyze-metrics.$$.log 2>&1; then
    reanalyzed=$((reanalyzed + 1))
  else
    errors=$((errors + 1))
    echo "ERROR: $base (session=$session)"
    tail -n 5 /tmp/reanalyze-metrics.$$.log
  fi
  rm -f /tmp/reanalyze-metrics.$$.log
done

echo "---"
echo "records: $total"
echo "re-analyzed: $reanalyzed"
echo "no transcript: $no_transcript"
echo "errors: $errors"

if [ "$errors" -gt 0 ]; then
  exit 1
fi
exit 0
