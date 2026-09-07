# Orchestration v1.8 — delta on top of orchestrare.md (advisor + effort phases)

Drop this into `~/.claude/orchestrare-v17.md`; `hooks/session-start.sh v17` injects it. The
base rules in `orchestrare.md` still apply; this file only adds/overrides what follows.

## Advisor trigger — at PLAN time, before ExitPlanMode
Call the `advisor` Agent MANDATORY when any: (a) ≥2 briefs carry JS/TS logic · (b) hooks,
live settings/config, data migration · (c) the user writes risky/complex/advisor · (d) any
implementer-complex, implementer-max, or scripter-complex brief · (e) ≥3 briefs · (f)
implementers in parallel or worktree. Optional only at 1–2 scribe/implementer-sonnet/simple
implementer briefs. Print one line in main: `advisor: <reason a/b/c/d/e/f>`.

## Advisor flow
Agent advisor -> report -> main applies the CHANGES to the plan file under
`~/.claude/plans/` (Edit, targeted lines only) -> if NEED -> explorer -> SendMessage advisor
with the answer (at most 2 rounds) -> ExitPlanMode. On round 2 the advisor rereads the
updated plan; the cost is negligible next to a missed bug.
From IMPROVEMENTS, main applies only the lines that add no file/brief (same as CHANGES);
lines marked "scope+" are not applied — list them in one line for the user at ExitPlanMode.

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
HARD CAP: at most 6 live agents at once, any type (was 4) — the user's call, 02.09: main's
context is small, parallelizing helps. The plan-time conditions (disjoint file lists, one
build, no cross-brief dependency) still apply; do not parallelize for the count's sake.

## Effort per phase
Main effort per phase: `medium` in plan mode, `low` after ExitPlanMode. Only the user changes the
effort with `/effort`; the `effort-phase.sh` hook (guard `~/.claude/v17-effort-auto`) writes
the target into settings and warns on mismatch. Main, first line after ExitPlanMode approved:
«You: /effort low»; on EnterPlanMode: «You: /effort medium». Resumed 2026-09-05: Claude Code
2.1.260 no longer invalidates the cache on `/effort`. Escalation = advisor or re-entering
plan mode. Reason: `DECIZII «v1.8 — efort pe faze reluat»`.
In /polish and /refine the command itself runs the hook at step 0 (medium) and 5 (low); same
«You: /effort».
