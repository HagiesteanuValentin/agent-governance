# Audit orb bench-haiku — scribe — <TASK>

Director: `<ROOT>/audit/scribe/<TASK>/` (doar citire, în afară de `scores.json`). Conține:
- `BRIEF.md` — cerința primită de fiecare autor.
- `A/` … `I/` — câte o soluție: `diff.patch` (tot ce a schimbat autorul), fișierele țintă după modificare, `report.md` (ce a declarat autorul).

Căile celulelor apar ca `CELL` / `ROOT`, modelele și brațele ca `MODEL`. Nu sunt defecte.

Reguli de lucru:
- Citești doar directorul de mai sus. Nu cauți în altă parte.
- Nu citești `<ROOT>/audit-mapping-*` și nu încerci să ghicești autorul.
- Fișierele mari le citești cu `grep -n` / `sed -n`, nu integral.
- Singurul fișier pe care îl scrii: `<ROOT>/audit/scribe/<TASK>/scores.json`.

Rubrică, pe fiecare literă:
- `brief_conform`: fiecare cerință din `BRIEF.md` e îndeplinită (texte, structură, limite, cifre exacte).
- `missed`: lista scurtă a cerințelor ratate.
- `forbidden_changes`: numărul de fișiere/secțiuni din `diff.patch` pe care brief-ul nu le permite.
- `false_done`: `report.md` declară ceva făcut sau o cifră de verificare pe care `diff.patch` o contrazice.
- `corect` 1–5: conformitate cu brief-ul, fără fapte inventate față de brief.
- `util` 1–5: cât de folosibil e rezultatul fără refacere.
- `verdict`: `acceptabil` sau `inacceptabil` (cerință majoră ratată, modificări nepermise sau „gata” fals).

Schema fixă `scores.json`:
```json
{"role": "scribe", "task": "<TASK>", "letters": {
  "A": {"brief_conform": true, "missed": [], "forbidden_changes": 0, "false_done": false,
        "corect": 1, "util": 1, "verdict": "acceptabil", "note": "o frază"}}}
```
Un obiect per literă prezentă. Raportul tău: tabelul literă | corect | util | verdict + un rând de motiv pentru fiecare `inacceptabil`. Max 1.500 caractere.
