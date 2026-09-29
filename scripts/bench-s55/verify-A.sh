#!/usr/bin/env bash
# Usage: verify-A.sh <worktree> [--base REV] [--no-build] — see scripts/SCRIPTS.md
exec "$(dirname "$0")/verify.sh" A "$@"
