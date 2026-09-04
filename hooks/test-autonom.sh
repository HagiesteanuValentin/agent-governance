#!/bin/bash
# 🔴 offline, synthetic marker dir in tmp, no Claude — docs/RETETE.md «Stare din transcript, nu din fișier (read-mare, test-hooks)»
set -u
HOOKS_DIR=$(cd "$(dirname "$0")" && pwd)
export HOOKS_DIR
# 🔴 HOOK=<cale> ca Brief 2 să ruleze aceleași cazuri pe copia live — DECIZII «Mod autonom (04.09.2026)»
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


# 1) start signal: "/handoff plec"
rc, out, err = prompt("s1", "/handoff plec")
case("'/handoff plec' -> marker + text MOD AUTONOM",
     rc == 0 and not err and os.path.exists(marker("s1"))
     and out.startswith("MOD AUTONOM pornit") and "ORCHESTRATION" in out,
     "rc=%d out=%r" % (rc, out[:60]))
case("REGULI has at most 8 lines", len(out.splitlines()) <= 8,
     "%d rânduri" % len(out.splitlines()))

# 2) "nesupravegheat" also starts it
rc, out, _ = prompt("s2", "rulează suitele, laptopul rămâne NESUPRAVEGHEAT")
case("'nesupravegheat' (caps) -> marker",
     rc == 0 and os.path.exists(marker("s2")) and "MOD AUTONOM pornit" in out, out[:40])

# 3) whole-word regex: "plecăm" does not match
rc, out, _ = prompt("s3", "plecăm mâine la mare")
case("'plecăm' -> no marker, no output",
     rc == 0 and not out and not os.path.exists(marker("s3")), "out=%r" % out)

# 4) prompt with no signal and no marker -> nothing
rc, out, _ = prompt("s4", "fă un grep prin hooks")
case("no signal, no marker -> no output",
     rc == 0 and not out and not os.path.exists(marker("s4")), "out=%r" % out)

# 5) gate with marker -> deny (AskUserQuestion)
got, body = gate("s1", "AskUserQuestion")
case("AskUserQuestion + marker -> deny",
     got == "deny" and "nu e la PC" in body and "nu reîncerca" in body,
     "%s %s" % (got, body))

# 6) gate with marker -> deny (EnterPlanMode)
got, body = gate("s1", "EnterPlanMode")
case("EnterPlanMode + marker -> deny",
     got == "deny" and "fără plan mode" in body and "nu reîncerca" in body,
     "%s %s" % (got, body))

# 7) gate without marker -> allow
got, body = gate("s4", "AskUserQuestion")
case("gate without marker -> no output", got == "allow", "%s %s" % (got, body))

# 8) any human prompt with no signal stops it
rc, out, _ = prompt("s1", "mersi, continuăm cu altceva")
case("no signal + existing marker -> marker removed + 'oprit'",
     rc == 0 and not os.path.exists(marker("s1")) and "MOD AUTONOM oprit" in out,
     "out=%r" % out)
got, _ = gate("s1", "AskUserQuestion")
case("after stop, gate lets it through", got == "allow", got)

# 9) negation is not covered: "nu plec încă" starts it (accepted, documented)
rc, out, _ = prompt("s5", "nu plec încă")
case("'nu plec încă' -> starts (negation not covered)",
     rc == 0 and os.path.exists(marker("s5")), "out=%r" % out[:40])

# 10) prompt coming from a sub-agent -> nothing
rc, out, _ = prompt("s6", "plec", {"agent_id": "a1"})
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

shutil.rmtree(TMP, ignore_errors=True)
failed = [r for r in results if not r[1]]
for name, ok, got in results:
    if not ok:
        print("FAIL  %s -> %s" % (name, got))
print("%d/%d passed" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
PY
