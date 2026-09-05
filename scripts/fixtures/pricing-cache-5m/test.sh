#!/usr/bin/env bash
# Testul fixture pentru scripts/pricing-cache-5m.py: dry-run, aplicare, diff cu dupa/, a doua rulare = 0.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp "$here"/inainte/* "$tmp"/
PRICES=(--date 2026-09-05 --note "fixture"
  --price claude-fable-5-1=10,50,1.0,12.5,20
  --price claude-fable-5=10,50,1.0,12.5,20
  --price claude-opus-5=5,25,0.5,6.25,10
  --price claude-sonnet-5=2,10,0.2,2.5,4
  --price claude-haiku-4-5-20251001=1,5,0.1,1.25,2
  --price default=5,25,0.5,6.25,10
  --extra claude-fable-5-1=api_cache_read:0.25)
run() { python3 "$repo/scripts/pricing-cache-5m.py" --pricing "$tmp/pricing.json" \
        --metrics "$tmp/fragment_metrics.py" "${PRICES[@]}" "$@"; }

rc=0
run --dry-run >/dev/null || rc=1
diff -q "$here/inainte/fragment_metrics.py" "$tmp/fragment_metrics.py" >/dev/null || { echo "FAIL: dry-run a scris"; rc=1; }
run >/dev/null || rc=1
diff -u "$here/dupa/fragment_metrics.py" "$tmp/fragment_metrics.py" || { echo "FAIL: fragment != dupa/"; rc=1; }
python3 -c "import json,sys; a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2])); sys.exit(0 if a==b else 1)" \
  "$here/dupa/pricing.json" "$tmp/pricing.json" || { echo "FAIL: pricing != dupa/"; rc=1; }
out="$(run)"
echo "$out" | grep -q "0 aplicate, 12 deja prezente" || { echo "FAIL: a doua rulare nu e idempotenta"; echo "$out"; rc=1; }
[ $rc -eq 0 ] && echo "OK: fixture pricing-cache-5m (12 reguli, dry-run curat, idempotent)"
exit $rc
