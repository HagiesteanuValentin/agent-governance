#!/bin/bash
# PreToolUse on Read (main session only, not subagents): if the file is large and is read
# without offset/limit, inject the "use the explorer, not Read" reminder from CLAUDE.md.
# For images (without "-small" in the name): the "downscaled preview / delegate the
# comparison" reminder.
# It does NOT block — audits legitimately need full reads; the rule is only put under the nose.
input=$(cat)
python3 - "$input" <<'PY'
import json, sys, os
d = json.loads(sys.argv[1])
ti = d.get("tool_input", {})
path = ti.get("file_path", "")
# Subagents (explorer/implementer) are allowed to read — this hook is for the orchestrator.
# Detection: a subagent transcript path contains "subagent".
if "subagent" in d.get("transcript_path", ""):
    sys.exit(0)
ext = os.path.splitext(path)[1].lower()
if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
    # Downscaled previews (the -small suffix) are exempt — they ARE the recommended path.
    if "-small" in os.path.basename(path).lower():
        sys.exit(0)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": f"Reminder (CLAUDE.md): {os.path.basename(path)} is an image — it enters the context and is re-paid on every following message. Comparing screenshots is the implementer's job; if you need a visual verdict here, read the downscaled variant *-small.png."
    }}))
    sys.exit(0)
if ti.get("offset") or ti.get("limit"):
    sys.exit(0)
try:
    n = sum(1 for _ in open(path, "rb"))
except OSError:
    sys.exit(0)
if n <= 300:
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": f"Reminder (CLAUDE.md): {os.path.basename(path)} has {n} lines and you are reading all of it. If you only need one fact or one fragment, use the explorer or offset/limit; a full read is for audits."
}}))
PY
