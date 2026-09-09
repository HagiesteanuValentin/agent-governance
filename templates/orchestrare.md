# Orchestration (Fable plans, Opus executes)

Drop this into `~/.claude/orchestrare.md`; `hooks/session-start.sh` injects it into the main
session only.

- Main guards and this block appear only on Fable (hook `main-model.sh`); on Opus you work
  directly, no delegation.
- Main = planner + verifier. Do NOT write code directly except under ~20 lines in one file.
- Deliver what was asked, at that scope. See something better → say it in one sentence; don't
  change scope silently.

## Agents
- explorer(-max), implementer(-complex/-max/-sonnet), scripter(-complex), scribe, auditor,
  design-lead(-expert) only through /polish, refiner(-complex) only through /refine — nothing
  else without my OK.
- Models: explorer* Sonnet 5 medium, read-only (max: report ≤6k, table-shaped answers) ·
  auditor Opus 5 high · implementer Opus 5 low, DEFAULT for any brief, including logic ·
  implementer-complex Opus 5 medium, chosen AT PLAN for multi-file logic, non-trivial verifier
  or declared debugging · implementer-max Opus 5 high · implementer-sonnet Sonnet 5 high ·
  scripter Sonnet 5 high · scripter-complex Opus 5 medium.
- maxTurns: implementer* 100 (max 120), scripter* 80-100, explorer-max 60.
- implementer-sonnet ONLY with a cheap verifier (script, build, test, grep), no debugging, no
  cross-file JS/TS logic: CSS, markup, config, docs, mechanical items. AT PLAN TIME. Logic
  deviations at audit → implementer-max; SendMessage to Sonnet only for mechanical ones.
- Light tasks (docs, HANDOFF, renames, one-line fixes) → scribe, given the target SECTIONS
  (heading, range), not whole files.

## Reading in main
- Main reads only `git diff --stat`, agent reports, and at most one dossier.
- Over ~3k chars of FACTS → explorer. A table/list over 1.5k → explorer-max, or a dossier in
  `docs/dossier/`. Not fitting the report is no reason to read directly.
- Bash: first list what you need, then ALL independent commands in a single call (`;`/`&&`)
  or the same message — never one per turn; the analyzer flags `batchable_bash`, the bash-mare
  hook flags the 3rd.
- Large output (build, tests, diffs) and screenshots stay in the agent's own context: report
  exit code + numbers.
- Plans under `docs/polish/` aren't read in main; summary comes from design-lead's report.

## Flow
- Flow: plan mode, I approve the plan → brief to implementer → audit per `/audit` →
  repairs (below) → final report; you don't summarize the agent's report for me.
- Before ExitPlanMode, paste the plan into chat (context + briefs, short, ≤25 lines): in auto
  mode the approval screen doesn't appear, and exiting plan mode stops auto mode.
- After a NONCOMPLIANT audit, in this order:
  1. Mechanical deviations ≤20 lines/file, ≤3 files, no new logic → the auditor fixes them
  directly, reported as `FIXED` with the hunk.
  2. Everything else → SendMessage to the SAME implementer, all in one message, cap of 3
  messages per agent. You fix it yourself only for one isolated deviation under ~20 lines.
  3. implementer-max ONLY when the deviation is LOGIC and: (a) it already failed once via
  SendMessage, (b) its context is >150k or the agent was closed by the hook, or (c) debugging
  was declared at plan time.
- Before any max you write one line in main: `escalation: <the logic deviation> · <why not
  SendMessage>` — the analyzer flags `max_without_sendmessage`.

## The brief
- One brief = one verifiable delivery. The cap is on FILES and RISK, not on items: CSS or
  text items in the same file, with the same verification, go 8-10 together.
- Split it when it passes ~6 files, mixes JS with CSS, or one item could break another —
  sequential briefs, with the diff audited between them. AT PLAN TIME.
- One extra run costs ~40-50k tokens of bootstrap. One brief ≈ ≤150k context ≈ ≤~60 calls;
  the hook closes it at 150k, blocks at 220k.
- The verifier runs once at the end and once after fixes, not after every edit (the hook
  flags the 3rd run).
- Agent turns are not something to save; a run that leaves verifications unrun is a loss.
- The BRIEF is self-contained (no conversation context, no skills, no delegating). It must
  contain: the goal in one sentence · the steps · the exact files with paths · the definition
  of done · how it's verified · what it's NOT allowed to do (commit/push/seed/real services).
  Rules spelled out, not "load /handoff". No brief, no delegation.
- Give paths and criteria, not pasted code: you don't read files to write the brief; the
  implementer reads its own code from those paths. Copy doc prohibitions verbatim, plus:
  "Do not read DECISIONS or RECIPES in full; only the sections named here".
- With plan mode: the plan (`~/.claude/plans/<slug>.md`) holds the briefs as sections
  `## Brief N — <title>`. Extract the section into its own file (`<scratchpad>/brief-N.md`,
  one `sed -n`); the Agent prompt (≤10 lines) gives THAT path, not the plan, and keeps the
  commit/push prohibition.
- The plan = ≤10 lines of context + briefs + verification; no alternatives, no narration.

## Scripter and dossier
- At plan: scripter-complex (Opus) only ≥4 files AND ≥8 changes confirmed (counted, not
  estimated); measurements over ≥3 states or a check reused ≥2 briefs also qualify →
  scripter writes the script (dry-run → 1 file → all → idempotency), adds a line to
  `scripts/SCRIPTS.md`. Below it, implementer edits; flag `scripter_below_threshold`.
- scripter-complex when the transform needs parsing (AST, multiline regex, frontmatter, JSON),
  per-file conditions, JS/TS logic, or the verifier isn't a plain exit code.
- Before the brief, read `scripts/SCRIPTS.md` (≤40 lines): a script marked "adaptation: easy"
  → you ask for that script adapted, not a new one.
- The scripter brief gives ≥2 before→after examples and the definition of done in numbers.
  The next implementer gets the script's path + only the leftover non-mechanical work. A
  verifier failing after a SendMessage → implementer-max, not a second scripter.
- Several briefs on the same target: the reusable verification script comes from design-lead
  or from brief 1; the following ones ONLY run it, with the "before" numbers from the plan.
- Decision dossier: a brief that needs >300 lines of material before the first Edit → brief 0
  = explorer writes `docs/dossier/<slug>.md`; the implementer gets the path + the ranges.
  `docs/dossier/` is not committed; the analyzer flags `late_first_edit`.

## Parallelism
- Default: one agent at a time. Launch several in one message when it's a time win with no
  risk: (a) explorers on different sources, none depending on another — no need to ask me;
  (b) up to 3 implementer*/scripter* ONLY when, at plan time, each brief has its own file
  list, the lists don't touch (shared config included), at most one runs build/browser (or
  each with its own port and `--out`), and none depends on another;
  (c) auditor on Brief N while the implementer runs Brief N+1, ONLY if N+1 doesn't touch N's
  files and doesn't depend on its verdict — declared at plan time;
  (d) an explorer while an implementer runs, only on areas the brief doesn't touch.
- HARD CAP: ≤6 live agents at once, any type — the analyzer flags `parallel_over_cap`.
- I want to see only the plan and the conclusion, not the execution. Audit after parallel
  runs: brief by brief.
- Worktree (`isolation: worktree`) only declared at plan, when lists can't be disjoint or
  delivery is risky: costs an audited merge, doesn't solve the dependency between briefs.

## Caps
- Agent cache expires at 5 min; SendMessage after audit ≈ rewriting context (80k ≈ $0.50
  Opus), cheaper than a new agent (only past 150k, implementer-max's cap, or unrelated fix).
  Auditor starts right after the report, no main text.
- ≤2 re-sends to implementer per task (3 runs total); one implementer-sonnet,
  implementer-complex or scripter run counts toward them.
- SendMessage to a live agent is not a re-send; it's the first option for small deviations.
- ≤3 explorer runs per task, can run parallel.
- An agent stopped by `maxTurns` = partial output; continue it ONCE via SendMessage (sub-agents
  docs: "message the subagent to continue from where it stopped"), then split the brief,
  don't relaunch it as is.
- Past the cap (4th explorer, 4th run, past 6 live agents): don't decide alone — ask me with
  AskUserQuestion: how many agents, what model, why the cap isn't enough. The approval holds
  only for the current task.

## Audit
- Three fixed commands: `git diff --stat` · diff against PREVIOUS briefs' deliveries on the
  same file · a grep on each "unclear/risky" from the report.
- In main, `git diff` ONLY with `--stat`; no `cat` on whole files.
- Threshold: ≤150 lines changed AND ≤3 files AND no `.js/.ts/.mjs` file with new logic → you
  read `git diff` directly, once; anything else → auditor. It reads the full diff and reports
  deviations in ≤1.5k; you read `git diff --stat` + the report + the flagged files.
- The auditor dies with the delivery; on a re-audit for the same task, continue the same
  agent.
- After launching an agent: zero text until the result notification; then the next-action line
  AND its tool call come in the same message. No "waiting for the report".

## Commit
- At the end of a task, without asking me, ONLY when: the audit is COMPLIANT, the definition
  of done's verifications have run, and the task is delivered in full. Q&A tasks, partial
  delivery, or a "don't commit" from me → no.
- Main commits, not the agent (it keeps the commit/push prohibition).
- `git status --short` first; `git add` ONLY the files from the brief + the ones in
  `git diff --stat`, never `-A`; unknown untracked files stay and you name them.
- Message: one line with what was delivered + the Co-Authored-By trailer.
- `git push -u origin HEAD` on the current branch — on master/main too, and in a worktree.
  Never `--force`, `--amend`, rebase; push rejected → report it, don't insist.
- HANDOFF.md is not part of the task commit (`/handoff` commits it). The final report gives
  the hash and what to check on live.

- `/rate N` and `/handoff` are run by me, not by main.
