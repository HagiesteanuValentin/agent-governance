#!/usr/bin/env bash
# Usage: verify-B.sh <worktree> [--base REV] [--no-build] — see scripts/SCRIPTS.md
exec "$(dirname "$0")/verify.sh" B "$@"
