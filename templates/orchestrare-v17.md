# Orchestration v1.7 — delta on top of orchestrare.md (advisor + effort phases)

Drop this into `~/.claude/orchestrare-v17.md`; `hooks/session-start.sh v17` injects it. The
base rules in `orchestrare.md` still apply; this file only adds/overrides what follows.

## Advisor trigger — at PLAN time, before ExitPlanMode
Call the `advisor` Agent when: (a) 2 or more briefs carry JS/TS logic, or (b) the plan
touches hooks, live settings/config, or a data migration, or (c) Vali writes
"risky/complex/advisor" in the request. Otherwise, do not call it. Print one line in main:
`advisor: <reason a/b/c>`.

## Advisor flow
Agent advisor -> report -> main applies the CHANGES to the plan file under
`~/.claude/plans/` (Edit, targeted lines only) -> if NEED -> explorer -> SendMessage advisor
with the answer (at most 2 rounds) -> ExitPlanMode. The advisor never gets the whole plan a
second time — only the diff of the changes, and only if it asks for it.
From IMPROVEMENTS, main applies only the lines that add no file/brief (same as CHANGES);
lines marked "scope+" are not applied — list them in one line for Vali at ExitPlanMode.

## Caps
1 advisor per plan; at most 3 SendMessage to it during implementation. It counts against the
live-agent cap and against the 3-explorer budget. Over either -> AskUserQuestion.

## Main in the implementation phase
Main never reads `git diff` directly — the auditor reads every diff. Advisor is MANDATORY
(not optional) when: a brief gets its 2nd DEVIATIONS report in a row · a worker's report has
"unclear/risky" touching logic · the verifier fails again after a SendMessage round · any
escalation to implementer-max. SendMessage the advisor the question plus the file paths; main
does not decide alone. Every other rule in `orchestrare.md` still holds.

## Parallelism
HARD CAP: at most 6 live agents at once, any type (was 4) — Vali's call, 02.09: main's
context is small, parallelizing helps. The plan-time conditions (disjoint file lists, one
build, no cross-brief dependency) still apply; do not parallelize for the count's sake.

## Effort per phase
Main effort = `medium` constant. The phase experiment (plan medium, implementation low) is
STOPPED as of 2026-09-03 — the `~/.claude/v17-effort-auto` guard file was deleted; the hooks
(`hooks/effort-phase.sh`) stay in the code but are inert without the guard. Reason: `DECIZII
«Efort pe faze — oprit»`.
