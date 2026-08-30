#!/bin/sh
# 🔴 SessionStart, $1=rules|handoff (one output >10KB → persisted, 2KB preview) — DECIZII «v1.5.2 — split SessionStart»
d="${CLAUDE_PROJECT_DIR:-$PWD}"
o="$HOME/.claude/orchestrare.md"
if [ "${1:-rules}" != "handoff" ] && [ -f "$o" ]; then
  echo "=== ORCHESTRATION (injected by SessionStart; main session only) ==="
  cat "$o"
  echo
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
