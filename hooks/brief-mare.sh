#!/bin/bash
# PreToolUse on Agent (main session only): brief >7000 characters -> the "split it into
# phases" reminder from CLAUDE.md, Orchestration section. Does not block.
input=$(cat)
python3 - "$input" "$(dirname "$0")" <<'PY'
import json, os, subprocess, sys
d = json.loads(sys.argv[1])
tp = d.get("transcript_path", "")
if "subagent" in tp:
    sys.exit(0)
# 🔴 model guard, main only — PATTERNS «The model inside hooks»
model = subprocess.run(["bash", os.path.join(sys.argv[2], "main-model.sh"), tp],
                       capture_output=True, text=True).stdout.strip().lower()
if not ("fable" in model or "mythos" in model or model in ("", "unknown")):
    sys.exit(0)
prompt = d.get("tool_input", {}).get("prompt", "")
if len(prompt) <= 7000:
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": f"Reminder (CLAUDE.md, Orchestration): this brief is {len(prompt)} characters. One brief = one verifiable delivery; if the definition of done has more than ~5 independent points or touches more than ~6 files, split it into sequential briefs with the diff read between them."
}}))
PY
