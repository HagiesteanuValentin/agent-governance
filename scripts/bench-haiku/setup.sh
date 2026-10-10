#!/usr/bin/env bash
# Usage: setup.sh <tasks.json> <root> [--force] [--dry-run] [--only TASK] [--runs N] — see scripts/bench-haiku/README.md
set -euo pipefail
ARMS_SCRIBE="${ARMS_SCRIBE:-s55-low h55-medium h55-high}"
ARMS_EXPLORER="${ARMS_EXPLORER:-s55-medium h55-medium h55-high}"
RUNS=3; FORCE=false; DRY=false; ONLY=""
TASKS="${1:?Usage: setup.sh <tasks.json> <root> [--force] [--dry-run] [--only TASK] [--runs N]}"
ROOT="${2:?root missing}"; shift 2
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --dry-run) DRY=true; shift ;;
    --only) ONLY="$2"; shift 2 ;;
    --runs) RUNS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ "$ROOT" = /* ]] || { echo "root must be absolute: $ROOT" >&2; exit 2; }
TASKS_DIR="$(cd "$(dirname "$TASKS")" && pwd)"
EXCLUDES="BRIEF.md report.md meta.json verify.json diff.patch"

mapfile -t ROWS < <(python3 -c '
import json, sys
for t in json.load(open(sys.argv[1]))["tasks"]:
    print("\t".join([t["id"], t["role"], t.get("repo", ""), t.get("commit", "")]))
' "$TASKS")

created=0; same=0; expected=0; errors=0
for ROW in "${ROWS[@]}"; do
  IFS=$'\t' read -r ID ROLE REPO COMMIT <<<"$ROW"
  [[ -n "$ONLY" && "$ID" != "$ONLY" ]] && continue
  BRIEF_SRC="$TASKS_DIR/$ID.md"; n_ph=""
  if [[ "$ROLE" == "scribe" ]]; then
    [[ -f "$BRIEF_SRC" && -n "$COMMIT" ]] || { echo "ERROR $ID: brief $BRIEF_SRC or commit missing" >&2; errors=$((errors+1)); continue; }
    n_ph=$( { grep -o '{{CELL_DIR}}' "$BRIEF_SRC" || true; } | wc -l)
    (( n_ph > 0 )) || { echo "ERROR $ID: no {{CELL_DIR}} in brief" >&2; errors=$((errors+1)); continue; }
  fi
  if [[ "$ROLE" == "scribe" ]]; then read -r -a ARM_LIST <<<"$ARMS_SCRIBE"; else read -r -a ARM_LIST <<<"$ARMS_EXPLORER"; fi
  for ARM in "${ARM_LIST[@]}"; do
    for N in $(seq 1 "$RUNS"); do
      expected=$((expected+1))
      CELL="$ROOT/$ROLE/$ID-$ARM-$N"
      if $DRY; then
        state="new"; [[ -e "$CELL" ]] && state="exists"
        ph=""; [[ -n "$n_ph" ]] && ph=", {{CELL_DIR}} x$n_ph"
        echo "DRY $ID $ARM $N -> $CELL ($state$ph)"
        continue
      fi
      if $FORCE && [[ -e "$CELL" ]]; then
        case "$(realpath "$CELL")" in "$(realpath "$ROOT")"/*) rm -rf "$CELL" ;; *) echo "SKIP outside root: $CELL" >&2; continue ;; esac
      fi
      if [[ "$ROLE" != "scribe" ]]; then
        if [[ -d "$CELL" ]]; then same=$((same+1)); else mkdir -p "$CELL"; created=$((created+1)); echo "CREATED $CELL"; fi
        continue
      fi
      BRIEF_TXT="$(grep -v '^<!-- sursa:' "$BRIEF_SRC" | sed "s|{{CELL_DIR}}|$CELL|g")"
      if [[ "$BRIEF_TXT" == *"{{"* ]]; then echo "ERROR $ID: placeholder left after replace" >&2; errors=$((errors+1)); continue; fi
      if [[ -d "$CELL/.git" ]] && git -C "$CELL" rev-parse -q --verify refs/tags/base >/dev/null \
         && [[ "$(cat "$CELL/BRIEF.md" 2>/dev/null)" == "$BRIEF_TXT" ]]; then
        same=$((same+1)); continue
      fi
      [[ -e "$CELL" ]] && { echo "ERROR $CELL exists but differs; use --force" >&2; errors=$((errors+1)); continue; }
      mkdir -p "$CELL"
      git -C "$REPO" archive "$COMMIT" | tar -x -C "$CELL"
      git -C "$CELL" init -q
      for X in $EXCLUDES; do echo "$X" >> "$CELL/.git/info/exclude"; done
      git -C "$CELL" add -A
      git -C "$CELL" -c user.name=bench -c user.email=bench@local commit -qm base
      git -C "$CELL" tag base
      printf '%s\n' "$BRIEF_TXT" > "$CELL/BRIEF.md"
      created=$((created+1))
      echo "CREATED $CELL (base = $(basename "$REPO") ${COMMIT:0:7}, {{CELL_DIR}} x$n_ph)"
    done
  done
done
echo "cells expected=$expected created=$created unchanged=$same errors=$errors"
(( errors == 0 ))
