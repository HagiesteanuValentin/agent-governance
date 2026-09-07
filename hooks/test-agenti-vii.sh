#!/bin/bash
# 🔴 offline, synthetic state in tmp, no Claude — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 fixtures don't depend on the model from settings — PATTERNS «The model inside hooks»
export GOV_MODEL=claude-fable-5-1
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile, time

HOOK = os.path.join(os.environ["HOOKS_DIR"], "agenti-vii.sh")
TMP = tempfile.mkdtemp(prefix="test-agenti-vii-")
STATE_DIR = os.path.join(TMP, "hooks")
ENV = dict(os.environ, CLAUDE_HOOKS_DIR=STATE_DIR)
NOW = int(time.time())

results = []


def tp(sid):
    p = os.path.join(TMP, "proj", "%s.jsonl" % sid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "a").close()
    return p


def state_path(sid):
    return os.path.join(STATE_DIR, "live-%s" % sid)


def make(sid, agents):
    """agents: (agent_id, agent_type, row_age_sec, jsonl_age_sec|None)."""
    tp(sid)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(sid), "w") as fh:
        for aid, atype, row_age, js_age in agents:
            fh.write("%s\t%s\t%d\n" % (aid, atype, NOW - row_age))
            if js_age is None:
                continue
            p = os.path.join(TMP, "proj", sid, "subagents", "agent-%s.jsonl" % aid)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write('{"type":"user"}\n')
            os.utime(p, (NOW - js_age, NOW - js_age))


def call(mode, payload):
    p = subprocess.run(["bash", HOOK, mode], input=json.dumps(payload), text=True,
                       capture_output=True, env=ENV)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def decide(mode, payload):
    rc, out, err = call(mode, payload)
    if rc != 0 or err:
        return "error", "rc=%d %s" % (rc, err)
    if not out:
        return "allow", ""
    try:
        h = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return "unknown", out
    return h.get("permissionDecision") or "unknown", h.get("permissionDecisionReason", "")


def case(name, ok, got):
    results.append((name, ok, got))


def check_case(name, sid, agents, expect, needle=""):
    make(sid, agents)
    got, body = decide("check", {"session_id": sid, "transcript_path": tp(sid),
                                 "tool_name": "Agent", "tool_input": {}})
    ok = got == expect and (not needle or needle in body)
    case(name, ok, "%s %s" % (got, body))


def rows(sid):
    try:
        return [l.rstrip("\n").split("\t") for l in open(state_path(sid)) if l.strip()]
    except OSError:
        return []


A = lambda n, t="explorer", row=10, js=10: ("a%d" % n, t, row, js)

# 1) 5 live -> allow
check_case("5 live agents -> allow", "s1", [A(1), A(2), A(3), A(4), A(5)], "allow")

# 2) 6 live -> ask
check_case("6 live agents -> ask", "s2", [A(1), A(2), A(3), A(4), A(5), A(6)], "ask",
           "6 live agents")
case("message lists type/id", "explorer/a1" in
     decide("check", {"session_id": "s2", "transcript_path": tp("s2"),
                      "tool_name": "Agent", "tool_input": {}})[1], "lista")

# 3) 6 live, one with jsonl older than 5 min -> allow + row disappears
check_case("6 live, 1 with jsonl older than 5 min -> allow", "s3",
           [A(1), A(2), A(3), A(4), A(5), ("a6", "scribe", 900, 900)], "allow")
case("stale row is cleaned from file", len(rows("s3")) == 5,
     "%d rows" % len(rows("s3")))

# 4) 6 live, one with no jsonl and an old row -> allow
check_case("6 live, 1 with no jsonl and old row -> allow", "s4",
           [A(1), A(2), A(3), A(4), A(5), ("a6", "scribe", 900, None)], "allow")

# 5) 6 live, one with no jsonl but just started -> ask (grace period)
check_case("6 live, 1 with no jsonl but fresh -> ask", "s5",
           [A(1), A(2), A(3), A(4), A(5), ("a6", "scribe", 5, None)], "ask", "6 live agents")

# 6) start adds the row in the format agent_id\tagent_type\ttimestamp
sid = "s6"
tp(sid)
rc6, out6, err6 = call("start", {"session_id": sid, "transcript_path": tp(sid),
                                 "agent_id": "b1", "agent_type": "implementer"})
r6 = rows(sid)
case("start writes 1 row id/type/ts",
     rc6 == 0 and not out6 and len(r6) == 1 and r6[0][0] == "b1"
     and r6[0][1] == "implementer" and r6[0][2].isdigit(), "%r" % r6)
call("start", {"session_id": sid, "transcript_path": tp(sid),
               "agent_id": "b1", "agent_type": "implementer"})
case("start twice on same id does not duplicate", len(rows(sid)) == 1,
     "%d rows" % len(rows(sid)))

# 7) stop removes the row
call("start", {"session_id": sid, "transcript_path": tp(sid),
               "agent_id": "b2", "agent_type": "scribe"})
call("stop", {"session_id": sid, "transcript_path": tp(sid), "agent_id": "b1"})
r7 = rows(sid)
case("stop removes only its own row", len(r7) == 1 and r7[0][0] == "b2", "%r" % r7)

# 8) session with no state file -> allow
got8, _ = decide("check", {"session_id": "s-inexistent", "transcript_path": tp("s9"),
                           "tool_name": "Agent", "tool_input": {}})
case("session with no state file -> allow", got8 == "allow", got8)

# 9) fail-open: invalid JSON / missing fields
p = subprocess.run(["bash", HOOK, "check"], input="not json", text=True,
                   capture_output=True, env=ENV)
case("invalid JSON -> exit 0, no output", p.returncode == 0 and not p.stdout.strip(),
     "rc=%d out=%r" % (p.returncode, p.stdout.strip()))
p = subprocess.run(["bash", HOOK, "start"], input=json.dumps({"session_id": "s7"}),
                   text=True, capture_output=True, env=ENV)
case("start without agent_id -> exit 0", p.returncode == 0 and not p.stdout.strip(),
     "rc=%d" % p.returncode)

# 10b) autonomous mode: 6 live agents + marker -> no ask
make("s11", [A(1), A(2), A(3), A(4), A(5), A(6)])
os.makedirs(STATE_DIR, exist_ok=True)
open(os.path.join(STATE_DIR, "autonom-s11"), "w").write("1\n")
got11, _ = decide("check", {"session_id": "s11", "transcript_path": tp("s11"),
                            "tool_name": "Agent", "tool_input": {}})
case("6 live + autonomous marker -> allow", got11 == "allow", got11)

# 10) session isolation: cap reached in s2 doesn't affect s1
got10, _ = decide("check", {"session_id": "s1", "transcript_path": tp("s1"),
                            "tool_name": "Agent", "tool_input": {}})
case("state file per session", got10 == "allow", got10)

shutil.rmtree(TMP, ignore_errors=True)
failed = [r for r in results if not r[1]]
for name, ok, got in results:
    if not ok:
        print("FAIL  %s -> %s" % (name, got))
print("%d/%d passed" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
PY
