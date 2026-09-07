#!/bin/bash
# 🔴 offline, synthetic transcripts, no network/Claude — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
python3 - <<'PY'
import glob, json, os, shutil, subprocess, sys, tempfile

HOOKS = os.environ["HOOKS_DIR"]
CTX_HOOK = os.path.join(HOOKS, "context-agent.sh")
TMP = tempfile.mkdtemp(prefix="test-ctx-main-")
RUN = "ctxm%d" % os.getpid()
MARKER_DIR = "/tmp/claude-hooks"


def usage_line(ctx):
    return {"type": "assistant",
            "message": {"role": "assistant", "id": "m1",
                        "usage": {"input_tokens": 1000,
                                  "cache_read_input_tokens": ctx - 1500,
                                  "cache_creation_input_tokens": 500},
                        "content": [{"type": "text", "text": "x"}]}}


def main_fixture(sid, ctx):
    """main transcript at <TMP>/proj/<sid>.jsonl"""
    p = os.path.join(TMP, "proj", "%s.jsonl" % sid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(json.dumps(usage_line(ctx)) + "\n")
    return p


def sub_fixture(sid, agent_id, ctx):
    """sub-agent transcript at <TMP>/proj/<sid>/subagents/agent-<id>.jsonl"""
    main_fixture(sid, 100000)
    p = os.path.join(TMP, "proj", sid, "subagents", "agent-%s.jsonl" % agent_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(json.dumps(usage_line(ctx)) + "\n")
    return p


def payload(sid, tool="Read", tool_input=None, agent_id=None, agent_type=None):
    d = {"session_id": sid,
         "transcript_path": os.path.join(TMP, "proj", "%s.jsonl" % sid),
         "cwd": TMP, "tool_name": tool, "tool_use_id": "cur",
         "tool_input": tool_input or {}}
    if agent_id:
        d["agent_id"] = agent_id
        d["agent_type"] = agent_type or "implementer"
    return d


def call(args, data):
    p = subprocess.Popen([CTX_HOOK] + args, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate(json.dumps(data).encode())
    return p.returncode, out.decode().strip(), err.decode().strip()


results = []


def case(name, args, data, expect, needle=""):
    rc, out, err = call(args, data)
    ok = rc == 0 and not err
    got = "error"
    body = out
    if ok:
        if not out:
            got = "allow"
        else:
            try:
                h = json.loads(out)["hookSpecificOutput"]
            except Exception:
                h = {}
            if h.get("permissionDecision") == "deny":
                got = "deny"
                body = h.get("permissionDecisionReason", "")
            elif h.get("additionalContext"):
                got = "context"
                body = h["additionalContext"]
            else:
                got = "unknown"
        ok = got == expect and (not needle or got == "allow" or needle in body)
    results.append((name, ok, "%s (rc=%d)%s" % (got, rc, " stderr: " + err if err else "")))


MAIN = ["--scope", "main"]

# 1-2. warning once, at >=150k
s_warn = "%s-warn" % RUN
main_fixture(s_warn, 160000)
case("main 160k Read -> additionalContext", MAIN, payload(s_warn), "context", "150k")
case("main 160k Read again -> allow (once)", MAIN, payload(s_warn), "allow")

# 3-6. deny at >=220k
s_deny = "%s-deny" % RUN
main_fixture(s_deny, 230000)
case("main 230k Read -> deny", MAIN, payload(s_deny), "deny", "220k")
case("main 230k Write outside plans -> deny", MAIN,
     payload(s_deny, "Write", {"file_path": os.path.join(TMP, "a.md")}), "deny", "220k")
case("main 230k Edit in /.claude/plans/ -> allow", MAIN,
     payload(s_deny, "Edit", {"file_path": "/home/x/.claude/plans/p.md"}),
     "context", "150k")   # warning consumes here; deny does not apply
case("main 230k Bash -> allow", MAIN, payload(s_deny, "Bash", {"command": "ls"}), "allow")
case("main 230k Agent scribe -> allow", MAIN,
     payload(s_deny, "Agent", {"subagent_type": "scribe"}), "allow")
case("main 230k Agent auditor -> allow", MAIN,
     payload(s_deny, "Agent", {"subagent_type": "auditor"}), "allow")
case("main 230k Agent implementer -> deny", MAIN,
     payload(s_deny, "Agent", {"subagent_type": "implementer-sonnet"}), "deny", "scribe/auditor")

# 7. custom thresholds from argv
s_arg = "%s-arg" % RUN
main_fixture(s_arg, 120000)
case("main 120k with --warn 100000 -> context", MAIN + ["--warn", "100000"],
     payload(s_arg), "context", "100k")
case("main 120k default thresholds -> allow", MAIN, payload(s_arg), "allow")

# 8. main scope ignores sub-agent calls
s_sub = "%s-sub" % RUN
sub_fixture(s_sub, "a-%s-1" % RUN, 230000)
case("scope main ignores a sub-agent call", MAIN,
     payload(s_sub, agent_id="a-%s-1" % RUN, agent_type="implementer"), "allow")

# 9-10. per-type thresholds (agent scope, opt-in)
s_son = "%s-son" % RUN
sub_fixture(s_son, "a-%s-son" % RUN, 160000)
case("implementer-sonnet 160k with --praguri-tip -> deny", ["--praguri-tip"],
     payload(s_son, "Edit", {"file_path": "/x/y.ts"},
             "a-%s-son" % RUN, "implementer-sonnet"), "deny", "150k")
s_scr = "%s-scr" % RUN
sub_fixture(s_scr, "a-%s-scr" % RUN, 110000)
case("scripter 110k with --praguri-tip -> context 100k", ["--praguri-tip"],
     payload(s_scr, "Edit", {"file_path": "/x/y.ts"},
             "a-%s-scr" % RUN, "scripter"), "context", "100k")
s_son2 = "%s-son2" % RUN
sub_fixture(s_son2, "a-%s-son2" % RUN, 160000)
case("implementer-sonnet 160k without --praguri-tip -> context 150k", [],
     payload(s_son2, "Edit", {"file_path": "/x/y.ts"},
             "a-%s-son2" % RUN, "implementer-sonnet"), "context", "150k")

# 11-12. cell-* only with --any-type
s_cell = "%s-cell" % RUN
sub_fixture(s_cell, "a-%s-cell" % RUN, 230000)
case("cell-opus-low without --any-type -> allow", ["--scope", "agent"],
     payload(s_cell, "Read", {}, "a-%s-cell" % RUN, "cell-opus-low"), "allow")
case("cell-opus-low with --any-type 230k -> deny", ["--scope", "agent", "--any-type"],
     payload(s_cell, "Read", {}, "a-%s-cell" % RUN, "cell-opus-low"), "deny", "220k")

# 13. fail-open on garbage input
p = subprocess.Popen([CTX_HOOK] + MAIN, stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
out, err = p.communicate(b"{not json")
results.append(("garbage stdin -> exit 0, no output",
                p.returncode == 0 and not out.strip() and not err.strip(),
                "rc=%d" % p.returncode))

# cleanup: markers and log rows from this run
for f in glob.glob(os.path.join(MARKER_DIR, "*%s*" % RUN)):
    try:
        os.remove(f)
    except OSError:
        pass
log = os.path.join(MARKER_DIR, "context-agent.jsonl")
if os.path.exists(log):
    try:
        keep = [l for l in open(log) if RUN not in l]
        with open(log, "w") as fh:
            fh.writelines(keep)
    except OSError:
        pass
shutil.rmtree(TMP, ignore_errors=True)

bad = 0
for name, ok, got in results:
    print("%s %s -> %s" % ("PASS" if ok else "FAIL", name, got))
    bad += 0 if ok else 1
print("%d/%d ok" % (len(results) - bad, len(results)))
sys.exit(1 if bad else 0)
PY
