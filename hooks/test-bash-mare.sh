#!/bin/bash
# 🔴 offline, synthetic transcripts, no Claude — docs/RETETE.md «Stare din transcript, nu din fișier (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 fixture-urile nu depind de modelul din settings — PATTERNS «Modelul în hook-uri»
export GOV_MODEL=claude-fable-5-1
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile

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

# 1) a 2-a rulare identică -> tăcut
got, body = agent_call("s1", CMD, [("bash", CMD)])
case("2 rulări identice -> tăcut", got == "silent", "%s %s" % (got, body))

# 2) a 3-a rulare identică -> additionalContext
got, body = agent_call("s2", CMD, [("bash", CMD), ("bash", CMD)])
case("a 3-a rulare -> context", got == "context" and "a 3-a rulare" in body,
     "%s %s" % (got, body))

# 3) Edit între rulări -> contor resetat
got, body = agent_call("s3", CMD, [("bash", CMD), ("bash", CMD), ("edit", "/x.ts")])
case("Edit între -> contor resetat", got == "silent", "%s %s" % (got, body))

# 4) main (fără agent_id) -> tăcut
agent_tp("s4", "a1", [("bash", CMD), ("bash", CMD)])
got, body = decide({"session_id": "s4", "transcript_path": tp("s4"),
                    "tool_name": "Bash", "tool_input": {"command": CMD}})
case("main -> tăcut", got == "silent", "%s %s" % (got, body))

# 5) normalizare: spații multiple / trim contează la fel
got, body = agent_call("s5", "  npm   test -- --run ",
                       [("bash", CMD), ("bash", "npm test  -- --run")])
case("normalizare spații -> context", got == "context", "%s %s" % (got, body))

# 6) comandă diferită -> tăcut
got, body = agent_call("s6", "npm run build", [("bash", CMD), ("bash", CMD)])
case("comandă diferită -> tăcut", got == "silent", "%s %s" % (got, body))

# 7) transcript de agent lipsă -> tăcut (fail-open)
got, body = decide({"session_id": "s7", "transcript_path": tp("s7"), "agent_id": "zzz",
                    "tool_name": "Bash", "tool_input": {"command": CMD}})
case("transcript agent lipsă -> tăcut", got == "silent", "%s %s" % (got, body))

# 8) JSON invalid -> exit 0, fără output
p = subprocess.run(["bash", HOOK], input="not json", text=True, capture_output=True)
case("JSON invalid -> exit 0, fără output",
     p.returncode == 0 and not p.stdout.strip(),
     "rc=%d out=%r" % (p.returncode, p.stdout.strip()))

shutil.rmtree(TMP, ignore_errors=True)
failed = [r for r in results if not r[1]]
for name, ok, got in results:
    if not ok:
        print("FAIL  %s -> %s" % (name, got))
print("%d/%d passed" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
PY
