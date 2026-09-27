#!/bin/sh
# 🔴 never write the user settings file — PATTERNS «Effort hook is per-session only»

flag="$HOME/.claude/v17-effort-auto"
[ -f "$flag" ] || exit 0

mode="${1:-check}"
state_dir="${CLAUDE_JOB_DIR:-/tmp}"

in=$(cat 2>/dev/null)

# 🔴 PostToolUse fires in subagents too — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
meta=$(printf '%s' "$in" | python3 -c "
import json, re, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
if not isinstance(d, dict):
    d = {}
sid = re.sub(r'[^A-Za-z0-9_.-]', '_', str(d.get('session_id') or ''))
eff = (d.get('effort') or {}).get('level') if isinstance(d.get('effort'), dict) else ''
src = re.sub(r'[^A-Za-z0-9_]', '', str(d.get('source') or ''))
print('%s %s %s %s %s %s' % (sid or '-', d.get('tool_name') or '-', d.get('hook_event_name') or '-',
                             eff or '-', 'A' if d.get('agent_id') else '-', src or '-'))
" 2>/dev/null)
set -- $meta
h_sid="${1:--}"; h_tool="${2:--}"; h_event="${3:--}"; h_eff="${4:--}"; h_agent="${5:--}"; h_src="${6:--}"
[ "$h_agent" = "-" ] || exit 0
[ "$h_eff" = "-" ] && h_eff=""

# 🔴 /polish and /refine hold medium across ExitPlanMode — PATTERNS «effort hold for /polish and /refine»
if [ "$mode" != check ] && [ "$mode" != gate ]; then
  if [ "$h_sid" = "-" ]; then
    h_sid=""
    env_sid=$(printf '%s' "${CLAUDE_CODE_SESSION_ID:-}" | sed 's/[^A-Za-z0-9_.-]/_/g')
    hold="$state_dir/effort-hold-$env_sid"
    if [ -n "$env_sid" ]; then
      if [ "$mode" = hold ]; then
        h_sid="$env_sid"
      elif [ "$mode" = low ] && [ -f "$hold" ]; then
        h_sid="$env_sid"; rm -f "$hold" 2>/dev/null
      fi
    fi
  else
    hold="$state_dir/effort-hold-$h_sid"
    if [ "$h_event" = SessionEnd ]; then
      rm -f "$hold" 2>/dev/null
    elif [ "$mode" = low ] && [ "$h_tool" = ExitPlanMode ] && [ -f "$hold" ]; then
      exit 0
    fi
  fi
else
  [ "$h_sid" = "-" ] && h_sid=""
fi

case "$mode" in
  hold)
    [ -n "$h_sid" ] || exit 0
    mkdir -p "$state_dir" 2>/dev/null
    : > "$hold" 2>/dev/null
    ;;
  low|medium)
    [ -n "$h_sid" ] || exit 0
    mkdir -p "$state_dir" 2>/dev/null
    rm -f "$state_dir/effort-phase-$h_sid" 2>/dev/null  # 🔴 phase switch re-arms the once-per-session WARN — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    printf '%s\n' "$mode" > "$state_dir/effort-target-$h_sid" 2>/dev/null
    if [ -n "$h_eff" ] && [ "$h_eff" != "$mode" ]; then
      printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"Tu: /effort %s, apoi scrie go (effective=%s)"}}\n' "$mode" "$h_eff"
    fi
    ;;
  check)
    # 🔴 low/medium fire on this same tool call — check must not race the write — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    case "$h_tool" in
      ExitPlanMode|EnterPlanMode) exit 0 ;;
    esac
    [ -n "$h_sid" ] && [ -n "$h_eff" ] || exit 0
    tgt="$state_dir/effort-target-$h_sid"
    [ -f "$tgt" ] || exit 0
    want=$(head -n1 "$tgt" 2>/dev/null)
    state="$state_dir/effort-phase-$h_sid"
    [ -f "$state" ] && exit 0
    if [ -n "$want" ] && [ "$h_eff" != "$want" ]; then
      : > "$state" 2>/dev/null
      printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"WARN effort effective=%s target=%s -> Tu: /effort %s"}}\n' "$h_eff" "$want" "$want"
    fi
    ;;
  gate)
    python3 - "$state_dir" "${CLAUDE_EFFORT:-}" <<'PY' "$in" 2>/dev/null
import json, os, re, sys
try:
    state_dir, env_effort, stdin_json = sys.argv[1:4]
    data_in = json.loads(stdin_json)
    tool = data_in.get("tool_name") or ""
    # 🔴 the gate must not deny the tools that let the user answer — PATTERNS «Claude Code — limits verified in docs (2026-09-02)»
    if tool in ("ExitPlanMode", "EnterPlanMode", "AskUserQuestion"):
        sys.exit(0)
    eff = data_in.get("effort", {}).get("level") or env_effort or ""
    if not eff:
        sys.exit(0)
    want = ""
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(data_in.get("session_id") or ""))
    if sid:
        try:
            with open(os.path.join(state_dir, "effort-target-%s" % sid)) as f:
                want = f.read().strip()
        except OSError:
            want = ""
    if not want or eff == want:
        sys.exit(0)
    # 🔴 a user /effort becomes the target (not in plan mode) — DECIZII «v1.13 — /effort al utilizatorului e țintă»
    tp = data_in.get("transcript_path") or ""
    if sid and tp and data_in.get("permission_mode") != "plan":
        from datetime import datetime
        tgt = os.path.join(state_dir, "effort-target-%s" % sid)
        def ts(e):
            try:
                return datetime.fromisoformat(str(e.get("timestamp")).replace("Z", "+00:00")).timestamp()
            except Exception:
                return None
        def text(e):
            c = (e.get("message") or {}).get("content")
            if isinstance(c, list):
                c = "".join(b.get("text") or "" for b in c if isinstance(b, dict) and b.get("type") == "text")
            return c if isinstance(c, str) else ""
        def lines_rev(path, bs=65536):
            with open(path, "rb") as f:
                f.seek(0, 2)
                pos, rest = f.tell(), b""
                while pos > 0:
                    step = min(bs, pos)
                    pos -= step
                    f.seek(pos)
                    parts = (f.read(step) + rest).split(b"\n")
                    rest = parts.pop(0)
                    for ln in reversed(parts):
                        yield ln
                if rest:
                    yield rest
        def user_set():
            ok_parents, nxt_ok = set(), False
            for ln in lines_rev(tp):
                if not ln.strip():
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if not isinstance(e, dict):
                    continue
                t = ts(e)
                if t is not None and t < since:
                    return False
                if e.get("type") != "user" or e.get("isSidechain"):
                    continue
                s = text(e).lstrip()
                if s.startswith("<command-name>/effort<") and t is not None and t > since \
                        and (nxt_ok or e.get("uuid") in ok_parents):
                    return True
                m = re.match(r"<local-command-stdout>Set effort level to (\w+)", s)
                nxt_ok = bool(m and m.group(1) == eff)
                if nxt_ok and e.get("parentUuid"):
                    ok_parents.add(e.get("parentUuid"))
            return False
        try:
            since = os.path.getmtime(tgt)
            adopt = user_set()
        except Exception:
            adopt = False
        if adopt:
            with open(tgt, "w") as f:
                f.write(eff + "\n")
            sys.exit(0)
    reason = ("STOP: effort effective=%s, target=%s. Write ONE line to the user: "
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
  end)
    [ -n "$h_sid" ] || exit 0
    rm -f "$state_dir/effort-target-$h_sid" "$state_dir/effort-phase-$h_sid" "$state_dir/effort-hold-$h_sid" 2>/dev/null
    ;;
  start)
    if [ -n "$h_eff" ] && [ "$h_eff" != medium ]; then
      if [ "$h_src" = "-" ]; then
        echo "Tu: /effort medium (sesiunea a pornit pe $h_eff)"
      else
        echo "Tu: /effort medium (sesiunea a pornit pe $h_eff, source=$h_src)"
      fi
    fi
    ;;
esac
exit 0
