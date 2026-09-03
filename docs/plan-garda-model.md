## Status 03.09

Brief 1, 2, 4 LIVRATE (neauditate, necomise). Teste: test-model-gate 25/25, test-hooks 57/57, test-comentarii-cod 12/12, toate suitele exit 0.

RĂMAS:
- audit pe 1+2+4 (auditor, diff mare)
- `export GOV_MODEL=claude-fable-5-1` în hooks/test-hooks.sh
- Brief 3 (read-mare) și Brief 5 (bash-mare) în paralel
- Brief 6 (docs + sync live doar pe fișierele atinse)
- commit

Briefurile extrase sunt în /tmp/claude-1000/scratch/brief-h3.md și brief-h5.md (pot dispărea la reboot; sursa e planul de mai jos). `~/.claude/settings.json` are deja comentarii-cod pe PreToolUse (activ după restart; backup /tmp/claude-1000/scratch/settings.bak.json).

---

# Plan — gardă de model (pe Opus gărzile din main tac) + 4 fix-uri pentru ineficiențele workerilor

## Context
- Azi niciun hook nu știe modelul: stdin-ul hook-urilor n-are câmp `model`; cheia
  `claude-fable-5-1` din settings e hardcodată. Pe Opus 5 direct, write-mare (20 linii),
  read-mare, bash-mare, brief-mare, agenti-vii și commit-gate rămân active și forțează delegarea.
- Sursa modelului: mesajele assistant din transcript au `"model":"claude-…"` (verificat);
  `~/.claude/settings.json` are `"model": "claude-fable-5-1[1m]"` (linia 5). La SessionStart
  transcriptul e gol → fallback pe settings.
- Ineficiențe promo-site 02.09 (22 agenți): agent re-citește propria scriere ×11, bloc de
  comentarii ×8, verificare sterilă ×5, PNG-uri de 500k caractere citite direct în main ×8.
  `read-mare.sh` urmărește doar `Read` (L50/L67), nu și Write/Edit; `comentarii-cod.sh` e
  PostToolUse și doar loghează (L214); `bash-mare.sh` n-are numărare de comenzi repetate.
- Decizia lui Vali (03.09): pe Opus tac TOATE gărzile de main, inclusiv commit-gate, și
  SessionStart nu mai injectează blocurile ORCHESTRATION; rămân metrics, log-ul de comentarii,
  gărzile pe agenți. Fix-urile alese: toate 4.
- Model de agent: `implementer-complex` (logică bash+python pe mai multe hook-uri, verificator =
  teste). Efort main: medium constant (experiment oprit azi).
- advisor: DA — trigger (b), atinge hook-uri și settings live.
- Teste: fiecare brief scrie în FIȘIERUL LUI de test (precedent: `hooks/test-commit-gate.sh`,
  `hooks/test-agenti-vii.sh`), ca briefurile din valul 2 să nu se atingă. `test-hooks.sh`
  (51 de cazuri, helper `call(hook, payload)` L94, `sub_fixture` L73) rămâne verde.
- Live: `~/.claude/hooks/*.sh` sunt copii identice ale repo-ului; sync repo→live la final
  (niciodată invers). `~/.claude/settings.json` se editează doar de agent (Brief 4), o singură
  cheie nouă.

## Contract comun — helper `hooks/main-model.sh` (Brief 1)
- Apel: `bash hooks/main-model.sh "<transcript_path>"` → printează modelul pe stdout, exit 0.
- Ordine: (1) env `GOV_MODEL` dacă e setat (pentru teste); (2) ultima linie `"type":"assistant"`
  din transcript cu `"model":"claude-…"` (`tac | grep -m1`, NU `tail -c`: imun la tool_result-uri
  care conțin textul `claude-opus`); ignoră `<synthetic>`;
  (3) `.model` din `~/.claude/settings.json` (fără sufixul `[1m]`); (4) `unknown`.
- Semantica gărzii: hook-ul de main acționează DOAR când modelul conține `fable` sau `mythos`;
  altfel `exit 0` tăcut. `unknown` = tratat ca Fable (fail-closed: mai bine o gardă în plus).
- Inserție: imediat după decizia main-vs-agent, DOAR pe ramura main; ramura de agent nu se
  schimbă. Un singur rând-pointer în cod: `🔴 gardă de model doar pe main — PATTERNS «Modelul
  în hook-uri»`.

## Brief 1 — implementer-complex: helper + gardă în session-start, write-mare, brief-mare
Scop: pe Opus, SessionStart nu injectează ORCHESTRATION/v17 și write-mare/brief-mare tac în main.
Fișiere: `hooks/main-model.sh` (nou, ≤30 linii), `hooks/session-start.sh` (blocurile
ORCHESTRATION și v17 sar când modelul nu e Fable; HANDOFF și rândul de efort rămân; fallback pe
settings pentru că transcriptul e gol), `hooks/write-mare.sh` (după L28), `hooks/brief-mare.sh`
(după L8), `hooks/test-model-gate.sh` (nou; cazuri: fixture jsonl cu `claude-opus-5` → write-mare
nu dă deny la 50 de linii în main; cu `claude-fable-5-1` → deny; `GOV_MODEL=claude-opus-5` →
session-start nu conține `=== ORCHESTRATION`; agent pe Opus → gărzile de agent neschimbate;
fără transcript + settings fable → Fable).
Complet: `bash hooks/test-model-gate.sh` exit 0 cu ≥6 cazuri; `bash hooks/test-hooks.sh` exit 0;
`echo '{"transcript_path":"/nonexistent"}' | bash hooks/write-mare.sh` nu crapă (exit 0).
Interzis: commit, push, editarea `~/.claude/`, citirea DECIZII/RETETE integral.

## Brief 2 — implementer-complex (același agent, prin SendMessage sau brief nou): gardă în restul
Fișiere: `hooks/agenti-vii.sh` (L78/87, ramura main), `hooks/commit-gate.sh` (L112, ramura main),
`hooks/read-mare.sh` (doar ramura main, L93/95), `hooks/bash-mare.sh` (doar ramura main, L37-38),
`hooks/test-model-gate.sh` (adaugă câte un caz Opus-main-tace + Fable-main-deny per hook).
Complet: `test-model-gate.sh` exit 0 (≥14 cazuri), `test-hooks.sh`, `test-commit-gate.sh`,
`test-agenti-vii.sh`, `test-read-mare-agent.sh` toate exit 0. Aceleași interdicții.
Rulează DUPĂ Brief 1 (depinde de helper). Audit Brief 1+2 împreună.

## Valul 2 — trei briefuri în PARALEL (liste de fișiere disjuncte, fără build)

### Brief 3 — implementer-complex: read-mare — recitire după propria scriere + imagini în main
Fișier: `hooks/read-mare.sh`, `hooks/test-read-mare-agent.sh` (extins).
(a) Agenți: la PreToolUse Read pe calea X, dacă în transcriptul agentului ultimul eveniment pe X
e un Write/Edit/MultiEdit al lui (fără Read ulterior) → deny, mesaj: „ai scris X; nu-l reciti;
verifică punctual cu grep -n sau sed -n pe interval". Read cu `offset`/`limit` pe ≤60 de linii
e permis (verificare punctuală). Nu schimbă logica existentă de re-citire (L50/L67).
(a') Poziție în cod: după L97 (ramura implementer/scripter/cell-) și ÎNAINTE de L105 (azi L105
lasă orice Read cu offset/limit; excepția nouă e doar ≤60 de linii). Nu numără Edit-urile cu
`is_error` (Edit picat pe «file modified since read» / «old_string not found» cere Read legitim).
Contorul se resetează dacă după Write/Edit vine un Bash care conține basename(X) în comandă
(build/test pe fișier).
(b) Main pe Fable: Read pe `.png/.jpg/.jpeg/.webp/.gif` (lista IMG L32) cu fișier >200 KB → deny,
mesaj: „imaginea o vede explorer sau design-lead și raportează în text". Sub 200 KB rămâne cum e.
Complet: `test-read-mare-agent.sh` exit 0 cu ≥7 cazuri noi (deny după Write; permis cu offset/limit
≤60; permis după Edit cu is_error; permis după Bash cu basename în comandă; imagine 300 KB main →
deny; imagine 50 KB main → nu; imagine 300 KB agent → nu);
`test-hooks.sh` exit 0.

### Brief 4 — implementer-complex: comentarii-cod → PreToolUse, deny la agenți
Fișiere: `hooks/comentarii-cod.sh`, `hooks/settings.example.json`, `~/.claude/settings.json`
(mută intrarea comentarii-cod de la PostToolUse la PreToolUse, matcher `Edit|Write|MultiEdit`,
nimic altceva atins; settings live se reîncarcă abia la restart), `hooks/test-comentarii-cod.sh`
(nou), `hooks/test-hooks.sh` DOAR cazurile comentarii-cod: L265 «sub-agent flagged too» așteaptă
`context` → devine deny; L47 acceptă MultiEdit; L214 hookEventName → PreToolUse.
Logică: detecția blocului ≥2 rânduri (L99-181, prag L187) se aplică pe `tool_input`
(`new_string` / `content`) în loc de rezultatul post-edit. Agent (`agent_id` sau `subagent` în
transcript_path) → deny DOAR pe `max_block ≥ 2` sau linie lungă; criteriul RATIO (25% din ≥5
rânduri) rămâne `additionalContext` și la agenți (2 pointere legitime în 6 rânduri nu dau deny).
Deny cu mesajul convenției (un rând-pointer `🔴 … — DOC
«secțiune»`). Main → `additionalContext` de avertizare, ca azi. Log-ul (L212/218) rămâne.
Complet: `test-comentarii-cod.sh` exit 0 (≥6 cazuri: agent bloc 2 rânduri → deny; agent pointer
1 rând → allow; main bloc → allow + context; Write cu content bloc → deny; MultiEdit → deny;
edit fără comentarii → allow); `test-hooks.sh` exit 0; `python3 -c 'import json;
json.load(open("/home/vali/.claude/settings.json"))'` exit 0; `diff <(jq .hooks
settings.example.json) <(jq .hooks ~/.claude/settings.json)` doar diferențele deja existente.

### Brief 5 — implementer-complex: bash-mare — avertizare la verificare sterilă (agenți)
Fișiere: `hooks/bash-mare.sh`, `hooks/test-bash-mare.sh` (nou).
Logică: intră ÎNAINTE de L38 (unde bash-mare iese pe agenți) și citește transcriptul agentului ca
read-mare L102-104. La PreToolUse Bash în agent, normalizează comanda (trim, spații multiple → unul) și
numără în transcriptul agentului rulările identice de după ultimul Edit/Write/MultiEdit. A 3-a
rulare fără edit între ele → `additionalContext`: „a 3-a rulare identică fără nicio modificare;
ori repari, ori raportezi neclar/riscant". Nu deny. Fără schimbare pe praguri (L3-L5).
Complet: `test-bash-mare.sh` exit 0 (≥4 cazuri: 2 rulări → tăcut; a 3-a → context; Edit între →
contor resetat; main → tăcut); `test-hooks.sh` exit 0.

## Brief 6 — scribe: docs + sync live
După audit OK pe toate: `docs/PATTERNS.md` secțiune nouă «Modelul în hook-uri» (sursa: transcript
apoi settings; `--model` din CLI nu se vede în settings → gardă activă; PreToolUse pentru deny,
PostToolUse nu poate refuza); `docs/DECIZII.md` «Gardă de model + fix-uri workeri (03.09.2026)»
cu cifrele din Context; `README.md` un rând per hook nou/schimbat; `~/.claude/orchestrare.md`
+ `templates/orchestrare.md`: rândul „Doar când modelul e Fable" devine „Gărzile de main și
blocul ăsta apar doar pe Fable (hook `main-model.sh`)"; sync DOAR pentru fișierele atinse
(main-model, session-start, write-mare, brief-mare, agenti-vii, commit-gate, read-mare, bash-mare,
comentarii-cod), apoi `diff -q` pe fiecare. NU `cp hooks/*.sh`: live diferă azi în
bash-mare/brief-mare (RO) și `session-metrics.sh` live are căi hardcodate — cp orb rupe metrics la
SessionEnd. Pentru brief-mare și bash-mare scribe portează hunk-ul în versiunea RO, nu copiază.

## Verificare finală (main)
- `git diff --stat` după fiecare val; auditor pe Brief 1+2, apoi pe fiecare din 3/4/5 (brief cu
  brief), apoi pe Brief 6.
- `bash hooks/test-hooks.sh && bash hooks/test-model-gate.sh && bash hooks/test-read-mare-agent.sh
  && bash hooks/test-comentarii-cod.sh && bash hooks/test-bash-mare.sh` — toate exit 0 (rulează
  auditorul, raportează cifrele).
- Rămâne activ pe Opus, intenționat: `context-agent --scope main` (deny la 220k e plafon de
  siguranță, nu regulă de orchestrare). Fail-open cunoscut: `--resume` al unei sesiuni Opus reluate
  pe Fable și `--model opus` din CLI cu settings pe Fable — documentat în PATTERNS (Brief 6).
- După Brief 4, settings.json cere restart de sesiune ca să se aplice PreToolUse.
- Pe viu: următoarea sesiune Opus → SessionStart fără ORCHESTRATION, Write de 30 de linii permis;
  sesiune Fable → identic cu azi.
- Commit după audit OK: „hooks: gardă de model (Opus fără gărzi de main) + read-mare reread/imagini,
  comentarii-cod deny agenți, bash-mare verificare sterilă".
