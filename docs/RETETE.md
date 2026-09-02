# Rețete — agent-governance

## Test hook SubagentStop
Agent de probă în `~/.claude/agents/` (sonnet, effort low, maxTurns 6, fără Bash/Edit/Write). Prompt: „scrie ~3.000 caractere; dacă ești blocat, comprimă și scrie pe primul rând COMPRIMAT DUPĂ BLOCARE". Verdict = raportul începe cu marcajul. Forma de block: `{"hookSpecificOutput":{"hookEventName":"SubagentStop","decision":"block","reason":"…"}}`. Șterge agentul după test.

Prag per agent (v1.5): implicit 2.000 caractere, 6.000 pentru agenții al căror nume începe
cu `explorer-max` (celule A/B cu raport lung). Payload-ul SubagentStop nu conține
`agent_type` — se deduce din `agent-<agent_id>.meta.json`, fișierul soră al transcriptului
agentului din același `subagents/`, cheia `agentType`.

## Regenerare metrics-local după schimbare de prețuri
Pentru fiecare `metrics-local/*.json` iei `path` (jsonl), apoi:
```
python3 tools/session_metrics.py <căi…> --json --md --out-dir metrics-local
python3 tools/session_metrics.py --trends metrics-local
```
Notele `/rate` se păstrează automat. Verifici numărul de JSON cu `quality` înainte/după.

## Test hook-uri și /rate
`bash hooks/test-hooks.sh` — 39 cazuri offline, exit 0. `/rate` potrivește nota după
basename-ul cwd și timpul sesiunii: din alt director nu se lipește; două sesiuni pe același
proiect → nota merge la prima închisă; în worktree notează cu
`python3 tools/session_metrics.py --rate <nume> N`.

## Regenerare TRENDS și invariante
`python3 tools/session_metrics.py --trends metrics-local/` (rulează întâi refresh_versions, deci schimbarea lui `from` în `tools/versions.json` re-etichetează sesiunile). Invariante de verificat după o schimbare în zona TRENDS: Σ actual pe versiuni = Corpus; ultimul `saved cumulative` = Corpus saved; Σ familii = Σ coduri = waste versiune; `wasted %` sesiune = `postmortem.wasted_pct_of_main_input` din JSON. A doua rulare trebuie să dea `TRENDS.md` identic (idempotent).

## Editare config live când clasificatorul blochează
Ordinea: agent (SendMessage/brief) → dacă rămâne blocat, `python3 - <<'EOF'` din main care
rescrie fișierul cu `pathlib` (rescriere completă, nu `sed -i`) → dacă tot nu trece, Vali
editează manual. Verificare de împăturire după orice editare a `~/.claude/CLAUDE.md`:
`awk 'length > 100' ~/.claude/CLAUDE.md | wc -l`.

## Stare din transcript, nu din fișier (read-mare, test-hooks)
`hooks/read-mare.sh` nu ține stare într-un fișier separat: citește transcriptul JSONL al
sesiunii curente la fiecare apel — apelul curent de `tool_use` e deja scris în jsonl, deci
e sărit după `tool_use_id` ca să nu se autoblocheze. Regula 0 (deny pe `/tool-results/`) se
aplică tuturor; regulile a-c sunt doar pentru sesiunea main. `hooks/test-hooks.sh` rulează
aceeași logică offline, cu transcripte JSONL sintetice pe stdin, fără rețea și fără Claude.

## Curățare comentarii-bloc într-un proiect (scripter-complex)
Se rulează din repo-ul proiectului. Pas 0 (Fable): `grep -rnE "^\s*(//|/\*|\*|#|<!--)" src/ | wc -l`
pentru cifra „înainte"; citește `scripts/SCRIPTS.md`. Brief scripter-complex (script
`scripts/comentarii-pointer.py`, argumente `--dry-run`, `--only <fișier>`, `--src src/`):
1) inventar: blocuri de ≥2 rânduri consecutive de comentariu (`//`, `/* */`, `<!-- -->`,
`{/* */}`) per fișier, cu prima linie; 2) extragere: textul fiecărui bloc într-un fișier de
staging `docs/comentarii-extrase.md`, grupat pe fișier sursă, cu ancoră `<fișier>#<n>` și
linia de cod de sub bloc; 3) înlocuire în cod: blocul → un rând
`// 🔴 <prima linie a blocului, ≤80 car.> — PATTERNS «<fișier>#<n>»` (sintaxa comentariului
după extensie; în `.astro` fără `<`/`>` în comentarii — PATTERNS al proiectului interzice);
4) verificator: al doilea `--dry-run` raportează 0 blocuri, `npx astro check` (sau
`tsc --noEmit`) exit 0, a doua rulare = 0 schimbări. Definiția de complet în cifre: n
fișiere, 234 blocuri → 0. Pasul 2 (implementer sau scribe, brief separat): condensează
`docs/comentarii-extrase.md` în secțiuni reale din PATTERNS.md/DECIZII.md (2–5 rânduri
fiecare), rescrie pointerele cu numele secțiunii reale, șterge staging-ul. Auditul citește
doar `--dry-run`-ul de după și `git diff --stat`. De ce din proiect, nu din
agent-governance: CLAUDE.md-ul proiectului se încarcă, PATTERNS/DECIZII sunt ținta,
`scripts/SCRIPTS.md` e al proiectului, hook-ul și analizorul loghează pe cwd.

## Experiment celule — evaluarea unui lot
S = `~/.claude/projects/-home-vali-workflow-proiecte-agent-governance/<sesiune>/subagents`
(lot 1 = `eb3b7cff-2e84-44ec-b9de-fe02fa88366c`; lots 2–4 = `1582af01-4db0-4d07-8298-10b83d183134`; fiecare lot nou adaugă `--subagents-dir` al
sesiunii lui). R = `metrics-local/experiments/simplu/r<k>`. Pași:
1. `python3 tools/cell_metrics.py --subagents-dir S… --first-run k --min-calls 2 --exclude-agent <id din
   r2/EXCLUDE.txt>… --dump-reports R/rapoarte`
2. `node scripts/evalueaza-simplu.mjs /home/vali/workflow/experimente/simplu/<cell>-r<k>
   --report R/rapoarte/<cell>-r<k>.md --json R/<cell>-r<k>.json` × 4 (câte o dată per celulă)
3. `python3 tools/cell_metrics.py --subagents-dir S… --first-run k --min-calls 2 --exclude-agent … \
   --results-dir R --md --json --out-dir R`
4. Auditor (Brief 4 din plan) → `R/audit.md`.

Verificatorul văzut de celule = `scripts/verifica-simplu.mjs` (doar I1–I8); capcanele T1–T5
sunt doar în `scripts/evalueaza-simplu.mjs`, nu se expun celulelor.
În fish, `--exclude-agent` se dă repetat direct în comandă, nu printr-o variabilă cu spații
(argparse îl vede ca un singur argument). `--results-dir` trebuie să conțină JSON-urile
TUTUROR rundelor din sesiune (copiază `r2/*.json` în `r3/`, etc.), altfel status `-`.

## Smoke hook-uri v1.6 și reluarea lotului
Smoke, sesiune NOUĂ, în ordinea asta:
1) `cat tools/session_metrics.py` din main → deny „>300 lines in main → explorer";
   `sed -n '1,40p' tools/session_metrics.py` → trece.
2) Ceri main-ului să scrie 30 de linii cu Write în `docs/smoke.md` → deny „>20 lines from
   main → scribe/implementer".
3) Stagiere într-o comandă SEPARATĂ: `touch smoke.mjs && git add smoke.mjs`, apoi
   `git commit -m smoke` singur; în auto mode NU apare întrebare — verdictul se citește din
   transcript: `grep -c '"permissionDecision\": \"ask' ~/.claude/projects/-home-vali-workflow-proiecte-agent-governance/<session-id>.jsonl`
   (session-id = fișierul `/tmp/claude-hooks/live-<sid>`); apoi
   `git reset --soft HEAD~1 && git reset smoke.mjs && rm smoke.mjs`.
4) 4 explorer-i rulează `python3 -c "import time; time.sleep(180)"` apoi răspund „ok";
   verifici `wc -l /tmp/claude-hooks/live-<sid>` = 4 înainte de al 5-lea; al 5-lea trece în
   auto mode, „ask"-ul se vede în transcript (același grep, PreToolUse:Agent).
5) `ls /tmp/claude-hooks/live-* /tmp/claude-hooks/audit-ok-*` după un audit cu VERDICT: OK
   → markerul există.

Notă: în auto mode „ask" = decide clasificatorul, nu Vali; doar „deny" oprește. Decizia în
DECIZII «Autoritate hook + commit gate (31.08.2026)».

Dacă un hook blochează greșit o comandă uzuală: nu-l dezactivezi, notezi comanda în
HANDOFF «Neclar».

Apoi pașii 1–7 din docs/experiments.md «simplu — lessons from r1 and how to resume».

## Experiment ferestre: orchestrator la două efforturi
Prompt scris orb în `task.md`, în vocea lui Vali, fără soluție. Pornești două sesiuni din
același commit: `claude --effort <x> --permission-mode plan` (o dată per effort). La orice
întrebare a orchestratorului: „decide tu și notează ipoteza". `ExitPlanMode` se respinge —
ieși cu `/exit`, nu cu kill. Planurile ajung în `~/.claude/plans/`; le găsești cu
`grep -o '/home/vali/.claude/plans/[^"]*\.md' <sesiune>.jsonl` și le copiezi orb ca
plan-K/plan-M + un `mapping.txt` (scris în bash, nu în fish — sintaxa diferă). Auditorul
judecă după rubrica din `docs/experiments.md`; Vali alege effort-ul câștigător fără să vadă
maparea K/M → effort real.

Capcană: plan mode blochează `Write` la subagenți (explorer nu poate scrie `docs/dosar/`
în plan mode) — dosarul se scrie după `ExitPlanMode`, sau explorer-ul doar raportează.

## Migrarea numelor de sesiune
`tools/session_metrics.py --migrate-names DIR [--yes]`: rulezi mai întâi fără `--yes`
(dry-run), verifici lista, apoi cu `--yes`. Backup-ul îl faci TU înainte:
`cp -r metrics-local metrics-local.bak-<dată>` (scriptul nu face backup; `.gitignore` îl acoperă). Idempotent — o a doua rulare pe recorduri deja redenumite nu schimbă
nimic. Nume noi: `<zi>-HHMM-<proiect>` (HHMMSS doar la coliziune). Recordurile vechi NU
primesc câmpurile noi (effort, main $ %, scripter) automat — necesită re-analiză explicită
cu `--json --md --out-dir metrics-local` (vezi PATTERNS «Câmpuri noi în recorduri vechi»).
Pentru TRENDS cronologic după migrare: `--trends`.
