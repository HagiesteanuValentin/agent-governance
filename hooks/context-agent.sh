#!/bin/bash
# PreToolUse in implementer*/scripter* sub-agents only: reads the worker's own context size from the
# last assistant line of its transcript and wraps the run up before quality degrades
# (measured v1.1-v1.2: tool_result errors 0.9% -> 5.1% and $/call doubled between the first
# and the last quarter of the big runs).
#   >= WARN_AT  -> one-time additionalContext (marker in /tmp/claude-hooks)
#   >= BLOCK_AT -> deny everything except Bash (verification + the final report)
WARN_AT=150000
BLOCK_AT=220000
MARKER_DIR=/tmp/claude-hooks
input=$(cat)
python3 - "$input" "$WARN_AT" "$BLOCK_AT" "$MARKER_DIR" <<'PY'
import json, os, re, sys

d = json.loads(sys.argv[1])
WARN_AT, BLOCK_AT = int(sys.argv[2]), int(sys.argv[3])
MARKER_DIR = sys.argv[4]

agent_id = d.get("agent_id")
agent_type = d.get("agent_type") or ""
# main has no agent_id; explorer/scribe/auditor/design-lead have their own budgets
if not agent_id or not agent_type.startswith(("implementer", "scripter")):
    sys.exit(0)
tp = d.get("transcript_path") or ""
if not tp or not os.path.exists(tp):
    sys.exit(0)


def last_context(path):
    """input + cache_read + cache_creation on the last assistant line; 0 if none."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > 512 * 1024:
                fh.seek(size - 512 * 1024)
            data = fh.read()
    except OSError:
        return 0
    for raw in reversed(data.split(b"\n")):
        if b'"usage"' not in raw or b'"assistant"' not in raw:
            continue
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        u = msg.get("usage")
        if not isinstance(u, dict):
            continue
        return ((u.get("input_tokens") or 0)
                + (u.get("cache_read_input_tokens") or 0)
                + (u.get("cache_creation_input_tokens") or 0))
    return 0


ctx = last_context(tp)
if ctx < WARN_AT:
    sys.exit(0)


def emit(**kw):
    kw["hookEventName"] = "PreToolUse"
    print(json.dumps({"hookSpecificOutput": kw}))
    sys.exit(0)


if ctx >= BLOCK_AT and d.get("tool_name") != "Bash":
    emit(permissionDecision="deny",
         permissionDecisionReason=("Context >=%dk: only Bash for verification is allowed; "
                                   "write the final report now." % (BLOCK_AT // 1000)))

safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(agent_id))
marker = os.path.join(MARKER_DIR, "%s.%dk" % (safe, WARN_AT // 1000))
try:
    os.makedirs(MARKER_DIR, exist_ok=True)
    if os.path.exists(marker):
        sys.exit(0)
    open(marker, "w").close()
except OSError:
    sys.exit(0)
emit(additionalContext=("Context >=%dk: finish the item in progress, run the verification, "
                        "write the final report. Do not start a new item; report the rest "
                        "as not done." % (WARN_AT // 1000)))
PY
