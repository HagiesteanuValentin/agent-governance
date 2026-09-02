#!/bin/sh
# 🔴 SessionStart, $1=rules|handoff|v17 (one output >10KB → persisted, 2KB preview) — DECIZII «v1.5.2 — split SessionStart»
d="${CLAUDE_PROJECT_DIR:-$PWD}"
o="$HOME/.claude/orchestrare.md"
v="$HOME/.claude/orchestrare-v17.md"
# 🔴 resume must not snap effort back to medium — PATTERNS «Claude Code — limite verificate în docs (02.09.2026)»
in="$(cat 2>/dev/null)"
src=$(printf '%s' "$in" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('source') or '')
except Exception:
    print('')
" 2>/dev/null)
if [ "${1:-rules}" = "v17" ]; then
  if [ -f "$v" ]; then
    echo "=== ORCHESTRATION v1.7 (injected by SessionStart; main session only) ==="
    cat "$v"
    echo
  fi
  s="$HOME/.claude/settings.json"
  x=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['modelSettings']['claude-fable-5-1']['effortLevel'])" "$s" 2>/dev/null)
  echo "effort main (settings): ${x:-unknown}"
  exit 0
fi
if [ "${1:-rules}" != "handoff" ]; then
  eph="$(dirname "$0")/effort-phase.sh"
  # 🔴 fork/resume/compact keep effort; unknown source resets — PATTERNS «Claude Code — limite verificate în docs (02.09.2026)»
  if [ -f "$eph" ]; then
    case "$src" in
      resume|fork|compact) ;;
      *) sh "$eph" medium >/dev/null 2>&1 </dev/null ;;
    esac
  fi
  if [ -f "$o" ]; then
    echo "=== ORCHESTRATION (injected by SessionStart; main session only) ==="
    cat "$o"
    echo
  fi
  s="$HOME/.claude/settings.json"
  x=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['modelSettings']['claude-fable-5-1']['effortLevel'])" "$s" 2>/dev/null)
  echo "effort main (settings): ${x:-unknown}"
fi
# In a worktree this also picks up its own mini-handoff (HANDOFF-<name>.md); on the main
# branch, after a merge, it picks up mini-handoffs that are not consolidated yet.
if [ "${1:-handoff}" != "rules" ]; then
  for f in "$d"/HANDOFF.md "$d"/HANDOFF-*.md; do
    [ -f "$f" ] || continue
    echo "=== $(basename "$f") (auto-injected at session start; snapshot, not history) ==="
    cat "$f"
  done
fi
exit 0
