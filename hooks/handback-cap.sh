#!/bin/bash
# 🔴 SubagentStop runs after the handback is delivered; the cap must be enforced in PreToolUse — PATTERNS «SubagentHandback and final_text»
LIMIT=2000
LIMIT_EXPLORER_MAX=6000
LIMIT_PLAN_LEAD=15000
input=$(cat)
python3 - "$input" "$LIMIT" "$LIMIT_EXPLORER_MAX" "$LIMIT_PLAN_LEAD" <<'PY' 2>/dev/null
import json, os, sys
try:
    d = json.loads(sys.argv[1])
    LIMIT, LIMIT_EXPLORER_MAX, LIMIT_PLAN_LEAD = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
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
    limit = (LIMIT_PLAN_LEAD if ("design-lead" in agent_type or "refiner" in agent_type)
             else LIMIT_EXPLORER_MAX if "explorer-max" in agent_type else LIMIT)  # 🔴 tested before explorer-max; cells cell-* inherit by substring — PATTERNS «raport-lung: cap by substring»
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
