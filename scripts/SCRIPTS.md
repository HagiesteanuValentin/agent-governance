# Scripts — agent-governance

Un rând per script; scripterul îl ține la zi; orchestratorul îl citește înainte de un brief de scripter.

| script | ce face | fișiere afectate | argumente | adaptare: ușoară/medie/grea — ce se schimbă | o dată/refolosibil |
| --- | --- | --- | --- | --- | --- |
| `scripts/verifica-debloat.sh` | verifică dimensiunile, șirurile interzise și cuvintele-cheie din template-urile CLAUDE.md + injecția orchestrării în hook | `templates/CLAUDE.global.md`, `templates/orchestrare.md`, `hooks/session-start.sh` | niciunul | ușoară — schimbi pragurile și listele de șiruri din capul scriptului | refolosibil |
