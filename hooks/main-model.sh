#!/bin/bash
# 🔴 model from the last assistant line, not from the file's tail — PATTERNS «The model inside hooks»
tp="${1:-}"
if [ -n "${GOV_MODEL:-}" ]; then
    printf '%s\n' "$GOV_MODEL"
    exit 0
fi
m=""
if [ -n "$tp" ] && [ -f "$tp" ]; then
    m=$(tac "$tp" 2>/dev/null \
        | grep -E '"type" *: *"assistant"' \
        | grep -v '<synthetic>' \
        | grep -m1 -oE '"model" *: *"claude-[^"]+"' \
        | sed 's/.*"claude-/claude-/; s/"$//')
fi
if [ -z "$m" ]; then
    m=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('model') or '')" \
        "$HOME/.claude/settings.json" 2>/dev/null)
    m="${m%\[1m\]}"
fi
[ -n "$m" ] || m="unknown"
printf '%s\n' "$m"
exit 0
