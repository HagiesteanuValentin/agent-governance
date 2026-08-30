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
SUB = {}
for k in (100000, 160000, 230000):
    SUB[k] = jsonl("sub%d.jsonl" % k, [
        {"type": "user", "message": {"role": "user", "content": "brief"}},
        usage_line(k)])

# 1 MB transcripts for the timing check
pad = "x" * 900
big_main = jsonl("big-main.jsonl",
                 [{"type": "user", "message": {"role": "user", "content": pad}}] * 1100
                 + [assistant([read_use("r1", small)])])
big_sub = jsonl("big-sub.jsonl",
                [{"type": "user", "message": {"role": "user", "content": pad}}] * 1100
                + [usage_line(230000)])

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

def ctx_in(transcript, agent_id=None, agent_type="implementer", tool_name="Read"):
    d = {"session_id": "s1", "transcript_path": transcript, "cwd": TMP,
         "tool_name": tool_name, "tool_use_id": "cur", "tool_input": {}}
    if agent_id:
        d["agent_id"] = agent_id
        d["agent_type"] = agent_type
        MARKERS.append(agent_id)
    return d

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

# ---------------------------------------------------------------- context-agent
case("main not affected by context-agent", CTX_HOOK, ctx_in(SUB[230000]), "allow")
case("explorer not affected", CTX_HOOK,
     ctx_in(SUB[230000], "a-%s-expl" % RUN, "explorer"), "allow")
case("100k -> allow", CTX_HOOK, ctx_in(SUB[100000], "a-%s-1" % RUN), "allow")
case("160k -> warning", CTX_HOOK, ctx_in(SUB[160000], "a-%s-2" % RUN), "context",
     "Context >=150k")
case("160k warning only once", CTX_HOOK, ctx_in(SUB[160000], "a-%s-2" % RUN), "allow")
case("implementer-max warned too", CTX_HOOK,
     ctx_in(SUB[160000], "a-%s-3" % RUN, "implementer-max"), "context", "Context >=150k")
case("implementer-sonnet 230k Edit -> deny", CTX_HOOK,
     ctx_in(SUB[230000], "a-%s-4" % RUN, "implementer-sonnet", "Edit"), "deny",
     "Context >=220k")
case("scripter-complex 230k Edit -> deny", CTX_HOOK,
     ctx_in(SUB[230000], "a-%s-4b" % RUN, "scripter-complex", "Edit"), "deny",
     "Context >=220k")
case("scripter 100k Edit -> allow", CTX_HOOK,
     ctx_in(SUB[100000], "a-%s-4c" % RUN, "scripter", "Edit"), "allow")
case("230k Read -> deny", CTX_HOOK,
     ctx_in(SUB[230000], "a-%s-5" % RUN, "implementer", "Read"), "deny", "only Bash")
case("230k Bash -> allowed (warning first)", CTX_HOOK,
     ctx_in(SUB[230000], "a-%s-6" % RUN, "implementer", "Bash"), "context")
case("230k Bash after warning -> allow", CTX_HOOK,
     ctx_in(SUB[230000], "a-%s-6" % RUN, "implementer", "Bash"), "allow")

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

mb_main = os.path.getsize(big_main) / 1024.0 / 1024.0
mb_sub = os.path.getsize(big_sub) / 1024.0 / 1024.0
t_read = timed(READ_HOOK, read_in(big, transcript=big_main))
t_ctx = timed(CTX_HOOK, ctx_in(big_sub, "a-%s-t" % RUN, "implementer", "Bash"))
results.append(("read-mare < 300 ms on %.2f MB (%.0f ms)" % (mb_main, t_read),
                t_read < 300, "%.0f ms" % t_read))
results.append(("context-agent < 300 ms on %.2f MB (%.0f ms)" % (mb_sub, t_ctx),
                t_ctx < 300, "%.0f ms" % t_ctx))

# ---------------------------------------------------------------- report
for aid in MARKERS:
    for f in ("/tmp/claude-hooks/%s.150k" % aid,):
        try:
            os.remove(f)
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
