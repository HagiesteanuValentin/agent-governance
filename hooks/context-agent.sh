#!/bin/bash
# 🔴 must read the sub-agent's own transcript, not main's — docs/workflow.md «Active hooks»
WARN_AT=150000
BLOCK_AT=220000
MARKER_DIR=/tmp/claude-hooks
input=$(cat)
python3 - "$input" "$WARN_AT" "$BLOCK_AT" "$MARKER_DIR" <<'PY'
import json, os, re, sys, time

d = json.loads(sys.argv[1])
WARN_AT, BLOCK_AT = int(sys.argv[2]), int(sys.argv[3])
MARKER_DIR = sys.argv[4]

agent_id = d.get("agent_id")
agent_type = d.get("agent_type") or ""
# main has no agent_id; explorer/scribe/auditor/design-lead have their own budgets
if not agent_id or not agent_type.startswith(("implementer", "scripter")):
    sys.exit(0)
tp = d.get("transcript_path") or ""
session_id = d.get("session_id") or ""
if not tp or not session_id:
    sys.exit(0)
# 🔴 in a sub-agent transcript_path is the MAIN transcript — DECIZII «v1.4.1 — 30.08.2026»
agent_tp = os.path.join(os.path.dirname(tp), session_id, "subagents",
                        "agent-%s.jsonl" % agent_id)
if not os.path.exists(agent_tp):
    sys.exit(0)

safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(agent_id))
LOG = os.path.join(MARKER_DIR, "context-agent.jsonl")


def marker_once(suffix):
    """True the first time it is called for this agent+suffix."""
    path = os.path.join(MARKER_DIR, "%s.%s" % (safe, suffix))
    try:
        os.makedirs(MARKER_DIR, exist_ok=True)
        if os.path.exists(path):
            return False
        open(path, "w").close()
    except OSError:
        return False
    return True


def log(ctx, decision):
    try:
        os.makedirs(MARKER_DIR, exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "agent_id": agent_id, "agent_type": agent_type,
                                 "ctx": ctx, "decision": decision}) + "\n")
    except OSError:
        pass


def emit(ctx, decision, **kw):
    log(ctx, decision)
    kw["hookEventName"] = "PreToolUse"
    print(json.dumps({"hookSpecificOutput": kw}))
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


ctx = last_context(agent_tp)
if marker_once("seen"):
    log(ctx, "seen")

# ---- a) context budget
if ctx >= BLOCK_AT and d.get("tool_name") != "Bash":
    emit(ctx, "deny", permissionDecision="deny",
         permissionDecisionReason=("Context >=%dk: only Bash for verification is allowed; "
                                   "write the final report now." % (BLOCK_AT // 1000)))
if ctx >= WARN_AT and marker_once("%dk" % (WARN_AT // 1000)):
    emit(ctx, "warn",
         additionalContext=("Context >=%dk: finish the item in progress, run the verification, "
                            "write the final report. Do not start a new item; report the rest "
                            "as not done." % (WARN_AT // 1000)))

# ---- b) verification counter
VERIF = re.compile(r"astro check|npm run build|npm test|vitest|pytest"
                   r"|verifica-[\w-]+\.mjs|verify-")
if d.get("tool_name") != "Bash":
    sys.exit(0)
ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
cmd = ti.get("command")
if not isinstance(cmd, str) or not VERIF.search(cmd):
    sys.exit(0)

cur_id = d.get("tool_use_id")
prior = 0
try:
    with open(agent_tp, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"Bash"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                if b.get("name") != "Bash" or (cur_id and b.get("id") == cur_id):
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                c = inp.get("command")
                if isinstance(c, str) and VERIF.search(c):
                    prior += 1
except OSError:
    sys.exit(0)

if prior + 1 >= 3 and marker_once("verif3"):
    emit(ctx, "verif3",
         additionalContext=("A 3-a verificare; brief-ul permite una la sfârșit și una după "
                            "fix-uri — continuă doar dacă ai făcut un fix de atunci."))
PY
