#!/bin/bash
# 🔴 marker autonom-<sid> per session, fail-open — docs/DECIZII.md «Mod autonom (04.09.2026)»
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
    "MOD AUTONOM pornit (orice mesaj nou îl oprește).\n"
    "Vali pleacă de la PC. MODUL AUTONOM PREVALEAZĂ asupra ORCHESTRATION «Flux» "
    "(plan aprobat de Vali) și «Peste plafon» (AskUserQuestion).\n"
    "Nicio întrebare, niciun plan mode; tool-ul refuzat nu se reîncearcă.\n"
    "Peste plafoane alegi varianta conservatoare și o notezi în raportul de final.\n"
    "Dacă ești în plan mode acum: ExitPlanMode imediat, cât Vali e încă aici.\n"
    "La capăt faci ce s-a cerut (handoff/commit/push, dacă au fost cerute) și închei "
    "tura fără să aștepți.\n"
    "Push respins: raportezi, nu insiști."
)

# 🔴 „autonom" lipsește din semnale: s-ar potrivi pe orice prompt despre acest hook — DECIZII «Mod autonom (04.09.2026)»
SEMNAL = re.compile(r"\b(plec|nesupravegheat)\b", re.IGNORECASE)

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
        # 🔴 stdout de UserPromptSubmit intră în context; exit 2 ar șterge prompt-ul — DECIZII «Mod autonom (04.09.2026)»
        print(REGULI)
        sys.exit(0)
    if os.path.exists(MARKER):
        try:
            os.remove(MARKER)
        except OSError:
            pass
        print("MOD AUTONOM oprit (mesaj uman fără semnal).")
    sys.exit(0)

# ---- gate (PreToolUse: AskUserQuestion|EnterPlanMode)
if not os.path.exists(MARKER):
    sys.exit(0)
COADA = " Prevalează asupra ORCHESTRATION; nu reîncerca."
if (d.get("tool_name") or "") == "EnterPlanMode":
    reason = "mod autonom: fără plan mode; scrii planul în fișier și execuți direct."
else:
    reason = ("mod autonom (Vali nu e la PC): alegi singur opțiunea "
              "recomandată/conservatoare, o scrii în raport, continui.")
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": reason + COADA}}))
sys.exit(0)
PY
