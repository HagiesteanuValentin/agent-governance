# PATTERNS — capcane tehnice

## Nume de sesiune

`<zi>-<HHMM>-<proiect>`, derivat doar din sesiunea însăși (primul timestamp + `cwd`). Schema
veche `-s<N>-` număra frații din directorul de transcripte, deci rangul se schimba când
apărea sau dispărea un fișier. Nu reintroduce scanarea directorului în `session_name`.
Coliziunea (alt session id în același minut) → `HHMMSS`; `--out-dir` șterge recordul aceluiași
session id salvat sub alt nume, ca re-analiza să nu lase dubluri.

## Sesiuni reluate
La `--resume`, transcriptul nou copiază mesajele sesiunii vechi; ele au `session_id`-ul
părintelui, diferit de numele fișierului. Tokenii lor au fost deja facturați acolo, deci
usage-ul acestor mesaje nu intră în `main` și în `totals` — altfel costul e numărat de două
ori. Recordul păstrează `resumed_from` și `inherited_assistant_msgs` ca urmă.
La fel, lansările de agenți moștenite n-au transcript propriu (`transcript` gol, 0 calls,
$0). Ele rămân în listă, dar nu intră în numărători sau costuri per agent (scripter runs,
files_changed, $/edit) — altfel o sesiune reluată dublează cifrele.

## Câmpuri noi în recorduri vechi
Recordurile din `metrics-local/` nu se re-analizează la fiecare rulare, deci un câmp nou
lipsește din cele vechi. La agregate (medii, $/edit) le sari, nu le trata ca 0: numărătorul
ar veni din toate sesiunile, numitorul doar din cele noi. În tabele afișează `—`.
