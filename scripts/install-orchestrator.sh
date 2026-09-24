#!/bin/bash
# 🔴 manually run by the user (the auto mode classifier blocks agents on ~/.claude) — docs/DECIZII.md «Mod autonom (04.09.2026)»
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd); LIVE="${LIVE:-$HOME/.claude}"; SRC="$REPO/docs/dosar/live-ro"
n=$(ls "$SRC" 2>/dev/null | wc -l)
if [ "$n" -lt 3 ]; then echo "ERROR: $SRC missing or has $n files (need orchestrator.md, orchestrare.md, orchestrare-v17.md)" >&2; exit 2; fi
PAIRS=("$SRC/orchestrator.md:agents/orchestrator.md" "$SRC/orchestrare.md:orchestrare.md" "$SRC/orchestrare-v17.md:orchestrare-v17.md" "$REPO/hooks/context-agent.sh:hooks/context-agent.sh")
BK="$LIVE/.backup-orchestrator-$(date +%Y%m%d-%H%M%S)"
for p in "${PAIRS[@]}"; do d="$LIVE/${p#*:}"; [ -f "$d" ] && mkdir -p "$BK/$(dirname "${p#*:}")" && cp -p "$d" "$BK/${p#*:}"; done
[ -d "$BK" ] && echo "backup: $BK"
for p in "${PAIRS[@]}"; do d="$LIVE/${p#*:}"; mkdir -p "$(dirname "$d")"; cp "${p%%:*}" "$d"; done
chmod +x "$LIVE/hooks/context-agent.sh"
fail=0
a=$(grep -c '^name: orchestrator' "$LIVE/agents/orchestrator.md" || true); echo "name: orchestrator = $a (expect 1)"; [ "$a" = 1 ] || fail=1
b=$(wc -c < "$LIVE/orchestrare.md"); echo "orchestrare.md bytes = $b (expect <=10000)"; [ "$b" -le 10000 ] || fail=1
c=$(grep -c orchestrator "$LIVE/orchestrare.md" || true); echo "orchestrator in orchestrare.md = $c (expect >=3)"; [ "$c" -ge 3 ] || fail=1
T=$(mktemp -d); cp "$LIVE/hooks/context-agent.sh" "$REPO/hooks/test-context-main.sh" "$T/"
if bash "$T/test-context-main.sh" > "$T/out" 2>&1; then echo "test-context-main on live hook: $(tail -1 "$T/out")"; else echo "test-context-main FAILED:"; tail -5 "$T/out"; fail=1; fi
rm -rf "$T"
[ "$fail" = 0 ] && echo "OK" || { echo "VERIFY FAILED" >&2; exit 1; }
