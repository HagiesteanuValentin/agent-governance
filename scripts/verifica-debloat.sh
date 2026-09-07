#!/usr/bin/env bash
# 🔴 what it checks and with what thresholds — scripts/SCRIPTS.md
set -u

cd "$(dirname "$0")/.." || exit 1
FAIL=0
GLOBAL=templates/CLAUDE.global.md
ORCH=templates/orchestrare.md
ORCHV17=templates/orchestrare-v17.md
HOOK=hooks/session-start.sh

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAIL=1; }

# 1. dimensiuni
n=$(wc -c < "$GLOBAL")
[ "$n" -le 3500 ] && pass "$GLOBAL = ${n}B ≤ 3500" || fail "$GLOBAL = ${n}B > 3500"
n=$(wc -c < "$ORCH")
[ "$n" -le 9800 ] && pass "$ORCH = ${n}B ≤ 9800" || fail "$ORCH = ${n}B > 9800"
n=$(wc -c < "$ORCHV17")
[ "$n" -le 3500 ] && pass "$ORCHV17 = ${n}B ≤ 3500" || fail "$ORCHV17 = ${n}B > 3500"

# 2. banned strings in the two templates
BANNED=('Motiv (' '30.08' '29.08' 'Playwright' 'Preview redus' 'verifica-' 'docs/polish/*.md nu' '-mic.png' '$7.8' '$79' '/home/' 'vali' 'DECIZII' 'RETETE' 'dosar/')
for s in "${BANNED[@]}"; do
  if grep -qiF -- "$s" "$GLOBAL" "$ORCH"; then
    fail "banned string present: «$s»"
  else
    pass "banned string absent: «$s»"
  fi
done

# 3. required keywords in orchestrare.md
KEYS=('explorer-max' 'implementer-sonnet' 'implementer-max' 'scripter-complex' 'scribe' 'auditor' 'design-lead-expert' 'escalation:' 'git diff --stat' '--force' '150k' '220k' '3 runs' '6 live agents' 'SendMessage' 'dossier' '/rate' 'worktree' '## Brief' 'Fable' '--stat' 'Co-Authored-By' 'plan mode' 'SCRIPTS.md' '1.5k')
for k in "${KEYS[@]}"; do
  if grep -qF -- "$k" "$ORCH"; then
    pass "keyword present: «$k»"
  else
    fail "keyword missing: «$k»"
  fi
done

# 4. hook with orchestrare.md available
TMP=$(mktemp -d)
mkdir -p "$TMP/.claude"
cp "$ORCH" "$TMP/.claude/orchestrare.md"
out=$(echo '{"source":"startup","cwd":"'"$PWD"'"}' | HOME="$TMP" bash "$HOOK"); rc=$?
[ "$rc" -eq 0 ] && pass "hook cu orchestrare: exit 0" || fail "hook cu orchestrare: exit $rc"
case "$out" in
  *"=== ORCHESTRATION"*) pass "hook prints the ORCHESTRATION marker" ;;
  *) fail "hook without the ORCHESTRATION marker" ;;
esac
n=$(printf '%s' "$out" | wc -c)
m=$(wc -c < "$ORCH")
[ "$n" -ge "$m" ] && pass "output hook ${n}B ≥ orchestrare ${m}B" || fail "output hook ${n}B < orchestrare ${m}B"

# 5. hook without orchestrare.md
TMP2=$(mktemp -d)
mkdir -p "$TMP2/.claude"
out2=$(echo '{"source":"startup","cwd":"'"$TMP2"'"}' | HOME="$TMP2" CLAUDE_PROJECT_DIR="$TMP2" bash "$HOOK"); rc=$?
[ "$rc" -eq 0 ] && pass "hook without orchestrare: exit 0" || fail "hook without orchestrare: exit $rc"
case "$out2" in
  *"=== ORCHESTRATION"*) fail "hook without orchestrare: marker present" ;;
  *) pass "hook without orchestrare: no marker" ;;
esac

rm -rf "$TMP" "$TMP2"

# 6. no Romanian diacritics in translated templates and in agents/*.md
for f in "$GLOBAL" "$ORCH" "$ORCHV17" agents/*.md; do
  c=$(grep -o '[ăâîșțĂÂÎȘȚ]' "$f" | wc -l)
  [ "$c" -eq 0 ] && pass "$f no RO diacritics" || fail "$f has $c RO diacritics"
done

[ "$FAIL" -eq 0 ] && echo "ALL PASS" || echo "FAILURE"
exit "$FAIL"
