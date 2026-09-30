# Audit orb bench-scripter — <T>

Director: `<BENCH_ROOT>/audit/<T>/` (doar citire). Conține:
- `BRIEF.md` — cerința primită de fiecare autor.
- `A/` … `J/` — câte o soluție: `scripts/<script>.mjs` + ieșirile lui (`docs/…`, `stdout.out`).
- `ref-out/` — ieșirile unei soluții de referință (fără script), pentru comparat cifre.

Porturile apar ca `44NN`, căile ca `<CELL>` / `<BENCH>`. Nu sunt defecte; nu le nota.

Reguli de lucru:
- Citești JSON-urile și `stdout.out` mari cu `grep -n` / `jq`, nu integral.
- Nu deschizi PNG-uri; pentru capturi verifici doar numele și numărul fișierelor (`ls`).
- Nu faci Edit/Write și nu rulezi scripturile: alt auditor citește același director.
- Nu cauți alte fișiere în afara directorului dat.

Rubrică, pe fiecare literă:
- `corect` 1–5: acoperă fiecare cerință din `BRIEF.md` (lățimi, pagini, metrici, capturi, md ≤ limită).
  Alegi 5 valori din ieșirea literei și le compari cu aceleași valori din `ref-out/`.
  Diferență mare fără motiv vizibil = cerință greșit măsurată.
- `robust` 1–5: fără port sau cale hardcodate (portul vine din argument), exit ≠ 0 la eroare,
  idempotent (a 2-a rulare dă aceleași cifre, nu adaugă fișiere), oprește ce a pornit (server, browser).
- `lizibil` 1–5: structură, nume, cât de ușor se modifică de altcineva.
- verdict: `OK` sau `ABATERI (n)`, n = numărul de cerințe din brief încălcate.
- `inacceptabil` da/nu: da dacă rezultatul nu poate fi folosit fără refacere
  (cifre greșite, cerință majoră lipsă, efecte în afara fișierelor permise).

Raport ≤2.000 de caractere, exact formatul:

| lit | corect | robust | lizibil | verdict | inacceptabil |
|---|---|---|---|---|---|
| A | 4 | 3 | 4 | ABATERI (1) | nu |

Un rând per literă prezentă (până la 10). Sub tabel, câte un rând de motiv DOAR pentru
literele cu `inacceptabil = da`: `<lit>: <motiv, o frază>`. Altceva nu scrii.
