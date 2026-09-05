#!/bin/bash
# 🔴 offline, transcripturi sintetice, fără rețea/Claude — docs/RETETE.md «Stare din transcript, nu din fișier (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 suita testează sursa modelului; GOV_MODEL moștenit din test-hooks ar ascunde-o — PATTERNS «Modelul în hook-uri»
unset GOV_MODEL
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile

HOOKS = os.environ["HOOKS_DIR"]
MODEL_HOOK = os.path.join(HOOKS, "main-model.sh")
WRITE_HOOK = os.path.join(HOOKS, "write-mare.sh")
BRIEF_HOOK = os.path.join(HOOKS, "brief-mare.sh")
START_HOOK = os.path.join(HOOKS, "session-start.sh")
CMT_HOOK = os.path.join(HOOKS, "comentarii-cod.sh")
TMP = tempfile.mkdtemp(prefix="test-model-gate-")
RUN = "mg%d" % os.getpid()
CMT_SESSION = "cmt-%s" % RUN
CMT_LOG = "/tmp/claude-hooks/comentarii-%s.jsonl" % CMT_SESSION

results = []
def check(name, ok, got):
    results.append((name, bool(ok), got))

def write(rel, lines):
    p = os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return p

def line(model, text="ok"):
    return json.dumps({"type": "assistant", "model": model,
                       "message": {"role": "assistant", "content": [
                           {"type": "text", "text": text}]}})

def user_line(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "content": text}]}})

def call(hook, payload, env=None, args=()):
    e = dict(os.environ, **(env or {}))
    p = subprocess.run(["bash", hook] + list(args), input=json.dumps(payload),
                       text=True, capture_output=True, env=e)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def decision(out):
    if not out:
        return "allow"
    try:
        h = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return "unknown"
    return h.get("permissionDecision") or ("context" if h.get("additionalContext") else "unknown")

# ------------------------------------------------------------------ fixtures
OPUS = write("proj/opus.jsonl", [user_line("log: claude-opus-5 mentioned"),
                                 line("claude-opus-5")])
FABLE = write("proj/fable.jsonl", [line("claude-fable-5-1")])
# tool_result cu textul claude-opus DUPĂ ultima linie de assistant pe Fable
TRICK = write("proj/trick.jsonl", [line("claude-fable-5-1"),
                                   user_line("output contains claude-opus-5 text")])
SYNTH = write("proj/synth.jsonl", [line("claude-fable-5-1"),
                                   json.dumps({"type": "assistant", "model": "<synthetic>",
                                               "message": {"role": "assistant",
                                                           "content": []}})])
SUBTP = write("proj/opus/subagents/agent-a1.jsonl", [line("claude-opus-5")])
BODY50 = "\n".join("line %d" % i for i in range(50))

def model_of(tp, env=None):
    e = dict(os.environ, **(env or {}))
    p = subprocess.run(["bash", MODEL_HOOK, tp], text=True, capture_output=True, env=e)
    return p.returncode, p.stdout.strip()

# ------------------------------------------------------------------ helper
rc, m = model_of(OPUS)
check("helper: transcript Opus -> claude-opus-5", rc == 0 and m == "claude-opus-5", m)
rc, m = model_of(TRICK)
check("helper: tool_result cu 'claude-opus' ignorat -> fable",
      rc == 0 and m == "claude-fable-5-1", m)
rc, m = model_of(SYNTH)
check("helper: <synthetic> ignorat -> fable", rc == 0 and m == "claude-fable-5-1", m)
rc, m = model_of("/nonexistent/x.jsonl")
check("helper: fara transcript -> settings (fable, fara [1m])",
      rc == 0 and "fable" in m and "[1m]" not in m, m)
rc, m = model_of(FABLE, env={"GOV_MODEL": "claude-opus-5"})
check("helper: GOV_MODEL are prioritate", rc == 0 and m == "claude-opus-5", m)

# ------------------------------------------------------------------ write-mare
def write_in(tp, agent_id=None):
    d = {"session_id": "s1", "transcript_path": tp, "cwd": TMP, "tool_name": "Write",
         "tool_use_id": "cur",
         "tool_input": {"file_path": os.path.join(TMP, "x.js"), "content": BODY50}}
    if agent_id:
        d["agent_id"] = agent_id
    return d

rc, out, err = call(WRITE_HOOK, write_in(OPUS))
check("write-mare: main pe Opus, 50 de linii -> allow",
      rc == 0 and not err and decision(out) == "allow", "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(WRITE_HOOK, write_in(FABLE))
check("write-mare: main pe Fable, 50 de linii -> deny",
      rc == 0 and not err and decision(out) == "deny", "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(WRITE_HOOK, write_in(FABLE), env={"GOV_MODEL": "claude-opus-5"})
check("write-mare: GOV_MODEL=opus -> allow",
      rc == 0 and decision(out) == "allow", "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(WRITE_HOOK, write_in("/nonexistent/x.jsonl"))
check("write-mare: transcript inexistent -> exit 0", rc == 0 and not err, "rc=%d" % rc)

# ------------------------------------------------------------------ brief-mare
def brief_in(tp):
    return {"session_id": "s1", "transcript_path": tp, "cwd": TMP, "tool_name": "Agent",
            "tool_use_id": "cur", "tool_input": {"prompt": "x" * 8000}}

rc, out, err = call(BRIEF_HOOK, brief_in(OPUS))
check("brief-mare: main pe Opus, 8000 de caractere -> tacere",
      rc == 0 and not out, "out=%r (rc=%d)" % (out[:40], rc))
rc, out, err = call(BRIEF_HOOK, brief_in(FABLE))
check("brief-mare: main pe Fable -> additionalContext",
      rc == 0 and decision(out) == "context", "%s (rc=%d)" % (decision(out), rc))

# ------------------------------------------------------------------ session-start
start_payload = {"session_id": "s1", "transcript_path": OPUS, "source": "startup",
                 "cwd": TMP}
env_opus = {"GOV_MODEL": "claude-opus-5", "CLAUDE_PROJECT_DIR": TMP}
env_fable = {"GOV_MODEL": "claude-fable-5-1", "CLAUDE_PROJECT_DIR": TMP}
rc, out, err = call(START_HOOK, start_payload, env=env_opus, args=("rules",))
check("session-start rules pe Opus: fara ORCHESTRATION, cu rand de efort",
      rc == 0 and "=== ORCHESTRATION" not in out and "effort main" in out,
      "rc=%d len=%d" % (rc, len(out)))
rc, out, err = call(START_HOOK, start_payload, env=env_opus, args=("v17",))
check("session-start v17 pe Opus: fara ORCHESTRATION v1.7",
      rc == 0 and "=== ORCHESTRATION" not in out and "effort main" in out,
      "rc=%d len=%d" % (rc, len(out)))
rc_f, out_f, err_f = call(START_HOOK, start_payload, env=env_fable, args=("rules",))
has_rules = os.path.isfile(os.path.expanduser("~/.claude/orchestrare.md"))
check("session-start rules pe Fable: ORCHESTRATION injectat (daca exista fisierul)",
      rc_f == 0 and (("=== ORCHESTRATION" in out_f) if has_rules else True),
      "rc=%d orchestrare.md=%s" % (rc_f, has_rules))
# HANDOFF rămâne pe orice model
write("HANDOFF.md", ["stare curenta"])
rc, out, err = call(START_HOOK, start_payload, env=env_opus, args=("handoff",))
check("session-start handoff pe Opus: HANDOFF injectat",
      rc == 0 and "HANDOFF.md" in out and "stare curenta" in out, "rc=%d" % rc)

# ------------------------------------------------------------------ read-mare (main)
RM_TARGET = write("read-target.txt", ["line %d" % i for i in range(10)])

def read_tp(name, model):
    return write("proj/%s.jsonl" % name, [json.dumps(
        {"type": "assistant", "model": model,
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Read",
              "input": {"file_path": RM_TARGET}}]}})])

def read_in(tp):
    return {"session_id": "s1", "transcript_path": tp, "cwd": TMP, "tool_name": "Read",
            "tool_use_id": "cur", "tool_input": {"file_path": RM_TARGET}}

RM_HOOK = os.path.join(HOOKS, "read-mare.sh")
rc, out, err = call(RM_HOOK, read_in(read_tp("rm-fable", "claude-fable-5-1")))
check("read-mare: main pe Fable, re-citire -> deny",
      rc == 0 and decision(out) == "deny", "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(RM_HOOK, read_in(read_tp("rm-opus", "claude-opus-5")))
check("read-mare: main pe Opus, re-citire -> allow",
      rc == 0 and decision(out) == "allow", "%s (rc=%d)" % (decision(out), rc))

# ------------------------------------------------------------------ bash-mare (main)
BM_HOOK = os.path.join(HOOKS, "bash-mare.sh")
BIG = write("big.txt", ["line %d" % i for i in range(400)])

def bash_in(tp):
    return {"session_id": "s1", "transcript_path": tp, "cwd": TMP, "tool_name": "Bash",
            "tool_use_id": "cur", "tool_input": {"command": "cat %s" % BIG}}

rc, out, err = call(BM_HOOK, bash_in(FABLE))
check("bash-mare: main pe Fable, cat pe 400 de linii -> deny",
      rc == 0 and decision(out) == "deny", "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(BM_HOOK, bash_in(OPUS))
check("bash-mare: main pe Opus -> allow",
      rc == 0 and decision(out) == "allow", "%s (rc=%d)" % (decision(out), rc))

# ------------------------------------------------------------------ agenti-vii (main)
AV_HOOK = os.path.join(HOOKS, "agenti-vii.sh")
AV_DIR = os.path.join(TMP, "markers")
os.makedirs(AV_DIR, exist_ok=True)
AV_ENV = {"CLAUDE_HOOKS_DIR": AV_DIR, "AGENTI_VII_CAP": "1"}

def av_in(tp, agent_id=None):
    d = {"session_id": "av-%s" % RUN, "transcript_path": tp, "cwd": TMP,
         "tool_name": "Agent", "tool_use_id": "cur", "tool_input": {"prompt": "x"}}
    if agent_id:
        d["agent_id"] = agent_id
        d["agent_type"] = "implementer"
    return d

call(AV_HOOK, av_in(FABLE, agent_id="av1-%s" % RUN), env=AV_ENV, args=("start",))
rc, out, err = call(AV_HOOK, av_in(FABLE), env=AV_ENV, args=("check",))
check("agenti-vii: main pe Fable, peste cap -> ask",
      rc == 0 and decision(out) == "ask", "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(AV_HOOK, av_in(OPUS), env=AV_ENV, args=("check",))
check("agenti-vii: main pe Opus -> allow",
      rc == 0 and decision(out) == "allow", "%s (rc=%d)" % (decision(out), rc))

# ------------------------------------------------------------------ commit-gate (main)
CG_HOOK = os.path.join(HOOKS, "commit-gate.sh")
CG_MARKERS = os.path.join(TMP, "cg-markers")
os.makedirs(CG_MARKERS, exist_ok=True)
REPO = os.path.join(TMP, "repo")
os.makedirs(REPO, exist_ok=True)

def git(*args):
    subprocess.run(["git"] + list(args), cwd=REPO, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=False)

git("init", "-q")
git("config", "user.email", "t@t")
git("config", "user.name", "t")
open(os.path.join(REPO, "seed.txt"), "w").write("seed\n")
git("add", ".")
git("commit", "-qm", "seed")
open(os.path.join(REPO, "a.ts"), "w").write("x = 1\n")
git("add", ".")

def cg_in(tp):
    return {"session_id": "cg-%s" % RUN, "transcript_path": tp, "cwd": REPO,
            "tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}

rc, out, err = call(CG_HOOK, cg_in(FABLE), env={"CLAUDE_HOOKS_DIR": CG_MARKERS})
check("commit-gate: main pe Fable, diff .ts fara marker -> ask",
      rc == 0 and decision(out) == "ask", "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(CG_HOOK, cg_in(OPUS), env={"CLAUDE_HOOKS_DIR": CG_MARKERS})
check("commit-gate: main pe Opus -> allow",
      rc == 0 and decision(out) == "allow", "%s (rc=%d)" % (decision(out), rc))

# ------------------------------------------------------------------ agent pe Opus
BLOCK3 = "// prima\n// a doua\n// a treia\nconst a = 1;"
cmt = {"session_id": CMT_SESSION, "cwd": TMP, "tool_name": "Edit", "tool_use_id": "cur",
       "transcript_path": SUBTP, "agent_id": "a-%s" % RUN, "agent_type": "implementer",
       "tool_input": {"file_path": os.path.join(TMP, "src.js"),
                      "old_string": "const a = 1;", "new_string": BLOCK3}}
rc, out, err = call(CMT_HOOK, cmt, env={"GOV_MODEL": "claude-opus-5"})
check("agent pe Opus: garda de comentarii ramane activa",
      rc == 0 and decision(out) in ("context", "deny"), "%s (rc=%d)" % (decision(out), rc))
rc, out, err = call(WRITE_HOOK, write_in(SUBTP, agent_id="a-%s" % RUN),
                    env={"GOV_MODEL": "claude-fable-5-1"})
check("agent: write-mare tace si pe Fable (ramura de agent neschimbata)",
      rc == 0 and decision(out) == "allow", "%s (rc=%d)" % (decision(out), rc))

# ------------------------------------------------------------------ cleanup
for p in (CMT_LOG,):
    try:
        os.remove(p)
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
rm -f /tmp/claude-hooks/bash-batch-s1* 2>/dev/null
exit $rc
