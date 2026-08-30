#!/bin/sh
# SessionStart: inject the orchestration rules, then any HANDOFF*.md from the project root.
# In a worktree this also picks up its own mini-handoff (HANDOFF-<name>.md); on the main
# branch, after a merge, it picks up mini-handoffs that are not consolidated yet.
d="${CLAUDE_PROJECT_DIR:-$PWD}"
o="$HOME/.claude/orchestrare.md"
if [ -f "$o" ]; then
  echo "=== ORCHESTRATION (injected by SessionStart; main session only) ==="
  cat "$o"
  echo
fi
for f in "$d"/HANDOFF.md "$d"/HANDOFF-*.md; do
  [ -f "$f" ] || continue
  echo "=== $(basename "$f") (auto-injected at session start; snapshot, not history) ==="
  cat "$f"
done
exit 0
