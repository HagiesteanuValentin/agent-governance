#!/bin/sh
# SessionStart: inject any HANDOFF*.md from the current project root.
# In a worktree this also picks up its own mini-handoff (HANDOFF-<name>.md); on the main
# branch, after a merge, it picks up mini-handoffs that are not consolidated yet.
d="${CLAUDE_PROJECT_DIR:-$PWD}"
for f in "$d"/HANDOFF.md "$d"/HANDOFF-*.md; do
  [ -f "$f" ] || continue
  echo "=== $(basename "$f") (auto-injected at session start; it is a snapshot, not history) ==="
  cat "$f"
done
exit 0
