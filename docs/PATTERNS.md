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
