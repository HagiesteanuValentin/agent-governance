#!/bin/bash
# 🔴 state from transcript, not a state file; rule 0 applies to everyone — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
input=$(cat)
python3 - "$input" "$(dirname "$0")" <<'PY'
import json, subprocess, sys, os

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
    deny("Bash output saved to a file; don't read it — rerun the command on a smaller "
         "range (`sed -n a,bp | head -150`)")

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


def pending_own_write(tpath):
    """True if the agent's own last event on this file is a write it never re-read."""
    events = []
    errors = set()
    if not tpath or not os.path.exists(tpath):
        return False
    with open(tpath, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
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
                if b.get("type") == "tool_result":
                    if b.get("is_error"):
                        errors.add(b.get("tool_use_id"))
                    continue
                if b.get("type") != "tool_use":
                    continue
                if cur_id and b.get("id") == cur_id:
                    continue
                name = b.get("name")
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if name == "Bash":
                    cmd = inp.get("command")
                    if base and isinstance(cmd, str) and base in cmd:
                        events.append(("clear", None))
                    continue
                if name not in ("Read", "Write", "Edit", "MultiEdit"):
                    continue
                fp = inp.get("file_path")
                if not isinstance(fp, str) or not fp:
                    continue
                try:
                    same_file = os.path.realpath(fp) == real
                except OSError:
                    same_file = fp == path
                if not same_file:
                    continue
                events.append(("clear", None) if name == "Read"
                              else ("write", b.get("id")))
    for kind, tid in reversed(events):
        if kind == "clear":
            return False
        # 🔴 an Edit with is_error doesn't count as a write — docs/PATTERNS.md «Reread after your own write»
        if tid in errors:
            continue
        return True
    return False


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
    try:
        lim = int(ti.get("limit") or 0)
    except (TypeError, ValueError):
        lim = 0
    # 🔴 <=60 lines = spot check, not a reread — docs/PATTERNS.md «Reread after your own write»
    if not (cur_ranged and 0 < lim <= 60):
        try:
            pending = pending_own_write(agent_tp)
        except Exception:
            pending = False
        if pending:
            deny("you wrote %s; don't reread it; spot-check with grep -n or sed -n "
                 "on a range" % base)
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

# 🔴 model guard, main only — PATTERNS «The model inside hooks»
_m = subprocess.run(["bash", os.path.join(sys.argv[2], "main-model.sh"), tp],
                    capture_output=True, text=True).stdout.strip().lower()
if not ("fable" in _m or "mythos" in _m or _m in ("", "unknown")):
    sys.exit(0)

if ext in IMG:
    low = base.lower()
    if "-small" in low or "-mic" in low:
        sys.exit(0)
    try:
        size = os.path.getsize(real)
    except OSError:
        size = 0
    if size > 200 * 1024:
        deny("%s is %d KB; explorer or design-lead sees the image and reports in text"
             % (base, size // 1024))
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
