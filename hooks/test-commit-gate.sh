#!/bin/bash
# 🔴 offline, temporary git repo + synthetic transcript — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 fixtures don't depend on the model in settings — PATTERNS «The model inside hooks»
export GOV_MODEL=claude-fable-5-1
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile, time

HOOKS = os.environ["HOOKS_DIR"]
GATE = os.path.join(HOOKS, "commit-gate.sh")
RAP = os.path.join(HOOKS, "raport-lung.sh")
TMP = tempfile.mkdtemp(prefix="test-commit-gate-")
MARKER_DIR = os.path.join(TMP, "markers")
os.makedirs(MARKER_DIR)
ENV = dict(os.environ, CLAUDE_HOOKS_DIR=MARKER_DIR)

results = []


def git(repo, *args):
    subprocess.run(["git"] + list(args), cwd=repo, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=False)


def repo_with(name, files):
    """git repo with one commit, then `files` written and staged."""
    repo = os.path.join(TMP, name)
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t"); git(repo, "config", "user.name", "t")
    open(os.path.join(repo, "seed.txt"), "w").write("seed\n")
    git(repo, "add", "."); git(repo, "commit", "-qm", "seed")
    for f in files:
        p = os.path.join(repo, f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("x = 1\n")
    git(repo, "add", ".")
    return repo


def transcript(sid, edit_ts=None):
    """main transcript at <TMP>/proj/<sid>.jsonl, optional Edit at edit_ts (epoch)."""
    p = os.path.join(TMP, "proj", "%s.jsonl" % sid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    lines = []
    if edit_ts is not None:
        iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(edit_ts)) + ".000Z"
        lines.append(json.dumps({
            "type": "assistant", "timestamp": iso,
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "Edit",
                 "input": {"file_path": "/x/a.ts"}}]}}))
    with open(p, "w") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    return p


def payload(sid, repo, cmd="git commit -m x", agent_id=None, tool="Bash"):
    d = {"session_id": sid, "transcript_path": transcript(sid), "cwd": repo,
         "tool_name": tool, "tool_input": {"command": cmd}}
    if agent_id:
        d["agent_id"] = agent_id
        d["agent_type"] = "implementer"
    return d


def call(hook, data, args=()):
    p = subprocess.Popen([hook] + list(args), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
    out, err = p.communicate(json.dumps(data).encode())
    return p.returncode, out.decode().strip(), err.decode().strip()


def case(name, data, expect, needle=""):
    rc, out, err = call(GATE, data)
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
            got = h.get("permissionDecision") or "unknown"
            body = h.get("permissionDecisionReason", "")
        ok = got == expect and (not needle or needle in body)
    results.append((name, ok, "%s (rc=%d)%s" % (got, rc, " stderr: " + err if err else "")))


def marker(sid, mtime=None):
    p = os.path.join(MARKER_DIR, "audit-ok-%s" % sid)
    open(p, "w").close()
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


R_TS = repo_with("r-ts", ["src/a.ts"])
R_MD = repo_with("r-md", ["docs/a.md"])
NOW = time.time()

# 1. no marker + diff .ts -> ask
case("no marker + diff .ts -> ask", payload("s1", R_TS), "ask", "audit")
case("git -C /x commit -> ask", payload("s1b", R_TS, cmd="git -C /x commit -m y"),
     "ask", "audit")
case("git --git-dir=... commit -> ask",
     payload("s1c", R_TS, cmd="git --git-dir=/x/.git commit -m y"), "ask", "audit")

# 2. fresh marker -> allow
marker("s2", NOW)
transcript("s2", NOW - 600)
d2 = payload("s2", R_TS); d2["transcript_path"] = transcript("s2", NOW - 600)
case("fresh marker (older Edit) -> allow", d2, "allow")

# 3. old marker vs. a later Edit -> ask
marker("s3", NOW - 600)
d3 = payload("s3", R_TS); d3["transcript_path"] = transcript("s3", NOW - 60)
case("old marker + later Edit -> ask", d3, "ask", "audit")

# 4. diff .md only -> allow
case("diff .md only -> allow", payload("s4", R_MD), "allow")

# 5. git commit in a subagent -> allow (unfiltered)
case("git commit in subagent -> allow", payload("s5", R_TS, agent_id="a1"), "allow")

# 6-8. edge cases
case("other Bash command -> allow", payload("s6", R_TS, cmd="git status"), "allow")
case("other tool -> allow", payload("s7", R_TS, tool="Read"), "allow")
case("cwd missing (fail-open) -> allow",
     payload("s8", os.path.join(TMP, "nope")), "allow")

# 9. .mjs / .astro caught by extensions
R_MJS = repo_with("r-mjs", ["scripts/a.mjs", "src/pages/b.astro"])
case("diff .mjs/.astro -> ask", payload("s9", R_MJS), "ask", "audit")

# 10. --extensii narrows the list
rc, out, err = call(GATE, payload("s10", R_MJS), args=["--extensii", "ts,js"])
results.append(("--extensii ts,js on .mjs diff -> allow",
                rc == 0 and not out and not err, "rc=%d out=%r" % (rc, out[:40])))


d5b = payload("s5b", R_TS)
d5b["transcript_path"] = os.path.join(TMP, "proj", "subagents", "agent-a2.jsonl")
case("subagent transcript (no agent_id) -> allow", d5b, "allow")

# 11. the later Edit is in a subagent transcript
marker("s11", NOW - 600)
d11 = payload("s11", R_TS); d11["transcript_path"] = transcript("s11", NOW - 900)
sub = os.path.join(TMP, "proj", "s11", "subagents")
os.makedirs(sub, exist_ok=True)
shutil.copy(transcript("s11-sub", NOW - 60), os.path.join(sub, "agent-a9.jsonl"))
case("Edit in subagent after marker -> ask", d11, "ask", "audit")


# ---------------------------------------------------------------- raport-lung: marker
def rap(sid, msg, agent_type="auditor"):
    tp = transcript(sid)
    return {"session_id": sid, "transcript_path": tp, "agent_id": "ra-%s" % sid,
            "agent_type": agent_type, "last_assistant_message": msg}


def rap_case(name, sid, msg, agent_type, expect_marker):
    p = os.path.join(MARKER_DIR, "audit-ok-%s" % sid)
    if os.path.exists(p):
        os.remove(p)
    rc, out, err = call(RAP, rap(sid, msg, agent_type))
    have = os.path.exists(p)
    results.append((name, rc == 0 and not err and have == expect_marker,
                    "marker=%s (rc=%d)%s" % (have, rc, " stderr: " + err if err else "")))


rap_case("VERDICT: OK -> marker", "sr1", "VERDICT: OK\nnimic de reparat",
         "auditor", True)
rap_case("VERDICT: CONFORM -> marker", "sr1b", "VERDICT: CONFORM", "auditor", True)
rap_case("ABATERI (2), 2 fixed -> marker", "sr2",
         "VERDICT: ABATERI (2), din care 2 reparate", "auditor", True)
rap_case("ABATERI (2), 1 fixed -> no marker", "sr3",
         "VERDICT: ABATERI (2), din care 1 reparate", "auditor", False)
rap_case("NECONFORM -> no marker", "sr4", "VERDICT: NECONFORM", "auditor", False)
rap_case("other agent with VERDICT: OK -> no marker", "sr5", "VERDICT: OK",
         "implementer", False)
rap_case("report too long with VERDICT: OK -> no marker", "sr6",
         "VERDICT: OK\n" + "x" * 2500, "auditor", False)

fails = [r for r in results if not r[1]]
for name, ok, info in results:
    print("%s %s — %s" % ("PASS" if ok else "FAIL", name, info))
print("\n%d/%d ok" % (len(results) - len(fails), len(results)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
PY
