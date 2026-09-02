# v1.7 experimental — advisor pe Fable high + efort main pe faze

## Context
- Main azi: Fable 5.1 medium (`settings.json` → `modelSettings.claude-fable-5-1.effortLevel: medium`). Date proprii: 2 sesiuni medium fără flag-uri de orchestrare (una 5/5); singurul 3/5 e pe high. T-metrics are 1 pereche; concluzia cere ≥3.
- Scop v1.7: (1) main medium la plan; (2) agent nou `advisor` (Fable 5.1 high, doar citire) chemat DOAR la planuri complexe/riscante, cu context minim, raport ≤1,5k, niciodată planul rescris; (3) după aprobarea planului main trece pe low; la neclarități întreabă advisor-ul (SendMessage reia agentul cu istoric — confirmat în docs sub-agents).
- Plafon hook: 10.000 caractere PER hook-comandă (confirmat docs + empiric: sesiunea asta a primit orchestrare 9.670 B și HANDOFF 2.314 B integral). orchestrare.md rămâne neatins; regulile v1.7 merg într-un fișier nou injectat de un al treilea hook.
- Mecanisme verificate în docs: frontmatter `model: fable` + `effort: high` acceptate; subagenții pot lansa subagenți (adâncime 3) — NU folosim: advisor cere prin linii `NEED:` (decizia ta); efortul main îl schimbă doar userul (`/effort`), settings sau env — nu există tool pentru model.
- Decizii tale: explorer prin orchestrator; trigger = criteriu + la cerere; efort low după aprobare, automatizat cât se poate (vezi «Efort pe faze»).

## Design

### Agent `advisor` (`agents/advisor.md` EN, `~/.claude/agents/advisor.md` RO)
- Frontmatter: `name: advisor`, `model: fable`, `effort: high`, `maxTurns: 40`, `tools: Read, Grep, Glob, Bash` (fără Edit/Write/Agent). Descriere ≤300 B.
- Input (în prompt-ul Agent, ≤8 rânduri): calea planului · scopul lui Vali în 1–3 rânduri, în cuvintele lui · numele secțiunilor DECIZII/PATTERNS citate în plan · „NU rescrii planul; NU citești DECIZII/RETETE integral". Fără HANDOFF, fără conversație, fără regulile de orchestrare. Fișierele din căile din plan le citește singur, în contextul LUI.
- Output (fix, ≤1.800 caractere): `VERDICT: GO | GO cu schimbări | NO-GO` · `SCHIMBĂRI:` ≤5 rânduri «Brief N — ce — de ce» · `RISC:` ≤3 · `EDGE:` ≤3 · `NEED:` ≤3 întrebări pentru explorer (doar dacă nu poate decide). Fără cod, fără brief-uri rescrise.
- Rol: adversar — caută ce pică, nu confirmă. Pe implementare răspunde la o întrebare punctuală (≤600 caractere).

### Reguli v1.7 (`~/.claude/orchestrare-v17.md` RO ≤3.500 B, `templates/orchestrare-v17.md` EN)
- Trigger advisor, LA PLAN, înainte de ExitPlanMode: (a) ≥2 briefuri cu logică JS/TS, sau (b) atinge hook-uri, settings/config live, migrare de date, sau (c) Vali scrie «riscant/complex/advisor». Altfel nu. Un rând în main: `advisor: <motivul (a/b/c)>`.
- Flux: Agent advisor → raport → main aplică SCHIMBĂRILE în planul din `~/.claude/plans/` (Edit, punctual) → NEED → explorer → SendMessage advisor cu răspunsul (max 2 runde) → ExitPlanMode. Advisor-ul NU primește planul a doua oară integral, doar diff-ul schimbărilor dacă îl cere.
- Plafoane: 1 advisor per plan, ≤3 SendMessage pe implementare; intră în cap-ul de 4 agenți vii și în bugetul de 3 explorer. Peste → AskUserQuestion.
- Main pe low (implementare): NU citește `git diff` direct niciodată — auditor la orice diff. Advisor OBLIGATORIU (nu la apreciere) când: a 2-a ABATERI pe același brief · raport de agent cu «neclar/riscant» care atinge logică · verificator picat după SendMessage · orice escaladare la implementer-max. SendMessage advisor cu întrebarea + căile; main nu decide singur. Restul regulilor din orchestrare.md rămân.
- Paralelism: HARD CAP 4 → 6 agenți vii (decizia lui Vali, 02.09: context main mic, paralelizarea ajută). Condițiile de la plan rămân (liste de fișiere disjuncte, un singur build, fără dependențe); nu paralelizezi „de dragul cifrei". Se schimbă în `orchestrare.md` («maxim 4» → «maxim 6», același număr de bytes), în `templates/orchestrare.md` (EN) și pragul `parallel_over_cap` din `tools/session_metrics.py` (4 → 6).
- Efort pe faze: plan = medium, implementare = low. Mecanismul: secțiunea următoare.

### Efort pe faze — automatizare (docs: hook-urile primesc `effort.level` + `permission_mode` în stdin la PostToolUse; reîncărcarea settings.json pe viu NU e documentată → se testează)
- `hooks/effort-phase.sh <low|medium|check>`, gardă: fișierul `~/.claude/v17-effort-auto` există = activ (experimentul se oprește cu `rm`).
- `PostToolUse` matcher `ExitPlanMode` → `effort-phase.sh low`: scrie atomic (tmp+mv, python3) `modelSettings.claude-fable-5-1.effortLevel=low` în `~/.claude/settings.json` și injectează `effort: settings→low (era <effort.level>)`. `PostToolUse` matcher `EnterPlanMode` și `SessionStart` (în `session-start.sh rules`) → `medium`.
- Confirmare automată: `PostToolUse` matcher `.*` → `effort-phase.sh check`: compară `effort.level` din stdin cu valoarea din settings; la nepotrivire, o singură dată per sesiune (fișier de stare `$CLAUDE_JOB_DIR`/`/tmp/effort-phase-<session_id>`), injectează `⚠ effort efectiv=<x>, settings=<y> → Tu: /effort <y>`. La potrivire, tăcere.
- Regulă main (în orchestrare-v17): după aprobarea planului, dacă apare rândul ⚠ → se oprește cu «Tu: /effort low, apoi go»; dacă nu apare → continuă. Deci: dacă reîncărcarea pe viu merge, e complet automat; dacă nu, ai un singur tur manual și sesiunea următoare pornește oricum corect.
- Ce NU se poate: modelul nu are tool pentru efort; nu există eveniment „plan approved" în docs — matcher-ul pe numele tool-ului `ExitPlanMode` e ipoteza, verificată în Brief 3.

## Briefuri

### Brief 1 — Repo (EN): agent, template, hook, docs — `implementer-sonnet`
Fișiere: `agents/advisor.md` (nou), `templates/orchestrare-v17.md` (nou), `templates/orchestrare.md` (cap 4→6, un cuvânt), `tools/session_metrics.py` (pragul `parallel_over_cap` 4→6, o linie; NU alt câmp nou, ca să nu ceară re-analiză), `hooks/session-start.sh` (arg `v17` → cat fișierul v17; + rând `effort main (settings): <x>` citit din settings cu python3/jq), `hooks/effort-phase.sh` (nou, moduri `low|medium|check`, gardă pe fișierul-flag, idempotent, `bash -n`), `scripts/verifica-debloat.sh` (gardă ≤3.500 B pe orchestrare-v17.md), `versions.json` (v1.7, `from` = ora locală a activării live, o pune Brief 2), `docs/DECIZII.md` secțiune nouă «v1.7 — advisor + efort pe faze» (≤5 rânduri), `docs/experiments.md` secțiune «T-v17» (design: benchmark $ main plan vs implementare, /rate, ≥3 sesiuni, comparat cu sesiunile medium-integral; confound: task-uri diferite).
Complet: `bash -n` pe cele 2 hook-uri = 0; `bash hooks/session-start.sh v17 | wc -c` ≤ 3.600; `effort-phase.sh check` pe un transcript de test fabricat dă rândul ⚠ la nepotrivire și nimic la potrivire; markere EN.
Interzis: commit, push, editare în `~/.claude/`.

### Brief 2 — Live (RO): `~/.claude/` — `implementer-sonnet` (după auditul Brief 1)
Fișiere: `~/.claude/agents/advisor.md` (traducere RO), `~/.claude/orchestrare-v17.md` (RO), `~/.claude/orchestrare.md` (DOAR «maxim 4» → «maxim 6» pe rândul HARD CAP; `wc -c` rămâne 9.670), `~/.claude/hooks/session-start.sh` și `~/.claude/hooks/effort-phase.sh` (identice cu repo), `~/.claude/settings.json` (al 3-lea SessionStart `session-start.sh v17`; PostToolUse ExitPlanMode/EnterPlanMode; UserPromptSubmit check — DOAR dacă mecanismul e confirmat), `~/.claude/v17-effort-auto` (flag), `versions.json` din repo (`from` = acum, local).
Complet: `python3 -c 'import json;json.load(open(...settings.json))'` = 0; `bash ~/.claude/hooks/session-start.sh rules | wc -c` ≤ 10.000 și `... v17 | wc -c` ≤ 3.600; `wc -c ~/.claude/orchestrare.md` = 9.670 (doar cifra 4→6 schimbată); `diff` hook-uri repo vs live = gol.
Interzis: commit, push, orice editare în repo în afara versions.json.

### Brief 3 — Test pe viu (main, fără agent nou de implementare)
1. Agent `advisor` apare după ~1–2 min (fără restart). Lansare pe planul ĂSTA: calea planului + scopul; se verifică formatul raportului (≤1,8k, secțiunile fixe inclusiv IMPROVEMENTS, fără plan rescris).
2. Sesiune nouă: SessionStart injectează orchestrare + HANDOFF + v17 integral și rândul de efort.
3. Efort: task mic în plan mode → aprobare → se notează dacă hook-ul ExitPlanMode a tras (rândul `effort: settings→low`) și dacă rândul ⚠ apare la următorul tool call (= fără reîncărcare pe viu). Rezultatul intră în DECIZII «v1.7» ca fapt măsurat, nu presupus. `session_metrics.py` pe transcript confirmă `effort_changes`.

## Verificare finală
- Audit: auditor pe Brief 1 și Brief 2 (peste 3 fișiere).
- `git status --short`: intră doar fișierele din briefuri; `scripts/cell-baseline-simplu.txt` rămâne netrackuit.
- Commit după audit CONFORM: «v1.7: advisor (Fable high, doar citire) + orchestrare-v17 + efort pe faze». HANDOFF rămâne pentru `/handoff`.

## Stare (02.09, după commit 2f4e766)
- Brief 1 + 2 livrate și auditate OK; advisor testat pe planul ăsta (GO cu schimbări, 3 aplicate). Hook EnterPlanMode → medium: CONFIRMAT pe viu.
- Rămâne Brief 3 pas 3: acest ExitPlanMode e testul (respingere, apoi aprobare); nicio altă schimbare de cod.

## Riscuri / limitări
- Nu există măsurătoare că main pe low orchestrează corect; de aceea T-v17 cere ≥3 sesiuni și `/rate` de la tine.
- Advisor high: ≈ $1–3 per apel (plan + fișiere); plafonul de 1/plan îl ține sub control.
- Restart omoară advisor-ul; pe implementare se relansează cu calea planului + întrebarea.
- Dacă hook-ul scrie settings.json cât Claude Code îl scrie (ex. `/effort`), poate pierde o schimbare — scrierea e atomică (tmp + mv).
