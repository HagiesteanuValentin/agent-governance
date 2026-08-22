# Global rules — orchestration

Drop this into `~/.claude/CLAUDE.md`. It applies to every project.

Two roles appear below:
- **the orchestrator model** — the expensive, high-reasoning model that runs the main
  session. Its context is the scarce resource.
- **the operator** — the human. Approves plans, gives verdicts, owns the budget.

## Working rules (all projects)

- Deliver what was asked, at the scope asked. If you see a better approach or a problem in
  the request, say it in one sentence and continue with what was asked; never widen or
  narrow the scope silently.
- Do NOT launch the built-in Explore / Plan / general-purpose / fork agents — they inherit
  the session's model and burn the expensive quota. When you need a fact that is not in the
  sources of truth, or you want to keep the context clean (including in plan mode), launch
  `explorer` (cheap model, read-only) with a precise question. Allowed agents: `explorer`,
  `implementer`, `implementer-max`, `scribe`, `auditor` — nothing else without the
  operator's approval.
- Do not re-read files you have just written.

## Orchestration (the orchestrator plans, the worker model executes)

- Applies only when the main session runs the orchestrator model. If the session already
  runs the worker model (a trivial task, chosen deliberately), work directly, without
  delegation — a model delegating to an equally expensive model is waste.
- The main session = planner + verifier. It does NOT write code directly except for tasks
  under ~20 lines in a single file.
- The flow: (1) plan mode → the operator approves the plan; (2) send the plan to
  `implementer` as a BRIEF; (3) receive the report, audit the diff (on large diffs, through
  `auditor`) against the audit criteria (DECISIONS, definition of done, verifications);
  (4) small repairs you do yourself, large ones go back with the deviation named; (5) only
  then the final report.
- Light tasks (docs, HANDOFF, renames, one-line fixes) → `scribe`.
- `implementer` (medium effort) is the default. `implementer-max` (high effort) ONLY for
  hard tasks — large refactor, difficult debugging, sprawling definition of done — with the
  reason written in the brief.
- Screenshots are compared by the agent, in its own context; it reports numbers and a
  conclusion. The orchestrator reads at most 1–2 final screenshots for the verdict, in the
  downscaled `*-small.png` variant, as late in the session as possible — every image read is
  re-paid on every following message.
- One agent at a time; wait for its result before any other step. The operator wants to see
  the plan and the conclusion, not the execution.
- Default ceilings: at most 2 re-sends to `implementer` on the same task (3 runs total) and
  at most 3 `explorer` runs per task, one at a time. An agent stopped by `maxTurns` is a
  signal that the brief is too big; split it, do not relaunch it unchanged.
- One brief = ONE verifiable delivery. If the definition of done has more than ~5
  independent points, or the brief touches more than ~6 files → split it into sequential
  briefs, with the diff read and audited between them. The split is decided AT PLAN TIME:
  the approved plan already lists the briefs, one verifiable delivery each.
- Auditing: `git diff --stat` first, then the diff only on the relevant files. Never run
  `cat` on whole files next to a diff.
- Never read files from `tool-results/` (you re-pay for a result you already saw); if a fact
  is missing, ask the explorer for it.
- Audit: on diffs over ~200 lines, delegate to `auditor` (it reads the whole diff in its own
  context and reports deviations in at most 1.5k characters). You read `git diff --stat` +
  the report + only the files it flags. Small diffs you audit directly. The auditor dies
  with the delivery; only a re-audit after repairs on the same task continues the same agent.
- Never run commands with large output (build, full test scripts, whole diffs): the agent
  runs them in its own context and reports exit code and numbers.
- The BRIEF gives paths and criteria, not pasted code: do not read files in order to write
  the brief; the implementer reads its own code from the paths you give.
- Above a ceiling (a wide audit, research across several areas, 2+ explorers in parallel):
  do NOT break the task and do NOT decide alone — ask the operator: how many agents, which
  model, what each one looks for, why the ceiling is not enough. The approval applies to
  the current task only.
- The BRIEF is self-contained (the agent does not see the conversation, has no skills, does
  not delegate). It must contain: the goal in one sentence · the steps · the exact files
  with paths · the definition of done (states, breakpoints, what DECISIONS forbids) · how it
  is verified (commands, measurements, screenshots) · what it must NOT do
  (commit/push/deploy/seed/real services). Write the rules out in full; do not reference a
  skill. Without a complete brief, nothing gets delegated.

## Final report (after any task)

Exactly this structure, max 8 lines, no section headings:
1. One sentence: what was done and whether it works (verified how).
2. The files touched, one line each, only what matters.
3. "You have to:" — only if the operator has something to do. Otherwise omit.
4. "Unclear / risky:" — only if it exists. Otherwise omit.

No process summary, no what-I-tried-and-failed, no options you did not take.
