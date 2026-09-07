#!/usr/bin/env bash
# Usage: dosar-simplu.sh [out-dir] [--recheck] — see scripts/SCRIPTS.md
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# set to your project
MAMA="${MAMA:-${PROJECT:-${HOME}/workflow/proiecte/your-project}}"
IN="$REPO/metrics-local/experiments/simplu/input"
MAX_LINII="${MAX_LINII:-580}"

OUT="$REPO/metrics-local/experiments/simplu/dosar"
RECHECK="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recheck) RECHECK="true"; shift ;;
    -*) echo "Unknown argument: $1" >&2; exit 1 ;;
    *) OUT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; shift ;;
  esac
done

[[ -d "$MAMA/.git" ]] || { echo "MAMA is not a git repo: $MAMA" >&2; exit 1; }
mkdir -p "$OUT"

# nn:label:version:hash:path
SURSE=(
  "02:AcasaCorp:v0:3d04e84:src/components/AcasaCorp.astro"
  "03:AcasaCorp:v1:81f8e1b:src/components/AcasaCorp.astro"
  "04:contact:v0:f581997:src/pages/contact.astro"
  "05:contact:v1:cad08ad:src/pages/contact.astro"
  "06:galerie:v0:81f8e1b:src/pages/galerie.astro"
  "07:despre:v0:db52da0:src/pages/despre.astro"
  "08:Galerie3D:v0:81f8e1b:src/components/Galerie3D.astro"
)

GENERATE=()

# --- 01: brief v0 ---
cp "$IN/brief-v0.md" "$OUT/01-brief-v0.md"
GENERATE+=("01-brief-v0.md")

# --- 02..08: earlier versions, split into chunks ---
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for S in "${SURSE[@]}"; do
  IFS=':' read -r NN ETICHETA VER HASH CALE <<< "$S"
  git -C "$MAMA" cat-file -e "${HASH}:${CALE}" 2>/dev/null || { echo "Missing ${HASH}:${CALE} in MAMA" >&2; exit 1; }
  DATA="$(git -C "$MAMA" log -1 --format=%ad --date=short "$HASH")"
  git -C "$MAMA" show "${HASH}:${CALE}" > "$TMP/src.txt"
  TOTAL="$(wc -l < "$TMP/src.txt")"
  PARTI=$(( (TOTAL + MAX_LINII - 1) / MAX_LINII ))
  [[ $PARTI -lt 1 ]] && PARTI=1
  rm -f "$TMP"/chunk-*
  split -l "$MAX_LINII" -d -a 2 "$TMP/src.txt" "$TMP/chunk-"
  P=0
  for CH in "$TMP"/chunk-*; do
    P=$((P + 1))
    F="${NN}-${ETICHETA}.${VER}.part${P}.md"
    {
      echo "<!-- ${CALE} @ ${HASH} (${DATA}), part ${P}/${PARTI} -->"
      cat "$CH"
    } > "$OUT/$F"
    GENERATE+=("$F")
  done
done

# --- 09: npm run check in MAMA (once; reused on rerun) ---
CHECK="$OUT/09-check-v0.txt"
if [[ "$RECHECK" == "true" || ! -s "$CHECK" ]]; then
  echo "Running 'npm run check' in $MAMA ..."
  set +e
  (cd "$MAMA" && npm run check) > "$CHECK" 2>&1
  set -e
fi
GENERATE+=("09-check-v0.txt")

# --- 10: v0 report ---
cp "$IN/raport-v0.md" "$OUT/10-raport-v0.md"
GENERATE+=("10-raport-v0.md")

# --- 00: index ---
{
  echo "# Dossier of the previous run — task \"mechanical upkeep\""
  echo
  echo "Previous run of this task, abandoned when the worktree was reset to \`master\`."
  echo "Contains the v0 brief (superseded), earlier versions of the large files"
  echo "(v0 = oldest, v1 = intermediate), the \`npm run check\` output and the run's report."
  echo "**The current brief takes priority** wherever the dossier contradicts it."
  echo
  echo "## Files"
  for F in "${GENERATE[@]}"; do
    case "$F" in
      01-*) D="v0 brief, superseded by the current brief" ;;
      02-*|03-*) D="AcasaCorp.astro, earlier version" ;;
      04-*|05-*) D="contact.astro, earlier version" ;;
      06-*) D="galerie.astro, earlier version" ;;
      07-*) D="despre.astro, earlier version" ;;
      08-*) D="Galerie3D.astro, earlier version" ;;
      09-*) D="\`npm run check\` output from the previous run" ;;
      10-*) D="final report of the previous run" ;;
      *) D="" ;;
    esac
    echo "- \`$F\` — $D"
  done
} > "$OUT/00-CITESTE.md"

# --- counts ---
echo "--- dossier: $OUT"
TOTC=0
for F in "00-CITESTE.md" "${GENERATE[@]}"; do
  L="$(wc -l < "$OUT/$F")"
  C="$(wc -c < "$OUT/$F")"
  TOTC=$((TOTC + C))
  printf '%-34s %6s lines %9s chars\n' "$F" "$L" "$C"
done
echo "TOTAL characters: $TOTC (target 280000-320000)"
if [[ $TOTC -lt 280000 ]]; then
  echo "BELOW TARGET by $((280000 - TOTC)) characters"
fi
