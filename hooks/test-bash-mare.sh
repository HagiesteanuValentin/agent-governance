#!/bin/bash
# 🔴 offline, synthetic transcripts, no Claude — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 fixtures don't depend on the model in settings — PATTERNS «The model inside hooks»
export GOV_MODEL=claude-fable-5-1
rm -f /tmp/claude-hooks/bash-batch-* 2>/dev/null
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile, time

HOOK = os.path.join(os.environ["HOOKS_DIR"], "bash-mare.sh")
TMP = tempfile.mkdtemp(prefix="test-bash-mare-")
results = []


def case(name, ok, got):
    results.append((name, ok, got))


def tp(sid):
    p = os.path.join(TMP, "proj", "%s.jsonl" % sid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "a").close()
    return p


def agent_tp(sid, aid, events):
    """events: ("bash", cmd) | ("edit", path) — written as tool_use blocks."""
    tp(sid)
    p = os.path.join(TMP, "proj", sid, "subagents", "agent-%s.jsonl" % aid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        for i, (kind, arg) in enumerate(events):
            if kind == "bash":
                blk = {"type": "tool_use", "name": "Bash", "id": "t%d" % i,
                       "input": {"command": arg}}
            else:
                blk = {"type": "tool_use", "name": "Edit", "id": "t%d" % i,
                       "input": {"file_path": arg}}
            fh.write(json.dumps({"type": "assistant",
                                 "message": {"content": [blk]}}) + "\n")
    return p


def call(payload):
    p = subprocess.run(["bash", HOOK], input=json.dumps(payload), text=True,
                       capture_output=True, env=dict(os.environ))
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def decide(payload):
    rc, out, err = call(payload)
    if rc != 0 or err:
        return "error", "rc=%d %s" % (rc, err)
    if not out:
        return "silent", ""
    try:
        h = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return "unknown", out
    if h.get("additionalContext"):
        return "context", h["additionalContext"]
    return h.get("permissionDecision") or "unknown", h.get("permissionDecisionReason", "")


def agent_call(sid, cmd, events, aid="a1"):
    agent_tp(sid, aid, events)
    return decide({"session_id": sid, "transcript_path": tp(sid), "agent_id": aid,
                   "agent_type": "implementer", "tool_name": "Bash",
                   "tool_use_id": "cur", "tool_input": {"command": cmd}})


CMD = "npm test -- --run"

# 1) 2nd identical run -> silent
got, body = agent_call("s1", CMD, [("bash", CMD)])
case("2 identical runs -> silent", got == "silent", "%s %s" % (got, body))

# 2) 3rd identical run -> additionalContext
got, body = agent_call("s2", CMD, [("bash", CMD), ("bash", CMD)])
case("3rd run -> context", got == "context" and "3rd identical run" in body,
     "%s %s" % (got, body))

# 3) Edit in between runs -> counter reset
got, body = agent_call("s3", CMD, [("bash", CMD), ("bash", CMD), ("edit", "/x.ts")])
case("Edit in between -> counter reset", got == "silent", "%s %s" % (got, body))

# 4) main (no agent_id) -> silent
agent_tp("s4", "a1", [("bash", CMD), ("bash", CMD)])
got, body = decide({"session_id": "s4", "transcript_path": tp("s4"),
                    "tool_name": "Bash", "tool_input": {"command": CMD}})
case("main -> silent", got == "silent", "%s %s" % (got, body))

# 5) normalization: multiple spaces / trim count the same
got, body = agent_call("s5", "  npm   test -- --run ",
                       [("bash", CMD), ("bash", "npm test  -- --run")])
case("space normalization -> context", got == "context", "%s %s" % (got, body))

# 6) different command -> silent
got, body = agent_call("s6", "npm run build", [("bash", CMD), ("bash", CMD)])
case("different command -> silent", got == "silent", "%s %s" % (got, body))

# 7) missing agent transcript -> silent (fail-open)
got, body = decide({"session_id": "s7", "transcript_path": tp("s7"), "agent_id": "zzz",
                    "tool_name": "Bash", "tool_input": {"command": CMD}})
case("missing agent transcript -> silent", got == "silent", "%s %s" % (got, body))

# 8) invalid JSON -> exit 0, no output
p = subprocess.run(["bash", HOOK], input="not json", text=True, capture_output=True)
case("invalid JSON -> exit 0, no output",
     p.returncode == 0 and not p.stdout.strip(),
     "rc=%d out=%r" % (p.returncode, p.stdout.strip()))

# 9-12) batching nudge in main

# 🔴 the gap is simulated via a pre-written counter, not sleep — PATTERNS «Bash batching»


def state_path(sid):
    return "/tmp/claude-hooks/bash-batch-%s" % sid


def set_state(sid, count, age):
    os.makedirs("/tmp/claude-hooks", exist_ok=True)
    with open(state_path(sid), "w") as fh:
        fh.write("%d %f" % (count, time.time() - age))


def main_call(sid, cmd):
    return decide({"session_id": sid, "transcript_path": tp(sid), "tool_name": "Bash",
                   "tool_use_id": "cur", "tool_input": {"command": cmd}})


SMALL = "git status --short"
BIG = "echo " + "x" * 220

set_state("b1", 1, 10)
got, body = main_call("b1", SMALL)
case("2nd small call -> silent", got == "silent", "%s %s" % (got, body))

set_state("b1", 2, 10)
got, body = main_call("b1", SMALL)
case("al 3-lea apel mic (gap >=3 s) -> context",
     got == "context" and "batchable_bash" in body, "%s %s" % (got, body))

set_state("b2", 2, 10)
main_call("b2", BIG)
set_state("b2", int(open(state_path("b2")).read().split()[0]), 10)
got, body = main_call("b2", SMALL)
case("large command -> counter reset", got == "silent", "%s %s" % (got, body))

set_state("b3", 0, 10)
for _i in range(3):
    got, body = main_call("b3", SMALL)
case("3 calls at <3s (same message) -> silent",
     got == "silent" and open(state_path("b3")).read().split()[0] == "1",
     "%s %s state=%s" % (got, body, open(state_path("b3")).read()))

for _f in ("b1", "b2", "b3"):
    try:
        os.remove(state_path(_f))
    except OSError:
        pass

shutil.rmtree(TMP, ignore_errors=True)
failed = [r for r in results if not r[1]]
for name, ok, got in results:
    if not ok:
        print("FAIL  %s -> %s" % (name, got))
print("%d/%d passed" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
PY
rc=$?
rm -f /tmp/claude-hooks/bash-batch-* 2>/dev/null
exit $rc
