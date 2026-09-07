#!/bin/bash
# 🔴 offline, synthetic payloads, no network/Claude — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
python3 - <<'PY'
import json, os, subprocess, sys, tempfile

HOOK = os.path.join(os.environ["HOOKS_DIR"], "comentarii-cod.sh")
TMP = tempfile.mkdtemp(prefix="test-cmt-")
RUN = "cmt%d" % os.getpid()
SESSION = "test-%s" % RUN
LOG = "/tmp/claude-hooks/comentarii-%s.jsonl" % SESSION
CODE = os.path.join(TMP, "src.js")
BLOCK2 = "// prima linie de nota\n// a doua linie de nota\nconst a = 1;"
POINTER = "// \U0001f534 constrangere - PATTERNS «section»\nconst a = 1;"
results = []


def payload(tool="Edit", path=CODE, agent=False, **ti_kw):
    ti = {"file_path": path}
    ti.update(ti_kw)
    d = {"session_id": SESSION, "cwd": TMP, "tool_name": tool, "tool_input": ti}
    if agent:
        d["agent_id"] = "a-%s" % RUN
        d["agent_type"] = "implementer"
        d["transcript_path"] = os.path.join(TMP, "s", "subagents", "agent-x.jsonl")
    return d


def call(d):
    p = subprocess.run(["bash", HOOK], input=json.dumps(d), text=True, capture_output=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def case(name, d, expect, needle=""):
    rc, out, err = call(d)
    body = ""
    if rc != 0 or err:
        got = "error"
    elif not out:
        got = "allow"
    else:
        try:
            h = json.loads(out)["hookSpecificOutput"]
        except Exception:
            h = {}
        if h.get("hookEventName") != "PreToolUse":
            got = "bad-event"
        elif h.get("permissionDecision") == "deny":
            got, body = "deny", h.get("permissionDecisionReason", "")
        elif h.get("additionalContext"):
            got, body = "context", h["additionalContext"]
        else:
            got, body = "unknown", out
    ok = got == expect and (not needle or got == "allow" or needle in body)
    results.append((name, ok, "%s (rc=%d)%s" % (got, rc, " stderr: " + err if err else "")))


case("agent 2-line block -> deny", payload(agent=True, old_string="const a = 1;",
     new_string=BLOCK2), "deny", "2 lines")
case("agent 1-line pointer -> allow", payload(agent=True, old_string="const a = 1;",
     new_string=POINTER), "allow")
case("agent long comment line -> deny", payload(agent=True, old_string="const a = 1;",
     new_string="// " + "x" * 200 + "\nconst a = 1;"), "deny", "chars")
case("main block -> context, no deny", payload(old_string="const a = 1;",
     new_string=BLOCK2), "context", "2 lines")
case("agent Write content block -> deny", payload(tool="Write",
     path=os.path.join(TMP, "nou.js"), agent=True,
     content=BLOCK2 + "\nconst b = 2;"), "deny", "2 lines")
case("agent MultiEdit block -> deny", payload(tool="MultiEdit", agent=True,
     edits=[{"old_string": "const b = 2;", "new_string": "const b = 3;"},
            {"old_string": "const a = 1;", "new_string": BLOCK2}]), "deny", "2 lines")
case("agent MultiEdit 2 separate pointers -> allow", payload(tool="MultiEdit", agent=True,
     edits=[{"old_string": "const a = 1;", "new_string": POINTER},
            {"old_string": "const b = 2;",
             "new_string": "// \U0001f534 alta - DECIZII «x»\nconst b = 2;"}]), "allow")
case("agent edit without comments -> allow", payload(agent=True,
     old_string="const a = 1;", new_string="const a = 2;"), "allow")
case("agent ratio 2/6 -> context, not deny", payload(agent=True, old_string="",
     new_string="// \U0001f534 unu - PATTERNS «x»\nconst a = 1;\nconst b = 2;\n"
                "// \U0001f534 doi - PATTERNS «y»\nconst c = 3;\nconst d = 4;"),
     "context", "added lines")
case("agent .md not code -> allow", payload(agent=True, path=os.path.join(TMP, "n.md"),
     old_string="text", new_string=BLOCK2), "allow")
rc_bad = subprocess.run(["bash", HOOK], input="not json", text=True,
                        capture_output=True).returncode
results.append(("invalid JSON -> exit 0", rc_bad == 0, "rc=%d" % rc_bad))
try:
    n_log = sum(1 for _ in open(LOG))
except OSError:
    n_log = 0
results.append(("log has %d rows (>=6)" % n_log, n_log >= 6, "%d rows" % n_log))
try:
    os.remove(LOG)
except OSError:
    pass

bad = 0
for name, ok, got in results:
    print("%s %s -- %s" % ("ok  " if ok else "FAIL", name, got))
    bad += 0 if ok else 1
print("%d/%d ok" % (len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
PY
