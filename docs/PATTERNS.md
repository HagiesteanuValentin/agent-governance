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
Fork-ul se analizează din origine prin lanțul `continued-in`; fork-ul nu produce record
propriu.

## Câmpuri noi în recorduri vechi
Recordurile din `metrics-local/` nu se re-analizează la fiecare rulare, deci un câmp nou
lipsește din cele vechi. La agregate (medii, $/edit) le sari, nu le trata ca 0: numărătorul
ar veni din toate sesiunile, numitorul doar din cele noi. În tabele afișează `—`.

## Claude Code — limite verificate în docs (02.09.2026)
1. Output hook ≤10.000 caractere PER hook-comandă; peste → fișier + preview. Alternative
   fără plafon hard: CLAUDE.md `@import`, `.claude/rules/`.
2. Efortul main îl schimbă doar userul: `/effort` (persistă per model în settings),
   `effortLevel`/`modelSettings.<model>.effortLevel`, env `CLAUDE_CODE_EFFORT_LEVEL`;
   modelul n-are tool; reîncărcarea settings.json pe viu NU e documentată.
3. Hook-urile primesc în stdin `effort.level` (PreToolUse/PostToolUse/Stop/SubagentStop),
   `permission_mode`, `transcript_path`, `session_id`.
4. Frontmatter subagent: `model: sonnet|opus|haiku|fable|inherit|<id>`,
   `effort: low|medium|high|xhigh|max`, `maxTurns`, `tools`, `disallowedTools`.
5. Subagenții pot lansa subagenți (adâncime 3, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`) —
   în proiect e interzis prin `tools` fără Agent.
6. SendMessage către un subagent terminat îl reia cu istoric complet.
7. PostToolUse/PreToolUse hooks run inside subagents as well; stdin carries `agent_id`;
   main-only hooks must guard on it.
8. Multiple PostToolUse hook entries matching the same tool call run without guaranteed
   ordering; a "check the write" hook must gate on `tool_name`, not assume it runs after
   a sibling "do the write" hook for that same call.
9. SessionStart stdin carries `source`: startup|resume|clear|compact|fork. A resumed session
   must not reset per-phase state (e.g. effort level) set by the session it resumes.
10. A real `/effort` command invalidates the messages cache: cache_read 67 818 → 17 234 on
    the next turn (system + tools stay cached); a hook writing `effortLevel` into
    settings.json does not touch the cache (63 240 → 67 818). One rewrite of ~52k tokens
    per switch.
11. An automatic fork (`SessionStart source=fork`, seen when main goes `sessionKind: bg`
    with live subagents) invalidates the cache the same way (69 326 → 14 904), also with
    no effort change (session 1457: 104 536 → 14 904). Undocumented; cannot be disabled.
12. Documented officially: top-level (session) effort invalidates the cache; per-message effort
    keeps it — see issue anthropics/claude-code #61984 (per-message effort).
Sursa: code.claude.com/docs (hooks, sub-agents, model-config, settings-reference).
- Measured 02.09: editing `settings.json` from a hook does NOT change the live effort (main stayed medium after the hook wrote low); only `/effort` does. PostToolUse does not fire when the tool exits non-zero (PostToolUseFailure does) — a check hook stays silent on failed calls.

## Baseline de efort: ture, nu linii
Un mesaj assistant e scris pe mai multe linii în `.jsonl` (una per bloc: thinking, text,
tool_use), toate cu același `message.id` și același `usage`. Numărat pe linii, corpusul dă
n=1033 și mediană output 785; numărat pe ture (deduplicat pe `message.id` global peste
corpus — o sesiune reluată copiază turele părintelui) dă n=403 și mediană 502. Contrafactualul
înlocuiește output-ul unei TURE, deci folosește 502; `effort-baseline.json` păstrează și
cifrele pe linii, ca să nu pară o regresie.

## Efort din transcript
Câmpul `effort` e scris pe linia din `.jsonl` (nu în obiectul `message`); `thinking_tokens`
stă sub `message.usage.output_tokens_details`, nu direct sub `usage`. Cine parsează
transcriptul pentru efort/tokeni citește ambele la nivelul lor corect, altfel iese `None`
tăcut în loc de eroare.

## Procente cu numitor lipsă
Când atribuirea pe main eșuează, `main.*` iese tot 0, dar `wasted_total` rămâne mare.
Fallback-ul `x / (total or 1)` transformă asta în procente absurde (v1.5: 4.807.400%).
Numitorul 0 înseamnă „nu se poate calcula": sesiunea iese din numărător ȘI din numitor,
iar celula se afișează `n/a`. Regula ține și pentru procentul salvat în record, nu doar
pentru cel calculat la agregare.

## Hook-uri SessionStart rulează în paralel
`session-start.sh` are mai multe branch-uri (`rules`, `handoff`, `v17`) care pot fi apelate
separat. Dacă logica de reset a efortului (case-ul pe `source`: resume|fork|compact păstrează,
altfel `medium`) trăiește doar într-un branch, celelalte branch-uri citesc `settings.json`
înainte ca reset-ul să fi rulat și afișează valoarea veche. Logica stă într-o singură funcție
(`reset_effort_for_source`) apelată de FIECARE branch care citește efortul, înainte de citire.

## sessionId vs session_id în jsonl
`sessionId` (camelCase) e egal cu numele fișierului, dar e REscris pe liniile copiate la
resume; `session_id` (snake_case) e id de proces, supraviețuiește `/clear` și poate fi străin
pe linii proprii. Niciunul singur nu distinge originalul de copie: o linie e moștenită doar
dacă `session_id` e străin ȘI `uuid`-ul ei apare în `<dir>/<session_id>.jsonl` (deja facturată
acolo). Părinte lipsă → linie proprie; uuid-urile lui se citesc o dată, în `_PARENT_UUIDS`.
Părinte dintr-un alt proiect (alt director) nu e detectat → linia iese proprie.

## Modelul în hook-uri
`hooks/main-model.sh <transcript>` dă modelul sesiunii: `GOV_MODEL` (teste) → ultima linie
`"type":"assistant"` cu `"model":"claude-…"` (`tac | grep -m1`, nu `tail -c`: tool_result-urile
pot conține textul `claude-opus`) → `.model` din settings, fără `[1m]` → `unknown`.
Gărzile de main (write-mare, brief-mare, blocurile ORCHESTRATION din session-start) acționează
doar când modelul conține `fable` sau `mythos`; `unknown` e tratat ca Fable (fail-closed).
Ramura de agent nu se schimbă: agenții au propriile gărzi, indiferent de model.
Un `--model` dat din CLI nu apare în `settings.json` (rămâne cheia default) — sursa transcript
prinde totuși modelul real; dacă transcriptul lipsește, garda rămâne activă (fail-closed) chiar
și pe Opus pornit din CLI. Blocarea (deny) merge doar din hook-uri `PreToolUse`; un hook
`PostToolUse` poate doar avertiza sau loga, nu poate opri acțiunea.

## comentarii-cod pe MultiEdit
`MultiEdit` trimite `tool_input.edits[]`, nu `new_string`. Hook-ul lipește `new_string`-urile cu
o linie goală între ele: linia goală rupe seria de comentarii, deci două pointere de câte un
rând din edit-uri diferite nu sunt citite ca un bloc de 2 rânduri (deny fals).
Vechiul `old_string` se lipește la fel, ca mutarea unui comentariu să nu iasă „adăugat".

## Recitire după propria scriere
În transcriptul agentului, un `Edit` respins (`tool_result.is_error`: «file modified since
read», «old_string not found») nu e o scriere reușită: agentul chiar are nevoie de un Read.
Hook-ul îl sare și caută mai departe în urmă. Un `Bash` care conține basename-ul fișierului
(build/test pe el) resetează contorul: rezultatul poate cere o recitire.
Read cu `offset`/`limit` pe ≤60 de linii rămâne permis — e verificare punctuală, nu recitire.

## Batching Bash
PreToolUse vede doar comanda, nu output-ul: „mic" = fără heredoc și sub 200 de caractere.
Contorul (`/tmp/claude-hooks/bash-batch-<session_id>`) stă înaintea ieșirii pe RANGE, ca
`sed -n`/`head` să se numere; reset la comandă mare sau după 90 s. Paralelismul nu se poate
citi din transcript (la PreToolUse mesajul asistent cu `tool_use_id`-ul curent nu e încă
scris): sub 3 s de la ultimul apel mic = același mesaj — nu incrementează, nu resetează.

## orchestrare.md sub 10 KB
`~/.claude/orchestrare.md` și `templates/orchestrare.md` trebuie să stea sub 10.000 bytes:
peste, harness-ul trunchiază blocul SessionStart la 2 KB și sesiunea pierde reguli. Pe
05.09 marja era sub 5 bytes (9.996/9.997) — orice rând nou cere o scurtare compensatorie în
altă parte a fișierului, nu doar adăugare.

## analizor: locale
`session_metrics.py` scrie `·`, `≤`, `—` în raport. Sub `LANG=C`/`LC_ALL=C` (sau pe Windows)
stdout ajunge ascii și printul crapă cu `UnicodeEncodeError`. De aceea `main()` forțează
`reconfigure(encoding="utf-8", errors="replace")` pe stdout și stderr, înainte de orice print.
