#!/bin/sh
# 🔴 effort live only via settings.json, reload-on-live unverified — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»

flag="$HOME/.claude/v17-effort-auto"
[ -f "$flag" ] || exit 0

mode="${1:-check}"
settings="$HOME/.claude/settings.json"
[ -f "$settings" ] || exit 0

in=$(cat 2>/dev/null)

# 🔴 PostToolUse fires in subagents too — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
agent_id=$(printf '%s' "$in" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('agent_id') or '')
except Exception:
    print('')
" 2>/dev/null)
[ -n "$agent_id" ] && exit 0

case "$mode" in
  low|medium)
    rm -f "${CLAUDE_JOB_DIR:-/tmp}"/effort-phase-* 2>/dev/null  # 🔴 phase switch re-arms the once-per-session WARN — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    python3 - "$settings" "$mode" <<'PY' "$in" 2>/dev/null
import json, os, sys, tempfile
try:
    settings_path, mode, stdin_json = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        old_effort = json.loads(stdin_json).get("effort", {}).get("level", "unknown")
    except Exception:
        old_effort = "unknown"
    with open(settings_path) as f:
        data = json.load(f)
    data.setdefault("modelSettings", {}).setdefault("claude-fable-5-1", {})["effortLevel"] = mode
    d = os.path.dirname(settings_path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, settings_path)
    ctx = "effort: settings->%s (was %s)" % (mode, old_effort)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": ctx}}))
except Exception:
    pass
PY
    ;;
  check)
    # 🔴 low/medium fire on this same tool call — check must not race the write — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    tool_name=$(printf '%s' "$in" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('tool_name') or '')
except Exception:
    print('')
" 2>/dev/null)
    case "$tool_name" in
      ExitPlanMode|EnterPlanMode) exit 0 ;;
    esac
    session_id=$(printf '%s' "$in" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('session_id', 'nosession'))
except Exception:
    print('nosession')
" 2>/dev/null)
    [ -n "$session_id" ] || session_id="nosession"
    state_dir="${CLAUDE_JOB_DIR:-/tmp}"
    mkdir -p "$state_dir" 2>/dev/null
    state="$state_dir/effort-phase-$session_id"
    [ -f "$state" ] && exit 0
    python3 - "$settings" "$state" <<'PY' "$in" 2>/dev/null
import json, sys
try:
    settings_path, state_path, stdin_json = sys.argv[1], sys.argv[2], sys.argv[3]
    eff = json.loads(stdin_json).get("effort", {}).get("level", "unknown")
    with open(settings_path) as f:
        data = json.load(f)
    want = data.get("modelSettings", {}).get("claude-fable-5-1", {}).get("effortLevel", "unknown")
    if eff != want:
        open(state_path, "w").close()
        ctx = "WARN effort effective=%s settings=%s -> You: /effort %s" % (eff, want, want)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                  "additionalContext": ctx}}))
except Exception:
    pass
PY
    ;;
esac
exit 0
