#!/usr/bin/env bash
# Usage: verify-C.sh <worktree> [--base REV] [--no-build] — see scripts/SCRIPTS.md
exec "$(dirname "$0")/verify.sh" C "$@"
