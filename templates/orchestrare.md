# Orchestration (Fable plans, Opus executes)

Drop this into `~/.claude/orchestrare.md`; `hooks/session-start.sh` injects it into the main
session only.

- Main guards and this block appear only on Fable (hook `main-model.sh`); on Opus you work
  directly, no delegation.
- Main = planner + verdict + commit. After ExitPlanMode the `orchestrator` agent executes;
  main writes NO code and launches no implementer*/scripter*/auditor* directly.
- Deliver what was asked, at that scope. See something better → say it in one sentence; don't
  change scope silently.

## Agents
- orchestrator (Opus 5.5 medium): executes the approved plan, launches the workers, writes the
  run-log. Its execution rules live in `agents/orchestrator.md`, not here.
- Workers it launches: implementer (Opus 5.5 low, DEFAULT) · implementer-complex (medium,
  cross-file logic) · implementer-max (high, declared debugging only) · scripter (low) ·
  scripter-complex (Opus 5 medium) · auditor (medium; -complex high) · scribe.
  implementer-sonnet only when I name it.
- Main launches directly: explorer(-max) (Sonnet 5 medium, read-only; max: report ≤6k,
  tables), advisor, the final auditor-complex; design-lead and design-lead-expert only through /polish,
  refiner(-complex) only through /refine — nothing else without my OK.
- At plan, name the worker per brief; escalation (-complex/-max) needs one line in the plan
  or the run-log: `escalation: <logic deviation> · <why not SendMessage>`.

## Reading in main
- Main reads only `git diff --stat`, agent reports, the run-log SUMMARY and at most one dossier.
- Read, Bash, WebFetch, WebSearch: >3k chars FACTS → explorer; table/list >1.5k →
  explorer-max or a dossier in `docs/dossier/`. Not fitting the report is no reason.
- Bash: first list what you need, then ALL independent commands in a single call (`;`/`&&`)
  or the same message — never one per turn; the analyzer flags `batchable_bash`, the bash-mare
  hook flags the 3rd.
- Plans under `docs/polish/` aren't read in main; summary comes from design-lead's report.

## Flow
1. Plan mode as today: explorers, advisor, briefs as `## Brief N — <title>` in the plan.
   Before ExitPlanMode, paste the plan into chat (context + briefs, ≤25 lines): in auto mode
   the approval screen doesn't appear, and exiting plan mode stops auto mode.
2. After ExitPlanMode: extract each brief into `<scratchpad>/brief-N.md` (one `sed -n`), then
   launch ONE `orchestrator` Agent in background. Prompt ≤10 lines: plan path, brief paths,
   run-log path (`docs/dossier/run-<slug>.md`), order/parallelism declared at plan,
   prohibitions (commit/push/seed/real services).
3. After launching: zero text until the notification. A `PING brief N: …` message → answer
   with at most one line, zero tool calls, zero decisions. Something looks wrong → note it
   and wait for the hand-back or the end; TaskStop only if the orchestrator visibly breaks
   the delivery (wrong file, out of scope).
4. At the notification: read the run-log SUMMARY once (Read, limit 150; the ANNEX only for
   flagged reports, with offset) + `git diff --stat` → verdict (see Audit).
5. HAND-BACK → answer by SendMessage to the SAME orchestrator, ≤3 per task; past that →
   AskUserQuestion. You see a deviation → SendMessage the orchestrator, never a worker.
   Its children are dead after a hand-back: a re-send there means a new agent (~40-50k).
6. OK → commit (below). You don't summarize the reports for me.

## The brief
- One brief = one verifiable delivery. The cap is on FILES and RISK, not on items: CSS or
  text items in the same file, with the same verification, go 8-10 together.
- Split it when it passes ~6 files, mixes JS with CSS, or one item could break another —
  sequential briefs, audited between them. AT PLAN TIME.
- One extra run costs ~40-50k tokens of bootstrap. One brief ≈ ≤150k context; the hook
  closes it at 150k, blocks at 220k. Worker turns are not something to save.
- The BRIEF is self-contained (no conversation context, no skills, no delegating). It must
  contain: the goal in one sentence · the steps · the exact files with paths · the definition
  of done · how it's verified · what it's NOT allowed to do (commit/push/seed/real services).
  Rules spelled out, not "load /handoff". No brief, no delegation.
- Give paths and criteria, not pasted code: you don't read files to write the brief. Copy doc
  prohibitions verbatim, plus: "Do not read DECISIONS or RECIPES in full; only the sections
  named here".
- The plan (`~/.claude/plans/<slug>.md`) = ≤10 lines of context + briefs + verification; no
  alternatives, no narration. Each brief names its worker and effort.

## Scripter and dossier (at plan)
- scripter-complex (Opus) only ≥4 files AND ≥8 changes confirmed (counted, not estimated);
  measurements over ≥3 states or a check reused ≥2 briefs also qualify. Below it, implementer
  edits; flag `scripter_below_threshold`.
- scripter-complex when the transform needs parsing (AST, multiline regex, frontmatter, JSON),
  per-file conditions, JS/TS logic, or the verifier isn't a plain exit code.
- Before the brief, read `scripts/SCRIPTS.md` (≤40 lines): a script marked "adaptation: easy"
  → the brief asks for that script adapted, not a new one.
- The scripter brief gives ≥2 before→after examples and the definition of done in numbers.
- Several briefs on the same target: the reusable verification script comes from design-lead
  or from brief 1; the following ones ONLY run it, with the "before" numbers from the plan.
- Decision dossier: a brief that needs >300 lines of material before the first Edit → brief 0
  = explorer writes `docs/dossier/<slug>.md`; the implementer gets the path + the ranges.
  `docs/dossier/` is not committed; the analyzer flags `late_first_edit`.

## Parallelism (declared at plan, executed by the orchestrator)
- Default: one brief at a time. Declare in the plan which briefs run together: disjoint file
  lists (shared config included), at most one build/browser, no dependency between them.
- HARD CAP: ≤6 live agents at once, any type — the analyzer flags `parallel_over_cap`.
- In plan mode, explorers on different sources can run in one message — no need to ask me.
- Worktree (`isolation: worktree`) only declared at plan, when lists can't be disjoint or
  delivery is risky: costs an audited merge, doesn't solve the dependency between briefs.
- I want to see only the plan and the conclusion, not the execution.

## Caps
- Hand-backs: ≤3 SendMessage answers to the orchestrator per task; past that → AskUserQuestion.
- The orchestrator keeps ≤2 re-sends per brief (3 runs total) and ≤6 live agents; it hands
  back instead of deciding past them.
- Explorers: no numeric cap — main launches as many as it needs, never reads solo; but
  surgically: each with one precise question and its own area, never two on the same source.
- Past a cap (4th run, past 6 live agents): ask me with AskUserQuestion: how many agents, what
  model, why the cap isn't enough. The approval holds only for the current task.

## Audit = verdict on the run-log
- The orchestrator's auditors read every diff; main reads the run-log SUMMARY + `git diff
  --stat`, never `git diff` in full, no `cat` on whole files.
- Verdict: OK only when every brief is `OK` or `DEVIATIONS (n), n fixed`, the definition of
  done's verifications ran, and no item is left unverified.
- When JS/TS/astro logic changed, main launches one final `auditor-complex` on the whole diff
  (independent of the orchestrator), then gives the verdict. It reports in ≤1.5k.

## Commit
- At the end of a task, without asking me, ONLY when: the verdict is OK, the definition of
  done's verifications have run, and the task is delivered in full. Q&A tasks, partial
  delivery, or a "don't commit" from me → no.
- Main commits, not the agents (they keep the commit/push prohibition).
- `git status --short` first; `git add` ONLY the files from the briefs + the ones in
  `git diff --stat`, never `-A`; the run-log and unknown untracked files stay; name them.
- Message: one line with what was delivered + the Co-Authored-By trailer.
- `git push -u origin HEAD` on the current branch — on master/main too, and in a worktree.
  Never `--force`, `--amend`, rebase; push rejected → report it, don't insist.
- HANDOFF.md is not part of the task commit (`/handoff` commits it). The final report gives
  the hash and what to check on live.

- `/rate N` and `/handoff` are run by me, not by main.
