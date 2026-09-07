#!/bin/bash
# 🔴 offline, synthetic payloads, no network/Claude — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 fixtures don't depend on the model from settings — PATTERNS «The model inside hooks»
export GOV_MODEL=claude-fable-5-1
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile

HOOKS = os.environ["HOOKS_DIR"]
BASH_HOOK = os.path.join(HOOKS, "bash-mare.sh")
WRITE_HOOK = os.path.join(HOOKS, "write-mare.sh")
TMP = tempfile.mkdtemp(prefix="test-main-guards-")

def write(rel, lines):
    p = os.path.join(TMP, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return p

def body(n, txt="line %d"):
    return "\n".join(txt % i for i in range(n))

# ---------------------------------------------------------------- fixtures
big = write("big.txt", ["line %d" % i for i in range(400)])
small = write("small.txt", ["line %d" % i for i in range(100)])
plan = write("plan.md", ["line %d" % i for i in range(700)])
MAIN = write("proj/s1.jsonl", ["{}"])
SUBTP = write("proj/s1/subagents/agent-a1.jsonl", ["{}"])

def call(hook, payload):
    p = subprocess.run(["bash", hook], input=json.dumps(payload), text=True,
                       capture_output=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

_SID = [0]

def bash_in(command, agent_id=None):
    # 🔴 unique session per main test case, otherwise the nudge kicks in — PATTERNS «Bash batching»
    _SID[0] += 1
    d = {"session_id": "s1" if agent_id else "s1-%d" % _SID[0],
         "transcript_path": SUBTP if agent_id else MAIN, "cwd": TMP,
         "tool_name": "Bash", "tool_use_id": "cur", "tool_input": {"command": command}}
    if agent_id:
        d["agent_id"] = agent_id
    return d

def write_in(path, content=None, new_string=None, agent_id=None):
    ti = {"file_path": path}
    if content is not None:
        ti["content"] = content
        tool = "Write"
    else:
        ti["old_string"] = "x"
        ti["new_string"] = new_string or ""
        tool = "Edit"
    d = {"session_id": "s1", "transcript_path": SUBTP if agent_id else MAIN, "cwd": TMP,
         "tool_name": tool, "tool_use_id": "cur", "tool_input": ti}
    if agent_id:
        d["agent_id"] = agent_id
    return d

results = []
def case(name, hook, payload, expect, needle=""):
    rc, out, err = call(hook, payload)
    ok = rc == 0 and not err
    got, body_txt = "error", ""
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
                body_txt = h.get("permissionDecisionReason", "")
            else:
                got = "unknown"
                body_txt = out
        ok = got == expect and (not needle or got == "allow" or needle in body_txt)
    results.append((name, ok, "%s (rc=%d)%s" % (got, rc, " stderr: " + err if err else "")))

# ---------------------------------------------------------------- bash-mare: reads
case("cat 400 lines -> deny", BASH_HOOK, bash_in("cat %s" % big), "deny", ">300 lines in main")
case("cat 100 lines -> allow", BASH_HOOK, bash_in("cat %s" % small), "allow")
case("sed -n '1,40p' -> allow", BASH_HOOK, bash_in("sed -n '1,40p' %s" % big), "allow")
case("head -n 20 -> allow", BASH_HOOK, bash_in("head -n 20 %s" % big), "allow")
case("cat big | head -150 -> allow", BASH_HOOK, bash_in("cat %s | head -150" % big), "allow")
case("less on 400 lines -> deny", BASH_HOOK, bash_in("less %s" % big), "deny", "400 lines")
case("python3 -c open(big) -> deny", BASH_HOOK,
     bash_in("python3 -c \"print(open('%s').read())\"" % big), "deny", ">300 lines")
case("grep on 400 lines -> allow", BASH_HOOK, bash_in("grep -n foo %s" % big), "allow")
case("wc/jq/ls/git diff --stat -> allow", BASH_HOOK,
     bash_in("wc -l %s; ls %s; git diff --stat" % (big, TMP)), "allow")
case("sub-agent cat 400 lines -> allow", BASH_HOOK, bash_in("cat %s" % big, agent_id="a1"),
     "allow")

case("sed -i on 400 lines -> allow", BASH_HOOK, bash_in("sed -i 's/a/b/' %s" % big), "allow")
case("sed without -n on 400 lines -> allow", BASH_HOOK,
     bash_in("sed 's/a/b/' %s" % big), "allow")
case("sed -n 'p' on 400 lines -> deny", BASH_HOOK, bash_in("sed -n 'p' %s" % big),
     "deny", "400 lines")
case("tail -f on 400 lines -> allow", BASH_HOOK, bash_in("tail -f %s" % big), "allow")
case("tail -F on 400 lines -> allow", BASH_HOOK, bash_in("tail -F %s" % big), "allow")
case("awk '{print}' on 400 lines -> deny", BASH_HOOK,
     bash_in("awk '{print}' %s" % big), "deny", "400 lines")
case("awk NR range -> allow", BASH_HOOK,
     bash_in("awk 'NR>=10 && NR<=60' %s" % big), "allow")
case("awk piped into head -> allow", BASH_HOOK,
     bash_in("awk '{print}' %s | head -50" % big), "allow")
case("awk -i inplace -> allow", BASH_HOOK,
     bash_in("awk -i inplace '{print}' %s" % big), "allow")
case("perl -ne on 400 lines -> deny", BASH_HOOK,
     bash_in("perl -ne 'print' %s" % big), "deny", "400 lines")
case("perl -pe on 400 lines -> deny", BASH_HOOK,
     bash_in("perl -pe 's/a/b/' %s" % big), "deny", "400 lines")
case("perl -i -pe in place -> allow", BASH_HOOK,
     bash_in("perl -i -pe 's/a/b/' %s" % big), "allow")
case("perl -e without -n/-p -> allow", BASH_HOOK,
     bash_in("perl -e 'print 1' %s" % big), "allow")
case("perl -ne piped into sed range -> allow", BASH_HOOK,
     bash_in("perl -ne 'print' %s | sed -n '1,5p'" % big), "allow")

# ---------------------------------------------------------------- bash-mare: heredocs
HD30 = "cat > src/x.astro <<'EOF'\n%s\nEOF" % body(30)
case("heredoc 30 lines into src/x.astro -> deny", BASH_HOOK, bash_in(HD30), "deny",
     ">20 lines from main")
HD10 = "cat > src/x.astro <<'EOF'\n%s\nEOF" % body(10)
case("heredoc 10 lines into src/x.astro -> allow", BASH_HOOK, bash_in(HD10), "allow")
case("heredoc 30 lines into /tmp brief -> allow", BASH_HOOK,
     bash_in("cat > /tmp/brief-1.md <<'EOF'\n%s\nEOF" % body(30)), "allow")
case("tee 30 lines into project -> deny", BASH_HOOK,
     bash_in("tee docs/x.md <<'EOF'\n%s\nEOF" % body(30)), "deny", ">20 lines from main")
case("python3 - heredoc writing project file -> deny", BASH_HOOK,
     bash_in("python3 - <<'PY'\nopen('docs/x.md','w').write('''%s''')\nPY" % body(30)),
     "deny", ">20 lines from main")
case("python3 - heredoc reading only -> allow", BASH_HOOK,
     bash_in("python3 - <<'PY'\n%s\nPY" % body(30)), "allow")
case("sed range into /tmp/brief-1.md -> allow", BASH_HOOK,
     bash_in("sed -n '10,60p' %s > /tmp/brief-1.md" % plan), "allow")

# ---------------------------------------------------------------- write-mare
case("Write 30 lines in docs/x.md -> deny", WRITE_HOOK,
     write_in(os.path.join(TMP, "docs/x.md"), content=body(30)), "deny", ">20 lines from main")
case("Write 30 lines in ~/.claude/plans -> allow", WRITE_HOOK,
     write_in(os.path.join(TMP, "fakehome/.claude/plans/x.md"), content=body(30)), "allow")
case("Write 30 lines in memory/ -> allow", WRITE_HOOK,
     write_in(os.path.join(TMP, "fakehome/memory/MEMORY.md"), content=body(30)), "allow")
case("Write 30 lines in HANDOFF.md -> deny", WRITE_HOOK,
     write_in(os.path.join(TMP, "HANDOFF.md"), content=body(30)), "deny", ">20 lines from main")
case("Edit new_string 8 lines -> allow", WRITE_HOOK,
     write_in(os.path.join(TMP, "docs/x.md"), new_string=body(8)), "allow")
case("Edit new_string 30 lines -> deny", WRITE_HOOK,
     write_in(os.path.join(TMP, "docs/x.md"), new_string=body(30)), "deny", "30 lines here")
case("sub-agent Write 50 lines -> allow", WRITE_HOOK,
     write_in(os.path.join(TMP, "docs/x.md"), content=body(50), agent_id="a1"), "allow")

# ---------------------------------------------------------------- fail-open
for hook, label in ((BASH_HOOK, "bash-mare"), (WRITE_HOOK, "write-mare")):
    p = subprocess.run(["bash", hook], input="not json", text=True, capture_output=True)
    results.append(("%s invalid JSON -> exit 0" % label, p.returncode == 0 and not p.stdout,
                    "rc=%d" % p.returncode))

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
