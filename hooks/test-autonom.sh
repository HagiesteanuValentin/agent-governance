#!/bin/bash
# 🔴 offline, synthetic marker dir in tmp, no Claude — docs/RECIPES.md «State from the transcript, not from a file (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 HOOK=<path> so Brief 2 can run the same cases against the live copy — DECIZII «Mod autonom (04.09.2026)»
export HOOK=${HOOK:-$HOOKS_DIR/autonom.sh}
python3 - <<'PY'
import json, os, shutil, subprocess, sys, tempfile

HOOK = os.environ["HOOK"]
TMP = tempfile.mkdtemp(prefix="test-autonom-")
STATE_DIR = os.path.join(TMP, "hooks")
ENV = dict(os.environ, CLAUDE_HOOKS_DIR=STATE_DIR)

results = []


def case(name, ok, got):
    results.append((name, ok, got))


def marker(sid):
    return os.path.join(STATE_DIR, "autonom-%s" % sid)


def call(mode, payload, raw=None):
    p = subprocess.run(["bash", HOOK, mode],
                       input=raw if raw is not None else json.dumps(payload),
                       text=True, capture_output=True, env=ENV)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def started(out):
    return "AUTONOMOUS MODE started" in out or "MOD AUTONOM pornit" in out


def stopped(out):
    return "AUTONOMOUS MODE stopped" in out or "MOD AUTONOM oprit" in out


def any_of(body, *parts):
    return any(p in body for p in parts)


def prompt(sid, text, extra=None):
    d = {"session_id": sid, "prompt": text}
    if extra:
        d.update(extra)
    return call("prompt", d)


def gate(sid, tool):
    rc, out, err = call("gate", {"session_id": sid, "tool_name": tool, "tool_input": {}})
    if rc != 0 or err:
        return "error", "rc=%d %s" % (rc, err)
    if not out:
        return "allow", ""
    try:
        h = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return "unknown", out
    return h.get("permissionDecision") or "unknown", h.get("permissionDecisionReason", "")


# 1) start signal: "/handoff leaving"
rc, out, err = prompt("s1", "/handoff leaving")
case("'/handoff leaving' -> marker + text AUTONOMOUS MODE",
     rc == 0 and not err and os.path.exists(marker("s1"))
     and started(out) and "ORCHESTRATION" in out,
     "rc=%d out=%r" % (rc, out[:60]))
case("REGULI has at most 9 lines", len(out.splitlines()) <= 9,
     "%d lines" % len(out.splitlines()))

# 2) "unsupervised" also starts it
rc, out, _ = prompt("s2", "run the suites, the laptop stays UNSUPERVISED")
case("'unsupervised' (caps) -> marker",
     rc == 0 and os.path.exists(marker("s2")) and started(out), out[:40])

# 2b) Romanian signal: "plec" also starts it
rc, out, _ = prompt("s2b", "ma duc, plec de aici")
case("'plec' (RO) -> marker",
     rc == 0 and os.path.exists(marker("s2b")) and started(out), out[:40])

# 3) whole-word regex: "leavings" does not match
rc, out, _ = prompt("s3", "leavings scattered on the shore")
case("'leavings' -> no marker, no output",
     rc == 0 and not out and not os.path.exists(marker("s3")), "out=%r" % out)

# 4) prompt with no signal and no marker -> nothing
rc, out, _ = prompt("s4", "run a grep through hooks")
case("no signal, no marker -> no output",
     rc == 0 and not out and not os.path.exists(marker("s4")), "out=%r" % out)

# 5) gate with marker -> deny (AskUserQuestion)
got, body = gate("s1", "AskUserQuestion")
case("AskUserQuestion + marker -> deny",
     got == "deny" and any_of(body, "the user is away", "Vali nu e la PC")
     and any_of(body, "don't retry", "nu reîncerca"),
     "%s %s" % (got, body))

# 6) gate with marker -> deny (EnterPlanMode)
got, body = gate("s1", "EnterPlanMode")
case("EnterPlanMode + marker -> deny",
     got == "deny" and any_of(body, "no plan mode", "fără plan mode")
     and any_of(body, "don't retry", "nu reîncerca"),
     "%s %s" % (got, body))

# 7) gate without marker -> allow
got, body = gate("s4", "AskUserQuestion")
case("gate without marker -> no output", got == "allow", "%s %s" % (got, body))

# 8) any human prompt with no signal stops it
rc, out, _ = prompt("s1", "thanks, let's move to something else")
case("no signal + existing marker -> marker removed + 'stopped'",
     rc == 0 and not os.path.exists(marker("s1")) and stopped(out),
     "out=%r" % out)
got, _ = gate("s1", "AskUserQuestion")
case("after stop, gate lets it through", got == "allow", got)

# 9) negation is not covered: "not leaving yet" starts it (accepted, documented)
rc, out, _ = prompt("s5", "not leaving yet")
case("'not leaving yet' -> starts (negation not covered)",
     rc == 0 and os.path.exists(marker("s5")), "out=%r" % out[:40])

# 10) prompt coming from a sub-agent -> nothing
rc, out, _ = prompt("s6", "leaving", {"agent_id": "a1"})
case("prompt with agent_id -> no marker, no output",
     rc == 0 and not out and not os.path.exists(marker("s6")), "out=%r" % out)

# 11) fail-open on broken JSON / missing session_id
rc, out, err = call("prompt", None, raw="not json")
case("invalid JSON -> exit 0, no output", rc == 0 and not out, "rc=%d out=%r" % (rc, out))
rc, out, _ = call("gate", {"tool_name": "AskUserQuestion"})
case("gate without session_id -> exit 0", rc == 0 and not out, "rc=%d" % rc)

# 12) marker is per session: s2 stays on while s1 is off
got, _ = gate("s2", "AskUserQuestion")
case("marker per session", got == "deny", got)

# 13) task-notification hand-back without signal -> marker stays, no output
prompt("s7", "leaving")
rc, out, _ = prompt("s7", "<task-notification><result>no signal here</result></task-notification>")
case("task-notification with marker -> marker stays, no output",
     rc == 0 and not out and os.path.exists(marker("s7")), "out=%r" % out)

# 14) task-notification quoting the signal -> no marker
rc, out, _ = prompt("s8", "<task-notification><result>regex plec|nesupravegheat</result></task-notification>")
case("task-notification with signal -> no marker, no output",
     rc == 0 and not out and not os.path.exists(marker("s8")), "out=%r" % out)

# 15) uppercase MOD AUTONOM starts it
rc, out, _ = prompt("s9", "MOD AUTONOM")
case("'MOD AUTONOM' -> starts", rc == 0 and os.path.exists(marker("s9")) and started(out), out[:40])

# 16) lowercase / 'modul autonom' does not start it
rc, out, _ = prompt("s10", "mod autonom")
rc2, out2, _ = prompt("s10", "modul autonom e stricat")
case("'mod autonom' / 'modul autonom' -> no start",
     not out and not out2 and not os.path.exists(marker("s10")), "out=%r %r" % (out, out2))

# 17) origin.kind == task-notification without tag -> ignored
prompt("s11", "leaving")
rc, out, _ = prompt("s11", "plain text", {"origin": {"kind": "task-notification"}})
case("origin.kind task-notification -> ignored",
     rc == 0 and not out and os.path.exists(marker("s11")), "out=%r" % out)

# 18) human prompt mentioning the tag mid-text -> starts
rc, out, _ = prompt("s12", "plec, hook-ul rulează pe <task-notification>")
case("tag mid-text + signal -> starts",
     rc == 0 and os.path.exists(marker("s12")) and started(out), out[:40])

# 19) origin as a string -> no crash, normal behaviour
rc, out, err = prompt("s13", "leaving", {"origin": "x"})
case("origin string -> normal start",
     rc == 0 and not err and os.path.exists(marker("s13")) and started(out), "err=%r" % err)

shutil.rmtree(TMP, ignore_errors=True)
failed = [r for r in results if not r[1]]
for name, ok, got in results:
    if not ok:
        print("FAIL  %s -> %s" % (name, got))
print("%d/%d passed" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
PY
