#!/bin/bash
# 🔴 offline, synthetic transcripts, no network/Claude — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 fixtures don't depend on the model from settings — PATTERNS «The model inside hooks»
export GOV_MODEL=claude-fable-5-1
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile

HOOKS = os.environ["HOOKS_DIR"]
READ_HOOK = os.path.join(HOOKS, "read-mare.sh")
TMP = tempfile.mkdtemp(prefix="test-read-agent-")
SID = "s1"
MAIN_TP = os.path.join(TMP, "proj", "%s.jsonl" % SID)


def write(rel, lines):
    p = os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return p


def jsonl(rel, objs):
    return write(rel, [json.dumps(o) for o in objs])


def read_use(tid, path, offset=None, limit=None):
    inp = {"file_path": path}
    if offset is not None:
        inp["offset"] = offset
    if limit is not None:
        inp["limit"] = limit
    return {"type": "tool_use", "id": tid, "name": "Read", "input": inp}


def tool_use(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def error_result(tid):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": True,
         "content": "String to replace not found in file."}]}}


def blob(rel, nbytes):
    p = os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(b"\x89PNG\r\n" + b"\0" * (nbytes - 6))
    return p


def assistant(tool_uses, side=False):
    o = {"type": "assistant", "message": {"role": "assistant", "id": "m1",
         "usage": {"input_tokens": 1}, "content": tool_uses}}
    if side:
        o["isSidechain"] = True
    return o


# ---------------------------------------------------------------- fixtures
small = write("a.txt", ["line %d" % i for i in range(10)])
fresh = write("fresh.txt", ["line %d" % i for i in range(10)])
big = write("big.txt", ["line %d" % i for i in range(400)])
bigmd = write("big.md", ["line %d" % i for i in range(400)])
ranged = write("ranged.txt", ["line %d" % i for i in range(400)])
planmd = write("fakehome/.claude/plans/plan.md", ["line %d" % i for i in range(700)])
img = write("shot.png", ["x"])

jsonl("proj/%s.jsonl" % SID, [
    {"type": "user", "message": {"role": "user", "content": "go"}},
    assistant([read_use("r1", small)]),
])
# a sub-agent transcript is a sidechain: its own Reads must still count
AGENT = "a1"
jsonl("proj/%s/subagents/agent-%s.jsonl" % (SID, AGENT), [
    {"type": "user", "message": {"role": "user", "content": "brief"}},
    assistant([read_use("r1", big)], side=True),
    assistant([read_use("r2", ranged, offset=1, limit=50)], side=True),
])

# --- write-then-reread fixtures: one agent per scenario
wrote = write("wrote.txt", ["line %d" % i for i in range(10)])
jsonl("proj/%s/subagents/agent-aw.jsonl" % SID, [
    assistant([tool_use("w1", "Write", {"file_path": wrote, "content": "x"})], side=True),
])
jsonl("proj/%s/subagents/agent-ar.jsonl" % SID, [
    assistant([tool_use("w1", "Write", {"file_path": wrote, "content": "x"})], side=True),
    assistant([read_use("r9", wrote)], side=True),
])
jsonl("proj/%s/subagents/agent-ae.jsonl" % SID, [
    assistant([tool_use("e1", "Edit", {"file_path": wrote, "new_string": "x"})], side=True),
    error_result("e1"),
])
jsonl("proj/%s/subagents/agent-ab.jsonl" % SID, [
    assistant([tool_use("w1", "Write", {"file_path": wrote, "content": "x"})], side=True),
    assistant([tool_use("b1", "Bash", {"command": "bash wrote.txt"})], side=True),
])
jsonl("proj/%s/subagents/agent-ao.jsonl" % SID, [
    assistant([tool_use("w1", "Write", {"file_path": small, "content": "x"})], side=True),
])
bigimg = blob("big.png", 300 * 1024)
smallimg = blob("small.png", 50 * 1024)


# ---------------------------------------------------------------- harness
def call(payload):
    p = subprocess.run(["bash", READ_HOOK], input=json.dumps(payload), text=True,
                       capture_output=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def agent_in(path, agent_id=AGENT, agent_type="implementer", tool_use_id="cur", **kw):
    return {"session_id": SID, "transcript_path": MAIN_TP, "cwd": TMP,
            "tool_name": "Read", "tool_use_id": tool_use_id,
            "agent_id": agent_id, "agent_type": agent_type,
            "tool_input": dict({"file_path": path}, **kw)}


def main_in(path, tool_use_id="cur", **kw):
    return {"session_id": SID, "transcript_path": MAIN_TP, "cwd": TMP,
            "tool_name": "Read", "tool_use_id": tool_use_id,
            "tool_input": dict({"file_path": path}, **kw)}


results = []


def case(name, payload, expect, needle=""):
    rc, out, err = call(payload)
    ok = rc == 0 and not err
    got, body = "error", ""
    if ok:
        if not out:
            got = "allow"
        else:
            try:
                h = json.loads(out)["hookSpecificOutput"]
            except Exception:
                h = {}
            if h.get("permissionDecision") == "deny":
                got, body = "deny", h.get("permissionDecisionReason", "")
            elif h.get("additionalContext"):
                got, body = "context", h["additionalContext"]
            else:
                got, body = "unknown", out
        ok = got == expect and (not needle or got == "allow" or needle in body)
    results.append((name, ok, "%s (rc=%d)%s" % (got, rc, " stderr: " + err if err else "")))


FIX = "Read with offset/limit on the range you need"

# ---------------------------------------------------------------- sub-agent
case("agent fresh 400 lines no range -> deny", agent_in(bigmd, tool_use_id="x"),
     "deny", "400 lines (>300)")
case("agent 400 lines with offset -> allow", agent_in(bigmd, offset=1, limit=50), "allow")
case("agent reread whole file -> deny", agent_in(big, tool_use_id="x"), "deny", FIX)
case("agent reread with offset -> allow", agent_in(big, offset=100, limit=50), "allow")
case("agent same slice again -> allow (Edit re-read)",
     agent_in(ranged, offset=1, limit=50), "allow")
case("agent own tool_use not a reread -> allow small file",
     agent_in(small, tool_use_id="r1"), "allow")
case("agent small fresh file -> allow", agent_in(fresh), "allow")
case("agent scripter filtered too", agent_in(bigmd, agent_type="scripter-complex"),
     "deny", "400 lines (>300)")
case("agent cell-* filtered too", agent_in(bigmd, agent_type="cell-runner"),
     "deny", "400 lines (>300)")
case("explorer not filtered", agent_in(bigmd, agent_type="explorer"), "allow")
case("auditor not filtered", agent_in(big, agent_type="auditor"), "allow")
case("agent plan file exempt", agent_in(planmd), "allow")
case("agent image exempt", agent_in(img), "allow")
case("agent tool-results still denied",
     agent_in(os.path.join(TMP, "tool-results", "x.txt")), "deny", "rerun the command")
case("no own transcript, 400 lines -> deny", agent_in(bigmd, agent_id="missing"),
     "deny", "400 lines (>300)")
case("no own transcript, with offset -> allow",
     agent_in(bigmd, agent_id="missing", offset=1, limit=50), "allow")
case("no own transcript, small file -> allow", agent_in(fresh, agent_id="missing"),
     "allow")

# ------------------------------------------------- write-then-reread + images
WROTE = "you wrote wrote.txt"
case("agent reads back own Write -> deny", agent_in(wrote, agent_id="aw"), "deny", WROTE)
case("agent spot-check 50 lines after Write -> allow",
     agent_in(wrote, agent_id="aw", offset=10, limit=50), "allow")
case("agent 100-line range after Write -> deny",
     agent_in(wrote, agent_id="aw", offset=10, limit=100), "deny", WROTE)
case("agent already re-read after Write -> old rule",
     agent_in(wrote, agent_id="ar"), "deny", "already read at call")
case("agent after failed Edit -> allow", agent_in(wrote, agent_id="ae"), "allow")
case("agent after Bash on the file -> allow", agent_in(wrote, agent_id="ab"), "allow")
case("agent Write on another file -> allow", agent_in(fresh, agent_id="ao"), "allow")
case("main image 300 KB -> deny", main_in(bigimg), "deny", "explorer or design-lead")
case("main image 50 KB -> reminder only", main_in(smallimg), "context", "downscaled")
case("agent image 300 KB -> allow", agent_in(bigimg), "allow")

# ---------------------------------------------------------------- main regression
case("main reread whole file -> deny", main_in(small), "deny", "already read at call 1")
case("main 400 lines -> deny", main_in(big), "deny", "400 lines")
case("main md under 600 -> allow", main_in(bigmd), "allow")
case("main first read -> allow", main_in(fresh), "allow")

shutil.rmtree(TMP, ignore_errors=True)

failed = [r for r in results if not r[1]]
for name, ok, got in results:
    if not ok:
        print("FAIL  %s -> %s" % (name, got))
print("%d/%d passed" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
PY
