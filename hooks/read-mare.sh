#!/bin/bash
# PreToolUse on Read, main session only (a sub-agent input carries agent_id -> exit 0).
# Three rules, in order:
#   a) full-size image  -> warning (additionalContext), as before;
#   b) same file already read in this main session -> deny (v1.4: was a warning);
#   c) no offset/limit and over 300 lines -> deny. Exempt: plan files, .md under 600 lines.
# State comes from the transcript, not from a state file; the current call's own tool_use
# block is already in the jsonl, so it is skipped by tool_use_id.
input=$(cat)
python3 - "$input" <<'PY'
import json, sys, os

d = json.loads(sys.argv[1])
# a sub-agent (implementer/explorer/auditor) reads its own target legitimately
if d.get("agent_id"):
    sys.exit(0)
tp = d.get("transcript_path") or ""
if "subagent" in tp:
    sys.exit(0)
ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
path = ti.get("file_path") or ""
if not isinstance(path, str) or not path:
    sys.exit(0)


def emit(**kw):
    kw["hookEventName"] = "PreToolUse"
    print(json.dumps({"hookSpecificOutput": kw}))
    sys.exit(0)


def deny(reason):
    emit(permissionDecision="deny", permissionDecisionReason=reason)


base = os.path.basename(path)
ext = os.path.splitext(path)[1].lower()

if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
    low = base.lower()
    if "-small" in low or "-mic" in low:
        sys.exit(0)
    emit(additionalContext=(
        "Reminder (CLAUDE.md): %s is an image - it enters the context and is re-paid on "
        "every following message. Comparing screenshots is the implementer's job; if you "
        "need a visual verdict here, read the downscaled variant *-mic.png." % base))

try:
    real = os.path.realpath(path)
except OSError:
    real = path
cur = (ti.get("offset"), ti.get("limit"))
cur_ranged = bool(cur[0] or cur[1])

# ---- b) re-read of a file already read in the main thread
prior = []
seen = 0
cur_id = d.get("tool_use_id")
if tp and os.path.exists(tp):
    with open(tp, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"Read"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("isSidechain"):
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
                    prior.append((seen, inp.get("offset"), inp.get("limit")))

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
try:
    n = sum(1 for _ in open(real, "rb"))
except OSError:
    sys.exit(0)
if n <= 300:
    sys.exit(0)
if ext == ".md" and n < 600:
    sys.exit(0)
deny("%d lines; use offset/limit, or the explorer/auditor" % n)
PY
