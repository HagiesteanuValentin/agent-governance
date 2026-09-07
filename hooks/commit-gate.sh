#!/bin/bash
# 🔴 the audit-ok marker is written by raport-lung.sh on CONFORM — docs/DECIZII.md «Autoritate hook + commit gate (31.08.2026)»
MARKER_DIR=${CLAUDE_HOOKS_DIR:-/tmp/claude-hooks}
input=$(cat)
GOV_HOOKS_DIR=$(dirname "$0")
export GOV_HOOKS_DIR
python3 - "$input" "$MARKER_DIR" "$@" <<'PY'
import json, os, re, subprocess, sys
from datetime import datetime, timezone

RAW = sys.argv[1]
MARKER_DIR = sys.argv[2]
ARGV = sys.argv[3:]

EXTS = ["ts", "tsx", "js", "jsx", "mjs", "astro"]
GIT = os.environ.get("COMMIT_GATE_GIT", "git")
# 🔴 also catches `git -C x commit` / `git --git-dir=... commit` — docs/DECIZII.md «Autoritate hook + commit gate (31.08.2026)»
GIT_COMMIT = re.compile(r"\bgit\b(\s+-\S+(\s+\S+)?)*\s+commit\b")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
REASON = ("commit without a CONFORM audit: run /audit on the commit range and get the "
          "orchestrator's confirmation before `git commit`.")


def parse_args(argv):
    global EXTS
    i = 0
    while i < len(argv):
        if argv[i] == "--extensii" and i + 1 < len(argv):
            EXTS = [e.strip().lstrip(".") for e in argv[i + 1].split(",") if e.strip()]
            i += 2
        else:
            i += 1


def diff_touches(cwd, exts):
    """True if staged (else unstaged) --stat lists a file with one of exts."""
    pat = re.compile(r"\.(%s)\s*(\{[^}]*\}\s*)?\|" % "|".join(re.escape(e) for e in exts))
    for args in (["diff", "--cached", "--stat"], ["diff", "--stat"]):
        try:
            out = subprocess.run([GIT] + args, cwd=cwd, timeout=5,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                                 ).stdout.decode("utf-8", "replace")
        except Exception:
            return False
        if not out.strip():
            continue
        return bool(pat.search(out))
    return False


def to_epoch(ts):
    if not isinstance(ts, str) or not ts:
        return None
    t = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def last_edit(path):
    """Epoch of the newest Edit/Write tool_use in one transcript; None if none."""
    newest = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not any(('"%s"' % t) in line for t in EDIT_TOOLS):
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
                if not any(isinstance(b, dict) and b.get("type") == "tool_use"
                           and b.get("name") in EDIT_TOOLS for b in content):
                    continue
                e = to_epoch(obj.get("timestamp"))
                if e is not None and (newest is None or e > newest):
                    newest = e
    except OSError:
        return None
    return newest


def session_last_edit(tp, session_id):
    """Newest Edit/Write across the main transcript and the session's sub-agents."""
    newest = last_edit(tp)
    subdir = os.path.join(os.path.dirname(tp), str(session_id), "subagents")
    try:
        names = os.listdir(subdir)
    except OSError:
        names = []
    for n in names:
        if not n.endswith(".jsonl"):
            continue
        e = last_edit(os.path.join(subdir, n))
        if e is not None and (newest is None or e > newest):
            newest = e
    return newest


def run():
    parse_args(ARGV)
    d = json.loads(RAW)
    # 🔴 main only, same convention as read-mare.sh — docs/DECIZII.md «Autoritate hook + commit gate (31.08.2026)»
    if d.get("agent_id") or "subagent" in (d.get("transcript_path") or ""):
        return
    # 🔴 model guard, main only — PATTERNS «The model inside hooks»
    _m = subprocess.run(["bash", os.path.join(os.environ.get("GOV_HOOKS_DIR", "."),
                                              "main-model.sh"),
                         d.get("transcript_path") or ""],
                        capture_output=True, text=True).stdout.strip().lower()
    if not ("fable" in _m or "mythos" in _m or _m in ("", "unknown")):
        return
    if d.get("tool_name") != "Bash":
        return
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    cmd = ti.get("command")
    if not isinstance(cmd, str) or not GIT_COMMIT.search(cmd):
        return
    cwd = d.get("cwd") or os.getcwd()
    if not diff_touches(cwd, EXTS):
        return

    session_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(d.get("session_id") or ""))
    marker = os.path.join(MARKER_DIR, "audit-ok-%s" % session_id)
    try:
        mtime = os.path.getmtime(marker)
    except OSError:
        mtime = None
    if mtime is not None:
        tp = d.get("transcript_path") or ""
        edit = session_last_edit(tp, d.get("session_id") or "") if tp else None
        if edit is None or edit <= mtime:
            return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": REASON}}))


try:
    run()
except SystemExit:
    raise
except Exception:
    pass
sys.exit(0)
PY
