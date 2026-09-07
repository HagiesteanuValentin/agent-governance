#!/usr/bin/env bash
# Checks each PATTERNS «X» / RECIPES «X» pointer matches a heading in its doc.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail=0

while IFS=$'\t' read -r file doc section; do
  case "$section" in
    …|section|x|y|"<file>#<n>") continue ;;
  esac
  if [[ "$doc" == "PATTERNS" ]]; then
    target="docs/PATTERNS.md"
  else
    target="docs/RECIPES.md"
  fi
  if ! grep -qF "## $section" "$target" 2>/dev/null && ! grep -qF "### $section" "$target" 2>/dev/null; then
    echo "MISSING: $file -> $doc «$section»"
    fail=1
  fi
done < <(git ls-files | grep -v '^docs/arhiva/\|^docs/DECIZII\|^scripts/check-pointers.sh$' \
  | xargs grep -nHoE '(PATTERNS|RECIPES) «[^»]*»' 2>/dev/null \
  | sed -E 's/^([^:]+):[0-9]+:(PATTERNS|RECIPES) «([^»]*)»/\1\t\2\t\3/')

exit $fail
</content>
