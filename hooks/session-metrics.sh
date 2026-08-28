#!/bin/bash
# SessionEnd: run the analyzer on the transcript of the session that just ended.
# Runs outside the model's context -> zero tokens.
# REPO_DIR must point at your clone of this repository.
REPO_DIR="${AGENT_GOVERNANCE_DIR:-$HOME/agent-governance}"
OUT_DIR="$REPO_DIR/metrics-local"
TOOL="$REPO_DIR/tools/session_metrics.py"
INPUT=$(cat)
TP=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("transcript_path",""))' 2>/dev/null)
[ -n "$TP" ] && [ -f "$TP" ] && [ -f "$TOOL" ] || exit 0
mkdir -p "$OUT_DIR"
python3 "$TOOL" "$TP" --json --md --out-dir "$OUT_DIR" --rating-file "$OUT_DIR/pending-rating.json" 2>/dev/null
python3 "$TOOL" --trends "$OUT_DIR" 2>/dev/null
exit 0
