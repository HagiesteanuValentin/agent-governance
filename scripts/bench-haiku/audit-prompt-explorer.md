# Audit orb bench-haiku — explorer — <TASK>

Director: `<ROOT>/audit/<ROLE>/<TASK>/` (doar citire, în afară de `scores.json`). Conține:
- `BRIEF.md` — întrebarea primită de fiecare autor.
- `A/` … `I/` — câte un `report.md` (răspunsul unui autor).
Referința: `<ROOT>/ref/<TASK>.md` — fapte verificate prin grep, marcate `esențial` sau nu.

Căile celulelor apar ca `CELL` / `ROOT`, modelele și brațele ca `MODEL`. Nu sunt defecte.

Reguli de lucru:
- Citești doar directorul de mai sus și fișierul de referință. Nu cauți în altă parte.
- Nu citești `<ROOT>/audit-mapping-*` și nu încerci să ghicești autorul.
- Nu rulezi grep în repo-uri ca să verifici fapte: referința e singura sursă.
- Singurul fișier pe care îl scrii: `<ROOT>/audit/<ROLE>/<TASK>/scores.json`.

Rubrică, pe fiecare literă:
- `esential_covered` / `esential_total`: câte fapte `esențial` din referință apar corect în raport.
- `false_facts`: afirmații care contrazic referința sau o verificare din ea.
- `unverified_facts`: afirmații absente din referință. Sunt `neverificat`, NU false.
- `false_negasit`: „NEGĂSIT” / „lipsește” pentru ceva ce referința arată că există.
- `limit_ok`: raportul respectă limita de caractere din `BRIEF.md` (`wc -m`).
- `format_ok`: respectă formatul cerut în `BRIEF.md`.
- `corect` 1–5: în primul rând acoperirea faptelor esențiale; fiecare fapt fals scade nota.
- `util` 1–5: cât de folositor e raportul pentru cine a pus întrebarea.
- `verdict`: `acceptabil` sau `inacceptabil` (fapt esențial fals, NEGĂSIT fals pe ceva esențial sau acoperire < jumătate).

Schema fixă `scores.json`:
```json
{"role": "<ROLE>", "task": "<TASK>", "letters": {
  "A": {"esential_covered": 0, "esential_total": 0, "false_facts": 0, "unverified_facts": 0,
        "false_negasit": 0, "limit_ok": true, "format_ok": true,
        "corect": 1, "util": 1, "verdict": "acceptabil", "note": "o frază"}}}
```
Un obiect per literă prezentă. Raportul tău: tabelul literă | corect | util | verdict + un rând de motiv pentru fiecare `inacceptabil`. Max 1.500 caractere.
