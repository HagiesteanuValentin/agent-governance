#!/usr/bin/env bash
# Usage: verify.sh <T1..T3> <cell-dir|cell-name> — see scripts/bench-scripter/README.md
set -uo pipefail
BENCH_ROOT="${BENCH_ROOT:-${HOME}/workflow/experimente/bench-scripter}"
RUN_TIMEOUT="${RUN_TIMEOUT:-600}"
TASK="${1:?task T1..T3}"; CELL="${2:?cell}"
[[ -d "$CELL" ]] || CELL="$BENCH_ROOT/$TASK/$CELL"
WT="$(cd "$CELL" && pwd)" || exit 2
NAME="$(basename "$WT")"
PORT="$(sed -n 's/^PORT=//p' "$WT/CELL.env")"
[[ -n "$PORT" ]] || { echo "No PORT in $WT/CELL.env" >&2; exit 2; }
RUNDIR="$(dirname "$WT")/.verify-$NAME"
OUT="$(dirname "$WT")/$NAME.json"
rm -rf "$RUNDIR"; mkdir -p "$RUNDIR"

case "$TASK" in
  T1) CMD=(node scripts/verify-studii-caz.mjs --url "http://localhost:$PORT") ;;
  T2) CMD=(node scripts/verifica-produs.mjs --port "$PORT") ;;
  T3) CMD=(node scripts/verifica-index-miscare.mjs --url "http://localhost:$PORT/") ;;
  *) echo "Unknown task: $TASK" >&2; exit 2 ;;
esac

free_port() { fuser -k -TERM "$PORT/tcp" >/dev/null 2>&1; sleep 1; fuser -k -KILL "$PORT/tcp" >/dev/null 2>&1; true; }

free_port
(cd "$WT" && exec setsid npm run dev -- --port "$PORT" --strictPort >"$RUNDIR/dev.log" 2>&1) &
DEV_PID=$!
stop_dev() { kill -- -"$DEV_PID" 2>/dev/null; free_port; }
trap stop_dev EXIT
for _ in $(seq 1 60); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/")" == "200" ]] && break
  sleep 1
done
echo "dev :$PORT -> $(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/")"

for i in 1 2; do
  mkdir -p "$RUNDIR/run$i"
  START=$(date +%s)
  (cd "$WT" && timeout "$RUN_TIMEOUT" "${CMD[@]}" >"$RUNDIR/run$i/stdout.out" 2>"$RUNDIR/run$i.stderr")
  echo $? > "$RUNDIR/run$i.exit"
  echo "run $i: exit $(cat "$RUNDIR/run$i.exit") in $(( $(date +%s) - START ))s"
  git -C "$WT" status --porcelain --untracked-files=all | cut -c4- | grep -E '\.(json|md)$' | while read -r f; do
    mkdir -p "$RUNDIR/run$i/$(dirname "$f")"; cp "$WT/$f" "$RUNDIR/run$i/$f"
  done
done

stop_dev; trap - EXIT
python3 "$(dirname "$0")/checks.py" "$TASK" "$WT" "$RUNDIR" "$OUT"
