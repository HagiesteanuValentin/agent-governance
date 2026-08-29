#!/bin/bash
# SubagentStop: the subagent's last message >2000 characters -> block ONCE, asking for a
# compressed report in the fixed format. Guarded on stop_hook_active so it cannot loop.
# Reads last_assistant_message (official field); falls back to the transcript if absent.
input=$(cat)
python3 - "$input" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
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
if len(last) <= 2000:
    sys.exit(0)
reason = (f"The final report is {len(last)} characters. The fixed format in your instructions "
          "allows at most 1,500 (soft) / 2,000 (hard). Send back ONLY the compressed report, "
          "in the fixed format, with no process narration.")
print(json.dumps({"decision": "block", "reason": reason,
    "hookSpecificOutput": {"hookEventName": d.get("hook_event_name", "SubagentStop"),
                           "decision": "block", "reason": reason}}))
PY
