#!/bin/bash
# 🔴 autonom-<sid> marker per session, fail-open — docs/DECIZII.md «Mod autonom (04.09.2026)»
MODE=${1:-prompt}
MARKER_DIR=${CLAUDE_HOOKS_DIR:-/tmp/claude-hooks}
input=$(cat)
python3 - "$input" "$MODE" "$MARKER_DIR" <<'PY' || exit 0
import json, os, re, sys

try:
    d = json.loads(sys.argv[1])
except ValueError:
    sys.exit(0)
MODE, MARKER_DIR = sys.argv[2], sys.argv[3]

REGULI = (
    "AUTONOMOUS MODE started (any new message stops it).\n"
    "The user is stepping away. AUTONOMOUS MODE OVERRIDES ORCHESTRATION «Flow» "
    "(plan approved by the user) and «Over the cap» (AskUserQuestion).\n"
    "No questions, no plan mode; a denied tool is not retried.\n"
    "Over any cap, pick the conservative option and note it in the final report.\n"
    "If you're in plan mode now: ExitPlanMode immediately, while the user is still here.\n"
    "At the end do what was asked (handoff/commit/push, if requested) and close "
    "the turn without waiting.\n"
    "Push rejected: report it, don't insist."
)

# 🔴 the hook's own name is excluded from signals: it would match any prompt about this hook — DECIZII «Mod autonom (04.09.2026)»
SEMNAL = re.compile(r"\b(plec|nesupravegheat|leaving|unsupervised)\b", re.IGNORECASE)

session_id = str(d.get("session_id") or "")
if not session_id:
    sys.exit(0)
safe_sid = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
MARKER = os.path.join(MARKER_DIR, "autonom-%s" % safe_sid)

if MODE == "prompt":
    if d.get("agent_id"):
        sys.exit(0)
    prompt = str(d.get("prompt") or "")
    if SEMNAL.search(prompt):
        try:
            os.makedirs(MARKER_DIR, exist_ok=True)
            with open(MARKER, "w") as fh:
                fh.write("1\n")
        except OSError:
            sys.exit(0)
        # 🔴 UserPromptSubmit stdout goes into context; exit 2 would erase the prompt — DECIZII «Mod autonom (04.09.2026)»
        print(REGULI)
        sys.exit(0)
    if os.path.exists(MARKER):
        try:
            os.remove(MARKER)
        except OSError:
            pass
        print("AUTONOMOUS MODE stopped (human message without a signal).")
    sys.exit(0)

# ---- gate (PreToolUse: AskUserQuestion|EnterPlanMode)
if not os.path.exists(MARKER):
    sys.exit(0)
COADA = " Overrides ORCHESTRATION; don't retry."
if (d.get("tool_name") or "") == "EnterPlanMode":
    reason = "autonomous mode: no plan mode; write the plan to a file and execute directly."
else:
    reason = ("autonomous mode (the user is away): pick the recommended/conservative "
              "option yourself, write it in the report, continue.")
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": reason + COADA}}))
sys.exit(0)
PY
