# bench-scripter

Benchmark `scripter` (Opus 5.5 low) vs Sonnet 5.5 medium/high pe 3 scripturi reale de măsurători.
Celule în `~/workflow/experimente/bench-scripter/<T>/<cell>-<run>`; rezultatul verificării în `<T>/<cell>-<run>.json`.

| T | repo | BASE (părintele scriptului original) | script | ref |
|---|---|---|---|---|
| T1 studii-caz | promo-site | `c41e0f7` (= `3da413b^`) | `scripts/verify-studii-caz.mjs` | `3da413b` |
| T2 produs | blueprint_prezentare | `e3e41cb` (+ `produs.dosar.md` din `1fbd216`) | `scripts/verifica-produs.mjs` | `1fbd216` (+ md) |
| T3 index-miscare | blueprint_prezentare | `e3e41cb` (+ `index.dosar.md` din `33be8a8`) | `scripts/verifica-index-miscare.mjs` | `ref/` (reconstruit) |

- T3: scriptul din `33be8a8` e extins de brief-urile 1–3. `ref/T3-verifica-index-miscare.mjs` e versiunea de la hand-back-ul brief 0, reconstruită din transcript (Write + 3 editări python; 8.527 B, ca în run-log). `ref/T3-index.masuratori.md` = generatorul original rulat pe ieșirea ref (2.675 caractere).
- Dosarele T2/T3 erau netrackuite la momentul rulării; conținutul din commit e identic cu ce a citit scripter-ul (verificat pe transcript). Intră în commit-ul `base` al celulei.
- T1: `playwright` 1.63.0 (din `~/.npm/_npx`) se copiază în `node_modules` — pe 24.09 scriptul original rula cu `import "playwright"`, azi promo-site nu-l mai are.

## Brief-uri (`briefs/`)
- T1: copiat verbatim din `promo-site/docs/dosar/brief-0-studii-caz.md`; singura abatere: port din `CELL.env` + `--strictPort`.
- T2/T3: textul original al brief-ului 0 (din transcriptul scripter-ului, nu din audit): fără dsf 0.5, fără filament. Abateri: 4321 → portul din `CELL.env`; T2 „Rădăcină” = directorul curent (nu repo-ul live); T3 spune explicit că scriptul acceptă `--url`.

## Folosire
```
./setup.sh <T1..T3> <run> [--ref]      # CELLS="..." pentru alte nume; port unic 4400+n în CELL.env
./verify.sh <T1..T3> <cell-run|cale>   # oprește ce e pe port, pornește dev, rulează scriptul de 2×, scrie <cell>.json
./cleanup.sh [--dry-run]               # șterge doar celulele și .verify-* din bench-scripter/; păstrează <cell>.json
```
`verify.sh` rulează: T1 `--url http://localhost:PORT`, T2 `--port PORT`, T3 `--url http://localhost:PORT/`. Deci pornirea serverului de către scriptul T1 (fără `--url`) nu e verificată — rămâne la audit.

## Criterii (`checks.py`)
script există · exit 0 de 2× · PNG: T1 9 fișiere `studii-caz-<pagina>-<bp>.png` cu latura ≤1568; T2 3 sau 9 `-mic.png` lățime ≤1440 (confound: brief-ul „Capturi reduse `-mic.png` la 390, 768, 1440” admite 1 produs × 3 lățimi sau 3 produse × 3 lățimi); T3 3 `-mic.png` lățime ≤800 · md prezent ≤4.000 (T1, cu cele 3 pagini + hover) / ≤3.000 (T2, T3) · T3 `masuratori.json` · stabilitate: `.json`/`.md` modificate + stdout, rularea 1 vs 2, aceleași chei și text, cifre la ±10% sau ±1 · fără timestamp în JSON · `git status --porcelain` doar în căile permise.

Validare 30.09: ref PASS 3/3 (8/8, 7/7, 8/8), bază FAIL 3/3.
