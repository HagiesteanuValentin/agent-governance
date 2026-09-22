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

# 🔴 /polish and /refine hold medium across ExitPlanMode — PATTERNS «effort hold for /polish and /refine»
if [ "$mode" != check ] && [ "$mode" != gate ]; then
  meta=$(printf '%s' "$in" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('%s %s %s' % (d.get('session_id') or '-', d.get('tool_name') or '-', d.get('hook_event_name') or '-'))
except Exception:
    print('- - -')
" 2>/dev/null)
  set -- $meta
  h_sid="${1:--}"; h_tool="${2:--}"; h_event="${3:--}"
  if [ "$h_sid" = "-" ]; then
    h_sid=""
    env_sid="${CLAUDE_CODE_SESSION_ID:-}"
    hold="${CLAUDE_JOB_DIR:-/tmp}/effort-hold-$env_sid"
    if [ -n "$env_sid" ]; then
      if [ "$mode" = hold ]; then
        h_sid="$env_sid"
      elif [ "$mode" = low ] && [ -f "$hold" ]; then
        h_sid="$env_sid"; rm -f "$hold" 2>/dev/null
      fi
    fi
  else
    hold="${CLAUDE_JOB_DIR:-/tmp}/effort-hold-$h_sid"
    if [ "$h_event" = SessionEnd ]; then
      rm -f "$hold" 2>/dev/null
    elif [ "$mode" = low ] && [ "$h_tool" = ExitPlanMode ] && [ -f "$hold" ]; then
      exit 0
    fi
  fi
fi

case "$mode" in
  hold)
    [ -n "$h_sid" ] || exit 0
    mkdir -p "${CLAUDE_JOB_DIR:-/tmp}" 2>/dev/null
    : > "$hold" 2>/dev/null
    ;;
  low|medium)
    rm -f "${CLAUDE_JOB_DIR:-/tmp}"/effort-phase-* 2>/dev/null  # 🔴 phase switch re-arms the once-per-session WARN — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    python3 - "$settings" "$mode" "${CLAUDE_JOB_DIR:-/tmp}" <<'PY' "$in" "${h_sid:-}" 2>/dev/null
import json, os, sys, tempfile
try:
    settings_path, mode, state_dir, stdin_json = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    # 🔴 gate target is per session, settings is shared by all sessions — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    try:
        sid = json.loads(stdin_json).get("session_id") or ""
    except Exception:
        sid = ""
    sid = sid or (sys.argv[5] if len(sys.argv) > 5 else "")
    if sid:
        try:
            os.makedirs(state_dir, exist_ok=True)
            with open(os.path.join(state_dir, "effort-target-%s" % sid), "w") as f:
                f.write(mode)
        except Exception:
            pass
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
  gate)
    python3 - "$settings" "${CLAUDE_JOB_DIR:-/tmp}" "${CLAUDE_EFFORT:-}" <<'PY' "$in" 2>/dev/null
import json, os, sys
try:
    settings_path, state_dir, env_effort, stdin_json = sys.argv[1:5]
    data_in = json.loads(stdin_json)
    tool = data_in.get("tool_name") or ""
    # 🔴 the gate must not deny the tools that let the user answer — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    if tool in ("ExitPlanMode", "EnterPlanMode", "AskUserQuestion"):
        sys.exit(0)
    eff = data_in.get("effort", {}).get("level") or env_effort or ""
    if not eff:
        sys.exit(0)
    want = ""
    sid = data_in.get("session_id") or ""
    if sid:
        try:
            with open(os.path.join(state_dir, "effort-target-%s" % sid)) as f:
                want = f.read().strip()
        except OSError:
            want = ""
    if not want:
        with open(settings_path) as f:
            want = json.load(f).get("modelSettings", {}).get(
                "claude-fable-5-1", {}).get("effortLevel", "")
    if not want or eff == want:
        sys.exit(0)
    reason = ("STOP: effort effective=%s, settings=%s. Write ONE line to the user: "
              "«Tu: /effort %s, apoi scrie go» and end the turn. "
              "Do not retry tools." % (eff, want, want))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
except SystemExit:
    raise
except Exception:
    pass
PY
    ;;
esac
exit 0
