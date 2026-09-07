#!/bin/bash
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd -P)"
TARGET=""
DRY_RUN=0
NO_GIT=0

usage() {
  echo "Usage: bash scripts/export-public.sh <target> [--dry-run] [--no-git]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --no-git) NO_GIT=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "ERROR: unknown option: $1"; usage; exit 1 ;;
    *) [ -z "$TARGET" ] || { echo "ERROR: only one target allowed"; exit 1; }; TARGET="$1" ;;
  esac
  shift
done

[ -n "$TARGET" ] || { echo "ERROR: target directory is required"; usage; exit 1; }

# ---------- file list ----------

WHITELIST=(
  "agents/*.md"
  "hooks/*.sh"
  "hooks/settings.example.json"
  "commands/*.md"
  "templates/*.md"
  "docs/PATTERNS.md"
  "docs/RECIPES.md"
  "docs/experiments.md"
  "docs/postmortem-2026-09-01-fable-5-1.md"
  "metrics/baseline-2026-08.md"
  "tools/session_metrics.py"
  "tools/pricing.json"
  "tools/versions.json"
  "tools/tests/**"
  "README.md"
  "HOW_TO_USE.md"
  "LICENSE"
  ".gitignore"
  "easy_install.sh"
  "scripts/SCRIPTS.md"
  "scripts/fixtures/pricing-cache-5m/**"
)

# sources scanned for scripts/ and tools/ mentions
CITE_SOURCES=(README.md HOW_TO_USE.md docs/PATTERNS.md docs/RECIPES.md hooks commands agents easy_install.sh templates)

collect_files() {
  local p f
  for p in "${WHITELIST[@]}"; do
    case "$p" in
      */\*\*)
        find "$SRC/${p%/**}" -type f -print 2>/dev/null | sed "s|^$SRC/||"
        ;;
      *)
        for f in $SRC/$p; do
          [ -f "$f" ] && echo "${f#$SRC/}"
        done
        ;;
    esac
  done
  ( cd "$SRC" && grep -rhoE '(scripts|tools)/[a-zA-Z0-9_.-]+' "${CITE_SOURCES[@]}" 2>/dev/null || true ) \
    | sort -u | while read -r f; do
        [ -f "$SRC/$f" ] && echo "$f"
      done
}

FILE_LIST="$(collect_files | grep -v '__pycache__' | sort -u)"
FILE_COUNT="$(printf '%s\n' "$FILE_LIST" | grep -c . || true)"

# top-level scripts/ and tools/ files that are NOT exported -> their SCRIPTS.md rows go away
NOT_EXPORTED="$( { find "$SRC/scripts" "$SRC/tools" -maxdepth 1 -type f -print | sed "s|^$SRC/||"; } \
  | grep -v '__pycache__' | sort -u | comm -23 - <(printf '%s\n' "$FILE_LIST") )"

echo "Source: $SRC"
echo "Target: $TARGET"
echo "Files to export: $FILE_COUNT"
printf '%s\n' "$FILE_LIST" | sed 's/^/  /'
echo "SCRIPTS.md rows dropped for:"
printf '%s\n' "$NOT_EXPORTED" | sed 's/^/  /'

if [ "$DRY_RUN" -eq 1 ]; then
  echo "DRY RUN: nothing written"
  exit 0
fi

# ---------- target guard ----------

mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd -P)"
[ "$TARGET" != "$SRC" ] || { echo "ERROR: target is the source repo"; exit 1; }

if [ -n "$(ls -A "$TARGET")" ]; then
  if [ ! -d "$TARGET/.git" ]; then
    echo "ERROR: target is not empty and has no .git of its own: $TARGET"
    exit 1
  fi
  find "$TARGET" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
fi

# ---------- copy ----------

while read -r f; do
  [ -n "$f" ] || continue
  mkdir -p "$TARGET/$(dirname "$f")"
  cp -p "$SRC/$f" "$TARGET/$f"
done <<< "$FILE_LIST"

if [ -f "$TARGET/scripts/SCRIPTS.md" ] && [ -n "$NOT_EXPORTED" ]; then
  GREP_ARGS=()
  while read -r n; do
    [ -n "$n" ] || continue
    GREP_ARGS+=(-e "$n")
  done <<< "$NOT_EXPORTED"
  grep -vF "${GREP_ARGS[@]}" "$TARGET/scripts/SCRIPTS.md" > "$TARGET/scripts/SCRIPTS.md.tmp"
  mv "$TARGET/scripts/SCRIPTS.md.tmp" "$TARGET/scripts/SCRIPTS.md"
fi

echo "Copied $FILE_COUNT files"

# ---------- checks ----------

FAILED=0
check_fail() { echo "CHECK FAILED: $1"; FAILED=1; }

cd "$TARGET"

N="$( { grep -rnE "/home/vali|-home-vali-|Vali\b" . --exclude-dir=.git || true; } | wc -l)"
echo "check private paths/name: $N hit(s)"
[ "$N" -eq 0 ] || { { grep -rnE "/home/vali|-home-vali-|Vali\b" . --exclude-dir=.git || true; } | head -20; check_fail "private path or author name present"; }

N="$( { grep -rlE "[ăâîșț]" . --exclude-dir=.git --exclude='*.py' || true; } | wc -l)"
echo "check diacritics outside *.py: $N file(s)"
[ "$N" -eq 0 ] || { grep -rlE "[ăâîșț]" . --exclude-dir=.git --exclude='*.py' || true; check_fail "Romanian diacritics outside *.py"; }

if TEST_OUT="$(python3 tools/tests/test_v17.py 2>&1)"; then
  echo "check tests: $(printf '%s\n' "$TEST_OUT" | tail -1)"
  printf '%s\n' "$TEST_OUT" | grep -qE '0 failed' || check_fail "test_v17.py did not report 0 failed"
else
  printf '%s\n' "$TEST_OUT" | tail -20
  check_fail "test_v17.py exited non-zero"
fi

BAD_LINKS=0
for doc in README.md HOW_TO_USE.md; do
  [ -f "$doc" ] || continue
  while read -r link; do
    [ -n "$link" ] || continue
    [ -e "${link%%#*}" ] || { echo "  broken link in $doc: $link"; BAD_LINKS=$((BAD_LINKS+1)); }
  done < <( { grep -oE '\]\(([^)h#][^)]*)\)' "$doc" || true; } | sed -E 's/^\]\(//; s/\)$//')
done
while read -r ref; do
  [ -n "$ref" ] || continue
  [ -e "$ref" ] || { echo "  missing path cited in scripts/SCRIPTS.md: $ref"; BAD_LINKS=$((BAD_LINKS+1)); }
done < <( { grep -ohE '(scripts|tools)/[a-zA-Z0-9_./-]+' scripts/SCRIPTS.md 2>/dev/null || true; } | sed 's/[.]$//' | sort -u )
echo "check relative links + SCRIPTS.md paths: $BAD_LINKS broken"
[ "$BAD_LINKS" -eq 0 ] || check_fail "broken relative links"

SH_BAD=0
while read -r s; do
  bash -n "$s" 2>&1 || { echo "  syntax error: $s"; SH_BAD=$((SH_BAD+1)); }
done < <(find . -name '*.sh' -not -path './.git/*')
echo "check bash -n: $SH_BAD error(s)"
[ "$SH_BAD" -eq 0 ] || check_fail "shell syntax errors"

FAKE_HOME="$(mktemp -d)"
if HOME="$FAKE_HOME" bash easy_install.sh --dry-run >/dev/null 2>&1; then
  echo "check easy_install.sh --dry-run: exit 0"
else
  check_fail "easy_install.sh --dry-run failed"
fi
rm -rf "$FAKE_HOME"

if [ "$FAILED" -ne 0 ]; then
  echo "RESULT: checks failed; files left in $TARGET for inspection"
  exit 1
fi
echo "RESULT: all checks passed"

# ---------- git ----------

if [ "$NO_GIT" -eq 1 ]; then
  echo "Skipping git (--no-git)"
  exit 0
fi

[ -d .git ] || git init -b main -q
git add -A
if git diff --cached --quiet; then
  echo "nothing to commit, working tree clean"
else
  git -c user.name=claude_code_king -c user.email=claude_code_king@users.noreply.github.com \
    commit -q -m "agent-governance v1.8 — public release"
  echo "committed"
fi
git log --oneline | wc -l | sed 's/^/commits: /'
