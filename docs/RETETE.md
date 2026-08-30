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
