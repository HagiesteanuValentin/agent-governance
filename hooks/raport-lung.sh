#!/bin/bash
# 🔴 explorer-max* = 6000, rest = 2000 — docs/RECIPES.md «SubagentStop hook test»
LIMIT=2000
LIMIT_EXPLORER_MAX=6000
input=$(cat)
python3 - "$input" "$LIMIT" "$LIMIT_EXPLORER_MAX" <<'PY'
import json, os, re, sys
d = json.loads(sys.argv[1])
LIMIT, LIMIT_EXPLORER_MAX = int(sys.argv[2]), int(sys.argv[3])
if d.get("stop_hook_active"):
    sys.exit(0)
last = d.get("last_assistant_message") or ""
if not last:
    try:
        with open(d.get("transcript_path", "")) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                c = e.get("message", {}).get("content", [])
                t = c if isinstance(c, str) else "".join(
                    b.get("text", "") for b in c
                    if isinstance(b, dict) and b.get("type") == "text")
                if t.strip():
                    last = t
    except OSError:
        sys.exit(0)

# 🔴 no agent_type in input — deduce via sibling .meta.json — docs/RECIPES.md «SubagentStop hook test»
agent_type = d.get("agent_type") or ""
if not agent_type:
    agent_id = d.get("agent_id")
    session_id = d.get("session_id")
    tp = d.get("transcript_path") or ""
    if agent_id and session_id and tp:
        meta_path = os.path.join(os.path.dirname(tp), session_id, "subagents",
                                  "agent-%s.meta.json" % agent_id)
        try:
            with open(meta_path) as f:
                agent_type = json.load(f).get("agentType") or ""
        except (OSError, ValueError):
            pass

# 🔴 verdict OK / toate abaterile reparate => marker citit de commit-gate.sh — docs/DECIZII.md «Autoritate hook + commit gate (31.08.2026)»
def audit_ok(text):
    if "NECONFORM" in text:
        return False
    if re.search(r"VERDICT:\s*(OK|CONFORM)\b", text):
        return True
    # 🔴 matches the live RO audit format — docs/RECIPES.md «State from the transcript»
    m = re.search(r"ABATERI\s*\((\d+)\)\s*,\s*din care\s*(\d+)\s*reparate", text)
    return bool(m) and m.group(1) == m.group(2)


limit = LIMIT_EXPLORER_MAX if agent_type.startswith("explorer-max") else LIMIT
if len(last) <= limit:
    if agent_type.startswith("auditor") and audit_ok(last):
        marker_dir = os.environ.get("CLAUDE_HOOKS_DIR", "/tmp/claude-hooks")
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(d.get("session_id") or ""))
        try:
            os.makedirs(marker_dir, exist_ok=True)
            open(os.path.join(marker_dir, "audit-ok-%s" % sid), "w").close()
        except OSError:
            pass
    sys.exit(0)

reason = (f"The final report is {len(last)} characters. The limit for this agent "
          f"({agent_type or 'unknown'}) is {limit} characters. Send back ONLY the "
          "compressed report, in the fixed format, with no process narration.")
print(json.dumps({"decision": "block", "reason": reason,
    "hookSpecificOutput": {"hookEventName": d.get("hook_event_name", "SubagentStop"),
                           "decision": "block", "reason": reason}}))
PY
