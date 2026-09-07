#!/bin/bash
# PreToolUse/Write|Edit, main only: over 20 written lines belong to scribe/implementer
BODY_LINES=20
LOG_DIR=/tmp/claude-hooks
mkdir -p "$LOG_DIR" 2>/dev/null
payload=$(mktemp "$LOG_DIR/write-mare-XXXXXX" 2>/dev/null || mktemp) || exit 0
cat > "$payload"
python3 - "$payload" "$BODY_LINES" "$(dirname "$0")" <<'PY'
import json, os, subprocess, sys

try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as _fh:
        d = json.loads(_fh.read())
    if not isinstance(d, dict):
        sys.exit(0)
except Exception:
    sys.exit(0)
finally:
    try:
        os.remove(sys.argv[1])
    except OSError:
        pass

BODY_LINES = int(sys.argv[2])

try:
    tp = d.get("transcript_path") or ""
    if d.get("agent_id") or "subagent" in tp:
        sys.exit(0)
    # 🔴 model guard, main only — PATTERNS «The model inside hooks»
    model = subprocess.run(["bash", os.path.join(sys.argv[3], "main-model.sh"), tp],
                           capture_output=True, text=True).stdout.strip().lower()
    if not ("fable" in model or "mythos" in model or model in ("", "unknown")):
        sys.exit(0)
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    path = ti.get("file_path") or ""
    if not isinstance(path, str):
        path = ""
    # 🔴 exempt: plan + memory; HANDOFF.md stays with the scribe — DECIZII «v1.6 — hook-uri pentru orchestrator (02.09.2026)»
    if "/.claude/plans/" in path or "/memory/" in path:
        sys.exit(0)
    body = ti.get("content")
    if not isinstance(body, str):
        body = ti.get("new_string")
    if not isinstance(body, str) or not body:
        sys.exit(0)
    n = len(body.rstrip("\n").split("\n"))
    if n > BODY_LINES:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": (
                ">20 lines from main → scribe/implementer; briefs come from the plan "
                "via sed -n (%d lines here)" % n)}}))
except Exception:
    sys.exit(0)
PY
exit 0
