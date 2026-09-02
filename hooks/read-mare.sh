#!/bin/bash
# 🔴 state from transcript, not a state file; rule 0 applies to everyone — docs/RETETE.md «Stare din transcript, nu din fișier (read-mare, test-hooks)»
input=$(cat)
python3 - "$input" <<'PY'
import json, sys, os

d = json.loads(sys.argv[1])
ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
path = ti.get("file_path") or ""
if not isinstance(path, str) or not path:
    sys.exit(0)
tp = d.get("transcript_path") or ""


def emit(**kw):
    kw["hookEventName"] = "PreToolUse"
    print(json.dumps({"hookSpecificOutput": kw}))
    sys.exit(0)


def deny(reason):
    emit(permissionDecision="deny", permissionDecisionReason=reason)


# ---- 0) saved Bash output, everyone (main + sub-agents)
if "/tool-results/" in path:
    deny("output Bash salvat în fișier; nu-l citi — reia comanda pe un interval mai mic "
         "(`sed -n a,bp | head -150`)")

base = os.path.basename(path)
ext = os.path.splitext(path)[1].lower()
IMG = (".png", ".jpg", ".jpeg", ".webp", ".gif")
try:
    real = os.path.realpath(path)
except OSError:
    real = path
cur = (ti.get("offset"), ti.get("limit"))
cur_ranged = bool(cur[0] or cur[1])
cur_id = d.get("tool_use_id")


def prior_reads(tpath, skip_sidechain):
    """(call index, offset, limit) for every earlier Read of the same file."""
    out = []
    seen = 0
    if not tpath or not os.path.exists(tpath):
        return out
    with open(tpath, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"Read"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if skip_sidechain and obj.get("isSidechain"):
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") != "tool_use" or b.get("name") != "Read":
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                fp = inp.get("file_path")
                if not isinstance(fp, str) or not fp:
                    continue
                seen += 1
                if cur_id and b.get("id") == cur_id:
                    continue
                try:
                    same_file = os.path.realpath(fp) == real
                except OSError:
                    same_file = fp == path
                if same_file:
                    out.append((seen, inp.get("offset"), inp.get("limit")))
    return out


def line_count():
    try:
        return sum(1 for _ in open(real, "rb"))
    except OSError:
        return 0


# ---- sub-agents: only the ones with a budget; ranged re-reads stay legitimate
agent_id = d.get("agent_id") or ""
agent_type = d.get("agent_type") or ""
if agent_id or "subagent" in tp:
    FIX = " → Read with offset/limit on the range you need"
    if not agent_type.startswith(("implementer", "scripter", "cell-")):
        sys.exit(0)
    session_id = d.get("session_id") or ""
    if not agent_id or not tp or not session_id:
        sys.exit(0)
    # 🔴 in a sub-agent transcript_path is the MAIN transcript — DECIZII «v1.4.1 — 30.08.2026»
    agent_tp = os.path.join(os.path.dirname(tp), session_id, "subagents",
                            "agent-%s.jsonl" % agent_id)
    if cur_ranged:
        sys.exit(0)
    if ext in IMG or "/.claude/plans/" in path:
        sys.exit(0)
    try:
        # a missing own transcript only disables the re-read rule, not the size rule
        prior = prior_reads(agent_tp, skip_sidechain=False)
        n = line_count()
    except Exception:
        sys.exit(0)
    if prior:
        deny("already read at call %d in this agent%s" % (prior[0][0], FIX))
    if n > 300:
        deny("%d lines (>300)%s" % (n, FIX))
    sys.exit(0)

if ext in IMG:
    low = base.lower()
    if "-small" in low or "-mic" in low:
        sys.exit(0)
    emit(additionalContext=(
        "Reminder (CLAUDE.md): %s is an image - it enters the context and is re-paid on "
        "every following message. Comparing screenshots is the implementer's job; if you "
        "need a visual verdict here, read the downscaled variant *-mic.png." % base))

# ---- b) re-read of a file already read in the main thread
prior = prior_reads(tp, skip_sidechain=True)

if prior:
    ranged_prior = all(o or l for _, o, l in prior)
    repeat_range = any((o, l) == cur for _, o, l in prior)
    # a different slice of a file read before with offset/limit is new information
    if not (ranged_prior and cur_ranged and not repeat_range):
        deny("already read at call %d; re-check with offset/limit or ask the explorer"
             % prior[0][0])

# ---- c) whole big file
if cur_ranged:
    sys.exit(0)
if "/.claude/plans/" in path:
    sys.exit(0)
n = line_count()
if not n or n <= 300:
    sys.exit(0)
if ext == ".md" and n < 600:
    sys.exit(0)
deny("%d lines; use offset/limit, or the explorer/auditor" % n)
PY
