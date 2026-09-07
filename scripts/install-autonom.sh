#!/bin/bash
# 🔴 manually run by the user (the auto mode classifier blocks agents on ~/.claude) — docs/DECIZII.md «Mod autonom (04.09.2026)»
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd); LIVE="${LIVE:-$HOME/.claude}"
cp "$LIVE/settings.json" "$LIVE/settings.json.bak-$(date +%Y%m%d-%H%M)"
cp "$REPO/hooks/autonom.sh" "$LIVE/hooks/autonom.sh"; chmod +x "$LIVE/hooks/autonom.sh"
grep -q 'autonom-%s' "$LIVE/hooks/agenti-vii.sh" || python3 - "$LIVE/hooks/agenti-vii.sh" <<'PY'
import sys; p=sys.argv[1]; t=open(p).read()
hunk='# 🔴 marker autonom-<sid> = no ask — docs/DECIZII.md «Mod autonom (04.09.2026)»\nif os.path.exists(os.path.join(MARKER_DIR, "autonom-%s" % safe_sid)):\n    sys.exit(0)\n'
i=t.rindex('rows = read_rows()'); open(p,'w').write(t[:i]+hunk+t[i:])
PY
python3 - "$LIVE/settings.json" <<'PY'
import json,sys; p=sys.argv[1]; s=json.load(open(p)); h=s['hooks']; H=lambda m:{"type":"command","command":"${HOME}/.claude/hooks/autonom.sh "+m}
h.setdefault('UserPromptSubmit',[]); h['UserPromptSubmit'].append({"hooks":[H("prompt")]}) if not any('autonom' in x['command'] for g in h['UserPromptSubmit'] for x in g['hooks']) else None
h['PreToolUse'].append({"matcher":"AskUserQuestion|EnterPlanMode","hooks":[H("gate")]}) if not any('autonom' in x['command'] for g in h['PreToolUse'] for x in g['hooks']) else None
open(p,'w').write(json.dumps(s,indent=2,ensure_ascii=False)+'\n')
PY
python3 -c "import json;json.load(open('$LIVE/settings.json'))"; echo "autonom.sh in settings: $(grep -c autonom.sh "$LIVE/settings.json") (expect 2)"
diff <(sed 's/#.*//' "$REPO/hooks/agenti-vii.sh") <(sed 's/#.*//' "$LIVE/hooks/agenti-vii.sh") && echo "agenti-vii live = repo (code)"
HOOK="$LIVE/hooks/autonom.sh" bash "$REPO/hooks/test-autonom.sh" | tail -1
