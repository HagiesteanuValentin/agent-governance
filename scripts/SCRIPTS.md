# Scripts — agent-governance

Un rând per script; scripterul îl ține la zi; orchestratorul îl citește înainte de un brief de scripter.

| script | ce face | fișiere afectate | argumente | adaptare: ușoară/medie/grea — ce se schimbă | o dată/refolosibil |
| --- | --- | --- | --- | --- | --- |
| `scripts/verifica-debloat.sh` | verifică dimensiunile, șirurile interzise și cuvintele-cheie din template-urile CLAUDE.md + injecția orchestrării în hook | `templates/CLAUDE.global.md`, `templates/orchestrare.md`, `hooks/session-start.sh` | niciunul | ușoară — schimbi pragurile și listele de șiruri din capul scriptului | refolosibil |
| `hooks/agenti-vii.sh` + `hooks/test-agenti-vii.sh` | cap de agenți vii per sesiune: start/stop/check, ask la >=4 | `/tmp/claude-hooks/live-<session_id>` (doar stare) | `start\|stop\|check`, env `AGENTI_VII_CAP` `AGENTI_VII_STALE` `CLAUDE_HOOKS_DIR` | ușoară — capul și vechimea vin din env | refolosibil |
| `hooks/context-agent.sh` + `hooks/test-context-main.sh` | buget de context pentru main și pentru agenți, contor de verificări | doar `/tmp/claude-hooks` (markere + log) | `--scope main\|agent` `--warn N` `--deny N` `--any-type` `--praguri-tip` | ușoară — `TYPE_LIMITS`, `AGENT_PREFIXES`, `SAFE_SUBAGENTS`, `PLAN_DIR` din capul scriptului | refolosibil |
| `hooks/commit-gate.sh` + `hooks/test-commit-gate.sh` | ask la `git commit` pe .ts/.js/.mjs/.astro fără audit CONFORM | `/tmp/claude-hooks/audit-ok-<session_id>` (doar citire) | `--extensii ts,tsx,js,jsx,mjs,astro`, env `CLAUDE_HOOKS_DIR` `COMMIT_GATE_GIT` | ușoară — extensiile din argument, motivul din `REASON` | refolosibil |
