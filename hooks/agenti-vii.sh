#!/bin/bash
# 🔴 state file per session, fail-open — docs/DECIZII.md «v1.6 — hook-uri pentru orchestrator (02.09.2026)»
MODE=${1:-check}
CAP=${AGENTI_VII_CAP:-6}
STALE_SEC=${AGENTI_VII_STALE:-300}
MARKER_DIR=${CLAUDE_HOOKS_DIR:-/tmp/claude-hooks}
input=$(cat)
python3 - "$input" "$MODE" "$CAP" "$STALE_SEC" "$MARKER_DIR" "$(dirname "$0")" <<'PY' || exit 0
import json, os, subprocess, sys, time

try:
    d = json.loads(sys.argv[1])
except ValueError:
    sys.exit(0)
MODE, CAP, STALE, MARKER_DIR = sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]

session_id = d.get("session_id") or ""
if not session_id:
    sys.exit(0)
safe_sid = "".join(c if c.isalnum() or c in "._-" else "_" for c in session_id)
STATE = os.path.join(MARKER_DIR, "live-%s" % safe_sid)


def read_rows():
    rows = []
    try:
        with open(STATE, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3 or not parts[0]:
                    continue
                try:
                    ts = int(float(parts[2]))
                except ValueError:
                    continue
                rows.append([parts[0], parts[1], ts])
    except OSError:
        pass
    return rows


def write_rows(rows):
    try:
        os.makedirs(MARKER_DIR, exist_ok=True)
        tmp = STATE + ".tmp%d" % os.getpid()
        with open(tmp, "w") as fh:
            for r in rows:
                fh.write("%s\t%s\t%d\n" % (r[0], r[1], r[2]))
        os.replace(tmp, STATE)
    except OSError:
        pass


def agent_jsonl(agent_id):
    tp = d.get("transcript_path") or ""
    if not tp:
        return None
    # 🔴 in a sub-agent, transcript_path is the MAIN transcript — DECIZII «v1.4.1 — 30.08.2026»
    return os.path.join(os.path.dirname(tp), session_id, "subagents",
                        "agent-%s.jsonl" % agent_id)


def alive(row, now):
    """mtime of the agent's own jsonl; falls back to the row's write time."""
    p = agent_jsonl(row[0])
    ts = row[2]
    if p:
        try:
            ts = max(ts, int(os.path.getmtime(p)))
        except OSError:
            pass
    return now - ts <= STALE


now = int(time.time())

if MODE == "start":
    aid = d.get("agent_id")
    if not aid:
        sys.exit(0)
    rows = [r for r in read_rows() if r[0] != aid]
    rows.append([str(aid), str(d.get("agent_type") or "?"), now])
    write_rows(rows)
    sys.exit(0)

if MODE == "stop":
    aid = d.get("agent_id")
    if not aid:
        sys.exit(0)
    rows = read_rows()
    kept = [r for r in rows if r[0] != aid]
    if len(kept) != len(rows):
        write_rows(kept)
    sys.exit(0)

# ---- check (PreToolUse/Agent in main)
# 🔴 model guard, main only — PATTERNS «The model inside hooks»
_m = subprocess.run(["bash", os.path.join(sys.argv[6], "main-model.sh"),
                     d.get("transcript_path") or ""],
                    capture_output=True, text=True).stdout.strip().lower()
if not ("fable" in _m or "mythos" in _m or _m in ("", "unknown")):
    sys.exit(0)
# 🔴 autonom-<sid> marker = no ask — docs/DECIZII.md «Mod autonom (04.09.2026)»
if os.path.exists(os.path.join(MARKER_DIR, "autonom-%s" % safe_sid)):
    sys.exit(0)
rows = read_rows()
if not rows:
    sys.exit(0)
live = [r for r in rows if alive(r, now)]
if len(live) != len(rows):
    write_rows(live)
if len(live) < CAP:
    sys.exit(0)
lista = ", ".join("%s/%s" % (r[1], r[0]) for r in live)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason":
        "%d live agents (%s); over the cap — approval" % (len(live), lista)}}))
sys.exit(0)
PY
