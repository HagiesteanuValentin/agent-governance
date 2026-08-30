#!/bin/bash
# Offline test for read-mare.sh, context-agent.sh and comentarii-cod.sh: synthetic transcripts + JSON on stdin,
# no network, no Claude. Exit 0 only if every case passes; prints "N/N passed".
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile, time

HOOKS = os.environ["HOOKS_DIR"]
READ_HOOK = os.path.join(HOOKS, "read-mare.sh")
CTX_HOOK = os.path.join(HOOKS, "context-agent.sh")
CMT_HOOK = os.path.join(HOOKS, "comentarii-cod.sh")
TMP = tempfile.mkdtemp(prefix="test-hooks-")
RUN = "test%d" % os.getpid()
MARKERS = []

def write(rel, lines):
    p = os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return p

def jsonl(rel, objs):
    return write(rel, [json.dumps(o) for o in objs])

def assistant(tool_uses, side=False):
    o = {"type": "assistant", "message": {"role": "assistant", "id": "m%d" % len(tool_uses),
         "usage": {"input_tokens": 1}, "content": tool_uses}}
    if side:
        o["isSidechain"] = True
    return o

def read_use(tid, path, offset=None, limit=None):
    inp = {"file_path": path}
    if offset is not None:
        inp["offset"] = offset
    if limit is not None:
        inp["limit"] = limit
    return {"type": "tool_use", "id": tid, "name": "Read", "input": inp}

def bash_use(tid, cmd):
    return {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}

def usage_line(ctx):
    return {"type": "assistant", "message": {"role": "assistant", "id": "u1",
            "usage": {"input_tokens": 1000, "cache_read_input_tokens": ctx - 1500,
                      "cache_creation_input_tokens": 500},
            "content": [{"type": "text", "text": "working"}]}}

# ---------------------------------------------------------------- fixtures
small = write("a.txt", ["line %d" % i for i in range(10)])
fresh = write("fresh.txt", ["line %d" % i for i in range(10)])
side = write("side.txt", ["line %d" % i for i in range(10)])
ranged = write("ranged.txt", ["line %d" % i for i in range(100)])
big = write("big.txt", ["line %d" % i for i in range(400)])
bigmd = write("big.md", ["line %d" % i for i in range(400)])
hugemd = write("huge.md", ["line %d" % i for i in range(700)])
planmd = write("fakehome/.claude/plans/plan.md", ["line %d" % i for i in range(700)])
img = write("shot.png", ["x"])
imgmic = write("shot-mic.png", ["x"])

MAIN = jsonl("main.jsonl", [
    {"type": "user", "message": {"role": "user", "content": "go"}},
    assistant([read_use("r1", small)]),
    assistant([read_use("r2", ranged, offset=1, limit=50)]),
    assistant([read_use("r3", side)], side=True),
])
# real layout: MAIN = <proj>/<sid>.jsonl (always 230k here), worker = <proj>/<sid>/subagents/
SESSIONS = set()

def sub_fixture(agent_id, ctx, bash_cmds=(), sid=None, pad_lines=0):
    sid = sid or "s-%s" % agent_id
    if sid not in SESSIONS:
        SESSIONS.add(sid)
        jsonl("proj/%s.jsonl" % sid,
              [{"type": "user", "message": {"role": "user", "content": "go"}},
               usage_line(230000)])
    objs = [{"type": "user", "message": {"role": "user", "content": "brief"}}]
    objs += [{"type": "user", "message": {"role": "user", "content": "x" * 900}}] * pad_lines
    objs += [assistant([bash_use("b%d" % i, c)]) for i, c in enumerate(bash_cmds)]
    objs.append(usage_line(ctx))
    jsonl("proj/%s/subagents/agent-%s.jsonl" % (sid, agent_id), objs)
    return sid

# 1 MB transcripts for the timing check
pad = "x" * 900
big_main = jsonl("big-main.jsonl",
                 [{"type": "user", "message": {"role": "user", "content": pad}}] * 1100
                 + [assistant([read_use("r1", small)])])

# ---------------------------------------------------------------- harness
def call(hook, payload):
    p = subprocess.run(["bash", hook], input=json.dumps(payload), text=True,
                       capture_output=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def read_in(path, transcript=MAIN, tool_use_id="cur", **kw):
    d = {"session_id": "s1", "transcript_path": transcript, "cwd": TMP,
         "tool_name": "Read", "tool_use_id": tool_use_id,
         "tool_input": dict({"file_path": path}, **kw)}
    return d

def ctx_in(sid, agent_id=None, agent_type="implementer", tool_name="Read", command=None):
    ti = {"command": command} if command else {}
    d = {"session_id": sid, "transcript_path": os.path.join(TMP, "proj", "%s.jsonl" % sid),
         "cwd": TMP, "tool_name": tool_name, "tool_use_id": "cur", "tool_input": ti}
    if agent_id:
        d["agent_id"] = agent_id
        d["agent_type"] = agent_type
        MARKERS.append(agent_id)
    return d

def ctx_case(name, agent_id, ctx, expect, needle="", agent_type="implementer",
             tool_name="Read", command=None, bash_cmds=(), reuse=False):
    aid = "a-%s-%s" % (RUN, agent_id)
    sid = sub_fixture(aid, ctx, bash_cmds) if not reuse else "s-%s" % aid
    case(name, CTX_HOOK, ctx_in(sid, aid, agent_type, tool_name, command), expect, needle)

results = []
def case(name, hook, payload, expect, needle=""):
    rc, out, err = call(hook, payload)
    ok = rc == 0 and not err
    got = "error"
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
                body = out
        ok = got == expect and (not needle or (got == "allow") or needle in body)
    results.append((name, ok, "%s (rc=%d)%s" % (got, rc, " stderr: " + err if err else "")))

# ---------------------------------------------------------------- read-mare
case("reread same file -> deny", READ_HOOK, read_in(small), "deny", "already read at call 1")
case("own tool_use not a reread", READ_HOOK, read_in(small, tool_use_id="r1"), "allow")
case("first read -> allow", READ_HOOK, read_in(fresh), "allow")
case("sidechain prior read ignored", READ_HOOK, read_in(side), "allow")
case("400 lines no range -> deny", READ_HOOK, read_in(big), "deny", "400 lines")
case("400 lines with offset -> allow", READ_HOOK, read_in(big, offset=1, limit=50), "allow")
case("md under 600 -> allow", READ_HOOK, read_in(bigmd), "allow")
case("md over 600 -> deny", READ_HOOK, read_in(hugemd), "deny", "700 lines")
case("plan file exempt", READ_HOOK, read_in(planmd), "allow")
case("image -> warning", READ_HOOK, read_in(img), "context", "image")
case("image -mic -> allow", READ_HOOK, read_in(imgmic), "allow")
case("other slice of ranged file -> allow", READ_HOOK,
     read_in(ranged, offset=200, limit=50), "allow")
case("same slice again -> deny", READ_HOOK, read_in(ranged, offset=1, limit=50), "deny",
     "already read")
case("full read after ranged -> deny", READ_HOOK, read_in(ranged), "deny", "already read")
sub_payload = read_in(small)
sub_payload["agent_id"] = "a-%s-x" % RUN
sub_payload["agent_type"] = "implementer"
case("sub-agent not affected by read-mare", READ_HOOK, sub_payload, "allow")
tr = write("tool-results/x.txt", ["line %d" % i for i in range(10)])
case("tool-results from main -> deny", READ_HOOK, read_in(tr), "deny", "interval mai mic")
tr_sub = read_in(tr)
tr_sub["agent_id"] = "a-%s-tr" % RUN
tr_sub["agent_type"] = "implementer"
case("tool-results from sub-agent -> deny", READ_HOOK, tr_sub, "deny", "nu-l citi")

# ---------------------------------------------------------------- context-agent
sub_fixture("a-%s-main" % RUN, 100000)
case("main not affected by context-agent", CTX_HOOK,
     ctx_in("s-a-%s-main" % RUN), "allow")
ctx_case("explorer not affected", "expl", 230000, "allow", agent_type="explorer")
ctx_case("main 230k + agent 100k -> allow (regression 30.08)", "1", 100000, "allow")
ctx_case("160k -> warning", "2", 160000, "context", "Context >=150k")
ctx_case("160k warning only once", "2", 160000, "allow", reuse=True)
ctx_case("implementer-max warned too", "3", 160000, "context", "Context >=150k",
         agent_type="implementer-max")
ctx_case("implementer-sonnet 230k Edit -> deny", "4", 230000, "deny", "Context >=220k",
         agent_type="implementer-sonnet", tool_name="Edit")
ctx_case("scripter-complex 230k Edit -> deny", "4b", 230000, "deny", "Context >=220k",
         agent_type="scripter-complex", tool_name="Edit")
ctx_case("scripter 100k Edit -> allow", "4c", 100000, "allow",
         agent_type="scripter", tool_name="Edit")
ctx_case("230k Read -> deny", "5", 230000, "deny", "only Bash")
ctx_case("230k Bash -> allowed (warning first)", "6", 230000, "context",
         tool_name="Bash")
ctx_case("230k Bash after warning -> allow", "6", 230000, "allow",
         tool_name="Bash", reuse=True)

# missing worker transcript -> allow (never measure main)
case("agent transcript missing -> allow", CTX_HOOK,
     ctx_in("s-a-%s-1" % RUN, "a-%s-nofile" % RUN), "allow")

# verification counter
VER1 = ["npm run build", "node scripts/verifica-galerie.mjs"]
ctx_case("2nd verification -> allow", "v2", 90000, "allow", tool_name="Bash",
         command="npm run build", bash_cmds=VER1[:1])
ctx_case("3rd verification -> context", "v3", 90000, "context", "A 3-a verificare",
         tool_name="Bash", command="node scripts/verifica-x.mjs", bash_cmds=VER1)
ctx_case("4th verification -> allow (once)", "v3", 90000, "allow", tool_name="Bash",
         command="npx vitest run", reuse=True)
ctx_case("non-verification Bash not counted", "v4", 90000, "allow", tool_name="Bash",
         command="grep -rn foo src/", bash_cmds=VER1 + ["pytest -q"])
ctx_case("explorer verifications not counted", "v5", 90000, "allow", agent_type="explorer",
         tool_name="Bash", command="npm test", bash_cmds=VER1)

# log: one JSON line per trigger, with the AGENT's context (not main's 230k)
try:
    rows = [json.loads(l) for l in open("/tmp/claude-hooks/context-agent.jsonl")
            if RUN in l]
except OSError:
    rows = []
warn_rows = [r for r in rows if r.get("decision") == "warn"]
ok_log = (len(warn_rows) >= 2
          and all(set(r) >= {"ts", "agent_id", "agent_type", "ctx", "decision"} for r in rows)
          and any(r["decision"] == "verif3" for r in rows)
          and any(r["ctx"] == 100000 for r in rows))
results.append(("context-agent.jsonl logs agent ctx (%d rows)" % len(rows), ok_log,
                "%d rows" % len(rows)))

# ---------------------------------------------------------------- comentarii-cod
CMT_SESSION = "cmt-%s" % RUN
CMT_LOG = "/tmp/claude-hooks/comentarii-%s.jsonl" % CMT_SESSION

def cmt_in(path, old=None, new=None, content=None, tool="Edit", **kw):
    ti = {"file_path": path}
    if content is not None:
        ti["content"] = content
    else:
        ti["old_string"] = old or ""
        ti["new_string"] = new or ""
    d = {"session_id": CMT_SESSION, "cwd": TMP, "tool_name": tool,
         "tool_use_id": "cur", "tool_input": ti}
    d.update(kw)
    return d

CODE = os.path.join(TMP, "src.js")
BLOCK3 = "// prima\n// a doua\n// a treia\nconst a = 1;"
case("1 comment line -> allow", CMT_HOOK,
     cmt_in(CODE, old="const a = 1;", new="// una\nconst a = 1;"), "allow")
case("3-line block -> context", CMT_HOOK,
     cmt_in(CODE, old="const a = 1;", new=BLOCK3), "context", "3 lines")
case("moved comment -> allow", CMT_HOOK,
     cmt_in(CODE, old=BLOCK3, new="const a = 1;\n// prima\n// a doua\n// a treia"),
     "allow")
case("write untracked 3/8 comments -> context", CMT_HOOK,
     cmt_in(os.path.join(TMP, "nou.js"), tool="Write",
            content="const a = 1;\n// nota unu\n// nota doi\n// nota trei\n"
                    "const b = 2;\nconst c = 3;\nconst d = 4;\nconst e = 5;"),
     "context", "nou.js")
case("long comment line -> context", CMT_HOOK,
     cmt_in(CODE, old="const a = 1;", new="// " + ("x" * 200) + "\nconst a = 1;"),
     "context", "chars")
case(".md not code -> allow", CMT_HOOK,
     cmt_in(os.path.join(TMP, "note.md"), old="text", new=BLOCK3), "allow")
sub_cmt = cmt_in(CODE, old="const a = 1;", new=BLOCK3)
sub_cmt["agent_id"] = "a-%s-cmt" % RUN
sub_cmt["agent_type"] = "implementer"
case("sub-agent flagged too", CMT_HOOK, sub_cmt, "context", "3 lines")
case("300 KB Write payload -> context (no E2BIG)", CMT_HOOK,
     cmt_in(os.path.join(TMP, "huge.js"), tool="Write",
            content="// nota unu\n// nota doi\n" + "const a = 1;\n" * 25000),
     "context", "2 lines")
rc_bad, out_bad, err_bad = subprocess.run(
    ["bash", CMT_HOOK], input="not json at all", text=True,
    capture_output=True).returncode, "", ""
results.append(("invalid JSON -> exit 0", rc_bad == 0, "rc=%d" % rc_bad))
try:
    n_log = sum(1 for _ in open(CMT_LOG))
except OSError:
    n_log = 0
results.append(("log file has %d rows (>=3)" % n_log, n_log >= 3, "%d rows" % n_log))
try:
    os.remove(CMT_LOG)
except OSError:
    pass

# ---------------------------------------------------------------- timing (1 MB transcript)
def timed(hook, payload, n=3):
    best = 1e9
    for _ in range(n):
        t = time.time()
        call(hook, payload)
        best = min(best, (time.time() - t) * 1000)
    return best

t_aid = "a-%s-t" % RUN
MARKERS.append(t_aid)
t_sid = sub_fixture(t_aid, 230000, bash_cmds=["npm run build"], pad_lines=1100)
big_sub = os.path.join(TMP, "proj", t_sid, "subagents", "agent-%s.jsonl" % t_aid)
mb_main = os.path.getsize(big_main) / 1024.0 / 1024.0
mb_sub = os.path.getsize(big_sub) / 1024.0 / 1024.0
t_read = timed(READ_HOOK, read_in(big, transcript=big_main))
t_ctx = timed(CTX_HOOK, ctx_in(t_sid, t_aid, "implementer", "Bash", "npm run build"))
results.append(("read-mare < 200 ms on %.2f MB (%.0f ms)" % (mb_main, t_read),
                t_read < 200, "%.0f ms" % t_read))
results.append(("context-agent < 200 ms on %.2f MB (%.0f ms)" % (mb_sub, t_ctx),
                t_ctx < 200, "%.0f ms" % t_ctx))

# ---------------------------------------------------------------- report
for aid in MARKERS:
    for suf in ("150k", "seen", "verif3"):
        try:
            os.remove("/tmp/claude-hooks/%s.%s" % (aid, suf))
        except OSError:
            pass
try:
    keep = [l for l in open("/tmp/claude-hooks/context-agent.jsonl") if RUN not in l]
    with open("/tmp/claude-hooks/context-agent.jsonl", "w") as fh:
        fh.writelines(keep)
except OSError:
    pass
shutil.rmtree(TMP, ignore_errors=True)

failed = [r for r in results if not r[1]]
print("timing: read-mare %.0f ms / context-agent %.0f ms on ~1 MB transcripts"
      % (t_read, t_ctx))
for name, ok, got in results:
    if not ok:
        print("FAIL  %s -> %s" % (name, got))
print("%d/%d passed" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
PY
