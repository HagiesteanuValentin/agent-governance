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
handback = None
# 🔴 SubagentStop runs after the handback is delivered; the cap must be enforced in PreToolUse — PATTERNS «SubagentHandback and final_text»
tp_agent = d.get("agent_transcript_path") or ""
if not tp_agent and d.get("agent_id") and d.get("session_id") and d.get("transcript_path"):
    tp_agent = os.path.join(os.path.dirname(d["transcript_path"]), d["session_id"],
                            "subagents", "agent-%s.jsonl" % d["agent_id"])
for tpath in (tp_agent, "" if last else d.get("transcript_path") or ""):
    if not tpath or not os.path.exists(tpath):
        continue
    found = ""
    try:
        with open(tpath) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                c = e.get("message", {}).get("content", [])
                for b in ([{"type": "text", "text": c}] if isinstance(c, str) else c):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and (b.get("text") or "").strip():
                        found, handback = b["text"], None
                    elif b.get("type") == "tool_use" and b.get("name") == "SubagentHandback":
                        m = (b.get("input") or {}).get("message")
                        if isinstance(m, str):
                            found, handback = m, m
    except OSError:
        continue
    if found or handback is not None:
        if not last or handback is not None:
            last = found
        break
if not last and handback is None:
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


limit = LIMIT_EXPLORER_MAX if "explorer-max" in agent_type else LIMIT  # 🔴 cells are named cell-explorer-max-* — PATTERNS «raport-lung: cap by substring»
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
if handback is not None:
    sys.exit(0)

reason = (f"The final report is {len(last)} characters. The limit for this agent "
          f"({agent_type or 'unknown'}) is {limit} characters. Send back ONLY the "
          "compressed report, in the fixed format, with no process narration.")
print(json.dumps({"decision": "block", "reason": reason,
    "hookSpecificOutput": {"hookEventName": d.get("hook_event_name", "SubagentStop"),
                           "decision": "block", "reason": reason}}))
PY
