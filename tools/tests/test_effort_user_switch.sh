#!/bin/bash
# Usage: test_effort_user_switch.sh [path/to/effort-phase.sh]   (default: repo hooks/effort-phase.sh)
set -u
HOOK="${1:-$(cd "$(dirname "$0")/../.." && pwd)/hooks/effort-phase.sh}"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/home/.claude" "$T/state"
: > "$T/home/.claude/v17-effort-auto"
SID=testsid
TGT="$T/state/effort-target-$SID"
TR="$T/transcript.jsonl"
fail=0

iso() { python3 -c "import sys,datetime;print(datetime.datetime.fromtimestamp(float(sys.argv[1]),datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'))" "$1"; }

run() { # $1=mode $2=effort $3=permission_mode $4=tool
  printf '{"session_id":"%s","tool_name":"%s","hook_event_name":"PreToolUse","effort":{"level":"%s"},"permission_mode":"%s","transcript_path":"%s"}' \
    "$SID" "${4:-Bash}" "$2" "$3" "$TR" | HOME="$T/home" CLAUDE_JOB_DIR="$T/state" sh "$HOOK" "$1"
}

cmd_line() { # $1=ts $2=uuid
  printf '{"type":"user","isSidechain":false,"uuid":"%s","timestamp":"%s","message":{"role":"user","content":"<command-name>/effort</command-name>\\n            <command-message>effort</command-message>\\n            <command-args></command-args>"}}\n' "$2" "$1"
}
out_line() { # $1=ts $2=parent $3=level
  printf '{"type":"user","isSidechain":false,"parentUuid":"%s","uuid":"o-%s","timestamp":"%s","message":{"role":"user","content":"<local-command-stdout>Set effort level to %s (saved as your default for new sessions): x</local-command-stdout>"}}\n' "$2" "$2" "$1" "$3"
}
asst_line() { printf '{"type":"assistant","isSidechain":false,"timestamp":"%s","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}\n' "$1"; }

check() { # $1=name $2=expect deny|allow $3=output $4=expected target (optional)
  local got=allow
  case "$3" in *'"deny"'*) got=deny ;; esac
  local t; t=$(head -n1 "$TGT" 2>/dev/null)
  if [ "$got" = "$2" ] && { [ -z "${4:-}" ] || [ "$t" = "$4" ]; }; then
    echo "PASS $1 ($got, target=$t)"
  else
    echo "FAIL $1 (got $got, expected $2; target=$t, expected ${4:-any})"; fail=1
  fi
}

now=$(date +%s)
old=$(iso $((now - 3600)))

# (a) target low, effective medium, no /effort in transcript -> deny
printf 'low\n' > "$TGT"
{ asst_line "$old"; asst_line "$(iso $((now + 1)))"; } > "$TR"
check a deny "$(run gate medium default)" low

# (b) /effort newer than target -> allow, target becomes medium
new=$(iso $((now + 5)))
{ asst_line "$old"; cmd_line "$new" u1; out_line "$new" u1 medium; asst_line "$(iso $((now + 6)))"; } > "$TR"
check b allow "$(run gate medium default)" medium

# (c) after (b): ExitPlanMode writes low; /effort now older than target -> deny
run low medium default ExitPlanMode > /dev/null
touch -d "@$((now + 10))" "$TGT"
check c deny "$(run gate medium default)" low

# (d) guard missing -> inert
rm -f "$T/home/.claude/v17-effort-auto"
printf 'low\n' > "$TGT"; touch -d "@$((now - 60))" "$TGT"
check d allow "$(run gate medium default)" low
: > "$T/home/.claude/v17-effort-auto"

# (e) /effort only inside a tool result -> deny
printf 'low\n' > "$TGT"; touch -d "@$((now - 60))" "$TGT"
printf '{"type":"user","isSidechain":false,"uuid":"r1","timestamp":"%s","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"x","content":"<command-name>/effort</command-name> <local-command-stdout>Set effort level to medium</local-command-stdout>"}]}}\n' "$new" > "$TR"
check e deny "$(run gate medium default)" low

# (f) /effort with cancelled menu (no "Set effort level") -> deny
printf 'low\n' > "$TGT"; touch -d "@$((now - 60))" "$TGT"
{ cmd_line "$new" u2; printf '{"type":"user","isSidechain":false,"parentUuid":"u2","uuid":"o-u2","timestamp":"%s","message":{"role":"user","content":"<local-command-stdout>Cancelled effort selection</local-command-stdout>"}}\n' "$new"; } > "$TR"
check f deny "$(run gate medium default)" low

# (g) permission_mode=plan -> not adopted
printf 'low\n' > "$TGT"; touch -d "@$((now - 60))" "$TGT"
{ cmd_line "$new" u3; out_line "$new" u3 medium; } > "$TR"
check g deny "$(run gate medium plan)" low

exit $fail
