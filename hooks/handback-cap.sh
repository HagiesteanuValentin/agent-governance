#!/bin/bash
# 🔴 SubagentStop runs after the handback is delivered; the cap must be enforced in PreToolUse — PATTERNS «SubagentHandback and final_text»
LIMIT=2000
LIMIT_EXPLORER_MAX=6000
input=$(cat)
python3 - "$input" "$LIMIT" "$LIMIT_EXPLORER_MAX" <<'PY' 2>/dev/null
import json, os, sys
try:
    d = json.loads(sys.argv[1])
    LIMIT, LIMIT_EXPLORER_MAX = int(sys.argv[2]), int(sys.argv[3])
    if d.get("tool_name") != "SubagentHandback":
        sys.exit(0)
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    msg = ti.get("message")
    if not isinstance(msg, str):
        sys.exit(0)
    agent_type = d.get("agent_type") or ""
    if not agent_type:
        agent_id, session_id = d.get("agent_id"), d.get("session_id")
        tp = d.get("transcript_path") or ""
        if agent_id and session_id and tp:
            meta = os.path.join(os.path.dirname(tp), session_id, "subagents",
                                "agent-%s.meta.json" % agent_id)
            try:
                with open(meta) as f:
                    agent_type = json.load(f).get("agentType") or ""
            except (OSError, ValueError):
                pass
    limit = LIMIT_EXPLORER_MAX if "explorer-max" in agent_type else LIMIT
    n = len(msg)
    if n <= limit:
        sys.exit(0)
    reason = (f"Report has {n} chars, cap is {limit}. Call SubagentHandback again with "
              f"ONLY the compressed report (≤{limit} chars); do not send the long "
              "version as text.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "deny", "permissionDecisionReason": reason}}))
except SystemExit:
    raise
except Exception:
    sys.exit(0)
PY
exit 0
