#!/usr/bin/env bash
# Usage: cleanup.sh [--dry-run] — see scripts/SCRIPTS.md
set -uo pipefail
MAMA="${MAMA:-${PROJECT:-${HOME}/workflow/proiecte/promo-site}}"
PREFIX="${PREFIX:-exp/bench-s55-}"
DRY="false"; [[ "${1:-}" == "--dry-run" ]] && DRY="true"
FAILED=0
while read -r WT BR; do
  [[ -z "$WT" ]] && continue
  if [[ "$DRY" == "true" ]]; then echo "WOULD DELETE worktree $WT"; continue; fi
  git -C "$MAMA" worktree remove --force "$WT" && echo "DELETED worktree $WT" || FAILED=1
done < <(git -C "$MAMA" worktree list --porcelain | awk -v p="refs/heads/$PREFIX" '/^worktree /{w=$2} /^branch /{if(index($2,p)==1)print w, $2}')
for BR in $(git -C "$MAMA" for-each-ref --format='%(refname:short)' "refs/heads/${PREFIX}*" "refs/heads/${PREFIX}*/**"); do
  if [[ "$DRY" == "true" ]]; then echo "WOULD DELETE branch $BR"; continue; fi
  git -C "$MAMA" branch -D "$BR" >/dev/null && echo "DELETED branch $BR" || FAILED=1
done
[[ "$DRY" == "true" ]] || git -C "$MAMA" worktree prune
exit $FAILED
