#!/usr/bin/env bash
# Uz: dosar-simplu.sh [out-dir] [--recheck] — vezi scripts/SCRIPTS.md
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MAMA="${MAMA:-/home/vali/workflow/proiecte/blueprint_pictura}"
IN="$REPO/metrics-local/experiments/simplu/input"
MAX_LINII="${MAX_LINII:-580}"

OUT="$REPO/metrics-local/experiments/simplu/dosar"
RECHECK="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recheck) RECHECK="true"; shift ;;
    -*) echo "Argument necunoscut: $1" >&2; exit 1 ;;
    *) OUT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; shift ;;
  esac
done

[[ -d "$MAMA/.git" ]] || { echo "Mama nu e repo git: $MAMA" >&2; exit 1; }
mkdir -p "$OUT"

# nn:eticheta:versiune:hash:cale
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

# --- 02..08: versiuni anterioare, tăiate ---
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for S in "${SURSE[@]}"; do
  IFS=':' read -r NN ETICHETA VER HASH CALE <<< "$S"
  git -C "$MAMA" cat-file -e "${HASH}:${CALE}" 2>/dev/null || { echo "Lipsă ${HASH}:${CALE} în mamă" >&2; exit 1; }
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
      echo "<!-- ${CALE} @ ${HASH} (${DATA}), partea ${P}/${PARTI} -->"
      cat "$CH"
    } > "$OUT/$F"
    GENERATE+=("$F")
  done
done

# --- 09: npm run check în mamă (o singură dată; reutilizat la re-rulare) ---
CHECK="$OUT/09-check-v0.txt"
if [[ "$RECHECK" == "true" || ! -s "$CHECK" ]]; then
  echo "Rulez 'npm run check' în $MAMA ..."
  set +e
  (cd "$MAMA" && npm run check) > "$CHECK" 2>&1
  set -e
fi
GENERATE+=("09-check-v0.txt")

# --- 10: raport v0 ---
cp "$IN/raport-v0.md" "$OUT/10-raport-v0.md"
GENERATE+=("10-raport-v0.md")

# --- 00: index ---
{
  echo "# Dosarul rulării anterioare — task «îngrijire mecanică»"
  echo
  echo "Rulare anterioară pe acest task, abandonată la resetul worktree-ului la \`master\`."
  echo "Conține brief-ul v0 (înlocuit), versiunile anterioare ale fișierelor mari"
  echo "(v0 = cea mai veche, v1 = intermediară), output-ul \`npm run check\` și raportul rulării."
  echo "**Brief-ul curent are prioritate** oriunde dosarul îl contrazice."
  echo
  echo "## Fișiere"
  for F in "${GENERATE[@]}"; do
    case "$F" in
      01-*) D="brief-ul v0, înlocuit de brief-ul curent" ;;
      02-*|03-*) D="AcasaCorp.astro, versiune anterioară" ;;
      04-*|05-*) D="contact.astro, versiune anterioară" ;;
      06-*) D="galerie.astro, versiune anterioară" ;;
      07-*) D="despre.astro, versiune anterioară" ;;
      08-*) D="Galerie3D.astro, versiune anterioară" ;;
      09-*) D="output \`npm run check\` de la rularea anterioară" ;;
      10-*) D="raportul final al rulării anterioare" ;;
      *) D="" ;;
    esac
    echo "- \`$F\` — $D"
  done
} > "$OUT/00-CITESTE.md"

# --- cifre ---
echo "--- dosar: $OUT"
TOTC=0
for F in "00-CITESTE.md" "${GENERATE[@]}"; do
  L="$(wc -l < "$OUT/$F")"
  C="$(wc -c < "$OUT/$F")"
  TOTC=$((TOTC + C))
  printf '%-34s %6s linii %9s car.\n' "$F" "$L" "$C"
done
echo "TOTAL caractere: $TOTC (țintă 280000–320000)"
if [[ $TOTC -lt 280000 ]]; then
  echo "SUB ȚINTĂ cu $((280000 - TOTC)) caractere"
fi
