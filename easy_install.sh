#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
DRY_RUN=0
ASSUME_YES=0
RESTORE_DIR=""

usage() {
  echo "Usage: bash easy_install.sh [--dry-run] [--yes] [--restore <backup-dir>]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --restore) shift; RESTORE_DIR="${1:-}"; [ -n "$RESTORE_DIR" ] || { echo "ERROR: --restore needs a directory"; exit 1; } ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1"; usage; exit 1 ;;
  esac
  shift
done

# 🔴 rm -rf never runs with an empty or missing HOME — PATTERNS «easy_install.sh»
safe_rm() {
  [ -n "${HOME:-}" ] && [ -d "$HOME" ] || { echo "ERROR: HOME is empty or not a directory; refusing to delete"; exit 1; }
  case "$1" in
    "$CLAUDE_DIR"/*) rm -rf "$1" ;;
    *) echo "ERROR: refusing to delete outside $CLAUDE_DIR: $1"; exit 1 ;;
  esac
}

case "${OSTYPE:-}" in
  linux*) : ;;
  darwin*) echo "WARN: macOS: \`tac\` missing -> main-model.sh fail-open (\`brew install coreutils\`)" ;;
  msys*|cygwin*) echo "WARN: Windows via Git Bash, untested" ;;
  *) echo "ERROR: unsupported OS: ${OSTYPE:-unknown}"; exit 1 ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required (used by the metrics analyzer and by this installer's checks)"
  exit 1
fi

INSTALLED_FILES="settings.json CLAUDE.md orchestrare.md orchestrare-v17.md"
INSTALLED_DIRS="agents hooks commands skills"

if [ -n "$RESTORE_DIR" ]; then
  [ -d "$RESTORE_DIR" ] || { echo "ERROR: backup directory not found: $RESTORE_DIR"; exit 1; }
  for d in $INSTALLED_DIRS; do safe_rm "$CLAUDE_DIR/$d"; done
  for f in $INSTALLED_FILES; do safe_rm "$CLAUDE_DIR/$f"; done
  mkdir -p "$CLAUDE_DIR"
  for d in $INSTALLED_DIRS; do
    if [ -d "$RESTORE_DIR/$d" ]; then cp -R "$RESTORE_DIR/$d" "$CLAUDE_DIR/$d"; fi
  done
  for f in $RESTORE_DIR/*.json $RESTORE_DIR/*.md; do
    if [ -f "$f" ]; then cp "$f" "$CLAUDE_DIR/"; fi
  done
  echo "Restored $CLAUDE_DIR from $RESTORE_DIR"
  exit 0
fi

for p in agents hooks commands templates hooks/settings.example.json templates/CLAUDE.global.md templates/orchestrare.md templates/orchestrare-v17.md; do
  [ -e "$REPO_DIR/$p" ] || { echo "ERROR: not a clone of this repo: missing $p"; exit 1; }
done

N_AGENTS=$(ls "$REPO_DIR"/agents/*.md 2>/dev/null | wc -l)
N_COMMANDS=$(ls "$REPO_DIR"/commands/*.md 2>/dev/null | wc -l)
N_HOOKS=$(ls "$REPO_DIR"/hooks/*.sh 2>/dev/null | grep -vc '/test-[^/]*\.sh$' || true)

BACKUP_DIR="$HOME/.claude-backup-$(date +%Y%m%d-%H%M%S)"
n=2
while [ -e "$BACKUP_DIR" ]; do
  BACKUP_DIR="$HOME/.claude-backup-$(date +%Y%m%d-%H%M%S)-$n"
  n=$((n + 1))
done

echo "Repo:      $REPO_DIR"
echo "Target:    $CLAUDE_DIR"
echo "Backup:    $BACKUP_DIR"
echo "Plan: replace agents/ hooks/ commands/ skills/ settings.json CLAUDE.md orchestrare*.md"
echo "      copy $N_AGENTS agents, $N_HOOKS hooks (no test-*.sh), $N_COMMANDS commands"
echo "      memory/ projects/ plans/ history* are left untouched"

if [ "$DRY_RUN" = "1" ]; then
  echo "Dry run: nothing written."
  exit 0
fi

if [ "$ASSUME_YES" != "1" ]; then
  printf 'This replaces your ~/.claude agents/hooks/commands/skills/settings. Backup at %s. Continue? [y/N] ' "$BACKUP_DIR"
  read -r reply
  case "$reply" in y|Y|yes|YES) : ;; *) echo "Aborted."; exit 1 ;; esac
fi

mkdir -p "$BACKUP_DIR"
N_SOURCES=0
for d in $INSTALLED_DIRS; do
  if [ -d "$CLAUDE_DIR/$d" ]; then N_SOURCES=$((N_SOURCES + 1)); fi
done
for f in settings.json CLAUDE.md; do
  if [ -f "$CLAUDE_DIR/$f" ]; then N_SOURCES=$((N_SOURCES + 1)); fi
done
for f in "$CLAUDE_DIR"/orchestrare*.md; do
  if [ -f "$f" ]; then N_SOURCES=$((N_SOURCES + 1)); fi
done
for d in $INSTALLED_DIRS; do
  if [ -d "$CLAUDE_DIR/$d" ]; then cp -R "$CLAUDE_DIR/$d" "$BACKUP_DIR/$d"; fi
done
for f in settings.json CLAUDE.md; do
  if [ -f "$CLAUDE_DIR/$f" ]; then cp "$CLAUDE_DIR/$f" "$BACKUP_DIR/$f"; fi
done
for f in "$CLAUDE_DIR"/orchestrare*.md; do
  if [ -f "$f" ]; then cp "$f" "$BACKUP_DIR/"; fi
done
N_BACKED_UP=$(ls -A "$BACKUP_DIR" | wc -l)
if [ "$N_BACKED_UP" -lt "$N_SOURCES" ]; then
  echo "ERROR: backup incomplete ($N_BACKED_UP of $N_SOURCES entries in $BACKUP_DIR); aborting"
  exit 1
fi
echo "Backup written: $BACKUP_DIR ($N_BACKED_UP of $N_SOURCES entries)"

for d in $INSTALLED_DIRS; do safe_rm "$CLAUDE_DIR/$d"; done
mkdir -p "$CLAUDE_DIR/agents" "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/commands" "$CLAUDE_DIR/skills"

cp "$REPO_DIR"/agents/*.md "$CLAUDE_DIR/agents/"
cp "$REPO_DIR"/commands/*.md "$CLAUDE_DIR/commands/"
for h in "$REPO_DIR"/hooks/*.sh; do
  case "$(basename "$h")" in test-*) continue ;; esac
  cp "$h" "$CLAUDE_DIR/hooks/"
done
chmod +x "$CLAUDE_DIR"/hooks/*.sh

# 🔴 the installed copy of session-metrics.sh must point at this clone — PATTERNS «easy_install.sh»
SM="$CLAUDE_DIR/hooks/session-metrics.sh"
if grep -q '^REPO_DIR=' "$SM"; then
  sed -i "s|^REPO_DIR=.*|REPO_DIR=\"\${AGENT_GOVERNANCE_DIR:-$REPO_DIR}\"|" "$SM"
else
  echo "WARN: REPO_DIR line not found in session-metrics.sh; TRENDS.md will not be generated"
fi

cp "$REPO_DIR/templates/CLAUDE.global.md" "$CLAUDE_DIR/CLAUDE.md"
cp "$REPO_DIR/templates/orchestrare.md" "$CLAUDE_DIR/orchestrare.md"
cp "$REPO_DIR/templates/orchestrare-v17.md" "$CLAUDE_DIR/orchestrare-v17.md"
cp "$REPO_DIR/hooks/settings.example.json" "$CLAUDE_DIR/settings.json"

python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$CLAUDE_DIR/settings.json" \
  || { echo "ERROR: installed settings.json is not valid JSON"; exit 1; }
echo "OK: settings.json is valid JSON"

echo "Installed: $(ls "$CLAUDE_DIR"/agents/*.md | wc -l)/$N_AGENTS agents, $(ls "$CLAUDE_DIR"/hooks/*.sh | wc -l)/$N_HOOKS hooks, $(ls "$CLAUDE_DIR"/commands/*.md | wc -l)/$N_COMMANDS commands"

ORCH_SIZE=$(wc -c < "$CLAUDE_DIR/orchestrare.md" | tr -d ' ')
if [ "$ORCH_SIZE" -gt 10240 ]; then
  echo "WARN: orchestrare.md is $ORCH_SIZE bytes (> 10240): SessionStart truncates the injected block"
else
  echo "OK: orchestrare.md $ORCH_SIZE bytes (<= 10240)"
fi

echo "Backup: $BACKUP_DIR. Next: /exit if Claude Code is open, then \`cd <project> && claude\` and run \`/onboarding\`."
