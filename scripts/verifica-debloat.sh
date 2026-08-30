#!/usr/bin/env bash
# 🔴 ce verifică și cu ce praguri — scripts/SCRIPTS.md
set -u

cd "$(dirname "$0")/.." || exit 1
FAIL=0
GLOBAL=templates/CLAUDE.global.md
ORCH=templates/orchestrare.md
HOOK=hooks/session-start.sh

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; FAIL=1; }

# 1. dimensiuni
n=$(wc -c < "$GLOBAL")
[ "$n" -le 3500 ] && pass "$GLOBAL = ${n}B ≤ 3500" || fail "$GLOBAL = ${n}B > 3500"
n=$(wc -c < "$ORCH")
[ "$n" -le 9800 ] && pass "$ORCH = ${n}B ≤ 9800" || fail "$ORCH = ${n}B > 9800"

# 2. șiruri interzise în cele două template-uri
BANNED=('Motiv (' '30.08' '29.08' 'Playwright' 'Preview redus' 'verifica-' 'docs/polish/*.md nu' '-mic.png' '$7.8' '$79' '/home/' 'vali' 'DECIZII' 'RETETE' 'dosar/')
for s in "${BANNED[@]}"; do
  if grep -qiF -- "$s" "$GLOBAL" "$ORCH"; then
    fail "șir interzis prezent: «$s»"
  else
    pass "șir interzis absent: «$s»"
  fi
done

# 3. cuvinte-cheie obligatorii în orchestrare.md
KEYS=('explorer-max' 'implementer-sonnet' 'implementer-max' 'scripter-complex' 'scribe' 'auditor' 'design-lead-expert' 'escalation:' 'git diff --stat' '--force' '150k' '220k' '3 runs' '4 live agents' 'SendMessage' 'dossier' '/rate' 'worktree' '## Brief' 'Fable' '--stat' 'Co-Authored-By' 'plan mode' 'SCRIPTS.md' '1.5k')
for k in "${KEYS[@]}"; do
  if grep -qF -- "$k" "$ORCH"; then
    pass "cuvânt-cheie prezent: «$k»"
  else
    fail "cuvânt-cheie lipsă: «$k»"
  fi
done

# 4. hook cu orchestrare.md disponibilă
TMP=$(mktemp -d)
mkdir -p "$TMP/.claude"
cp "$ORCH" "$TMP/.claude/orchestrare.md"
out=$(echo '{"source":"startup","cwd":"'"$PWD"'"}' | HOME="$TMP" bash "$HOOK"); rc=$?
[ "$rc" -eq 0 ] && pass "hook cu orchestrare: exit 0" || fail "hook cu orchestrare: exit $rc"
case "$out" in
  *"=== ORCHESTRATION"*) pass "hook tipărește markerul ORCHESTRATION" ;;
  *) fail "hook fără markerul ORCHESTRATION" ;;
esac
n=$(printf '%s' "$out" | wc -c)
m=$(wc -c < "$ORCH")
[ "$n" -ge "$m" ] && pass "output hook ${n}B ≥ orchestrare ${m}B" || fail "output hook ${n}B < orchestrare ${m}B"

# 5. hook fără orchestrare.md
TMP2=$(mktemp -d)
mkdir -p "$TMP2/.claude"
out2=$(echo '{"source":"startup","cwd":"'"$TMP2"'"}' | HOME="$TMP2" CLAUDE_PROJECT_DIR="$TMP2" bash "$HOOK"); rc=$?
[ "$rc" -eq 0 ] && pass "hook fără orchestrare: exit 0" || fail "hook fără orchestrare: exit $rc"
case "$out2" in
  *"=== ORCHESTRATION"*) fail "hook fără orchestrare: marker prezent" ;;
  *) pass "hook fără orchestrare: fără marker" ;;
esac

rm -rf "$TMP" "$TMP2"

# 6. fără diacritice românești în templates traduse și în agents/*.md
for f in "$GLOBAL" "$ORCH" agents/*.md; do
  c=$(grep -o '[ăâîșțĂÂÎȘȚ]' "$f" | wc -l)
  [ "$c" -eq 0 ] && pass "$f fără diacritice RO" || fail "$f are $c diacritice RO"
done

[ "$FAIL" -eq 0 ] && echo "TOATE PASS" || echo "EȘEC"
exit "$FAIL"
