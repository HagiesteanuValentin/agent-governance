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
  `implementer`, `implementer-max`, `implementer-sonnet`, `scripter`, `scripter-complex`,
  `scribe`, `auditor`, `design-lead`, `design-lead-expert` (only via `/polish`) — nothing
  else without the operator's approval.
- Do not re-read files you have just written.
- A new code comment = a single one-line pointer: `🔴 <constraint> — <DOC> «<section>»`
  (PATTERNS for technical traps, DECISIONS for reasons). The explanation does NOT live in the
  code, it lives in the named section; if the section does not exist, add it there (2-5
  lines) and put the pointer. No comment blocks, no "what the code does", no history ("it
  used to be..."). Test: does changing the comment change what an agent does when it edits
  THIS line? If not, don't write it. Existing comments are never deleted. A hook flags blocks
  of >=2 lines — on a flag, shorten it before the report. Applies to the orchestrator's own
  sub-20-line edits too.

## Orchestration (the orchestrator plans, the worker model executes)

- Applies only when the main session runs the orchestrator model. If the session already
  runs the worker model (a trivial task, chosen deliberately), work directly, without
  delegation — a model delegating to an equally expensive model is waste.
- The main session = planner + verifier. It does NOT write code directly except for tasks
  under ~20 lines in a single file.
- After launching an agent: no text at all until its result notification. At the
  notification, the line stating the next action AND its tool call go in the same message;
  a text-only message after a notification ends the turn and re-sends the whole context
  (~100k cache) for nothing. No "waiting for the report".
- Agent report: 1,500 soft cap / 2,000 hard cap — over 2,000 the hook rejects the report.
- Quality rating: before closing a session that delivered a task, the operator runs
  `/rate N [note]` (N = 1-5: 5 complete and correct on the first pass, zero fixes after
  audit · 4 complete, one round of small fixes · 3 complete, 2+ rounds or a deviation the
  operator caught · 2 partial, the operator fixed/relaunched it · 1 unusable — rate the
  result, not the cost). If forgotten, rate it later with
  `python3 tools/session_metrics.py --rate <session-name> N`.
- The flow: (1) plan mode → the operator approves the plan; (2) send the plan to
  `implementer` as a BRIEF; (3) receive the report, audit the diff (on large diffs, through
  `auditor`) against the audit criteria (DECISIONS, definition of done, verifications);
  (4) the auditor fixes mechanical deviations directly (≤20 lines/file, ≤3 files, no new
  logic) and reports them as `FIXED` with the hunk; the rest all go, in a single message, to
  the same implementer via SendMessage (its context is alive; ~0 bootstrap versus ~40-50k
  for a new run) — the first re-send after a failed audit goes to `implementer-max`; you fix
  directly only an isolated deviation, under ~20 lines in one file, when that is faster than
  the message; (5) only then the final report.
- Light tasks (docs, HANDOFF, renames, one-line fixes, typos) → `scribe`. The scribe gets
  the target SECTIONS (heading name, maybe a line range), not whole files; it does not read
  docs end to end.
- `implementer` (Opus, medium effort, maxTurns 100) is the DEFAULT for any brief, logic
  included. A brief ≈ ≤150k of the agent's context ≈ ≤~60 calls; the hook wraps it up at
  150k and blocks at 220k — split oversized briefs AT PLAN TIME; run the verifier once at
  the end of the brief and once after a round of fixes, not after every edit — the hook
  flags (does not block) a 3rd verification run on the same brief, screenshots
  only if the brief asks for them (12% of verifications led to a fix; 41% of the agent's
  output is verification); up to 3 in parallel with
  disjoint file lists. The agent's turns and tokens are NOT a cost to save: its context dies
  at the end, only 1,500 characters reach main. A run that delivers complete under 150k is a
  win; a short one that leaves checks unrun is a loss (the operator has to step in) — but past
  150k the hook closes out the brief, so length is decided at plan time, not mid-run.
  Reason (numbers from 30.08): tool_result errors 0.9%→5.1% and $/call doubling between Q1
  and Q4 on large runs; Anthropic: medium is −2 points at half the cost of high, and
  "low/medium + re-run on failure" matches high's success rate.
- `implementer-sonnet` (Sonnet 5, high effort, maxTurns 100) ONLY for briefs with a cheap
  verifier (a `verifica-*.mjs` script, build, test, a grep that catches failure), no
  debugging and no multi-file JS/TS logic: CSS, markup, config, docs, mechanical items,
  verification scripts. Chosen AT PLAN TIME and written into the brief. Logic deviations at
  audit → re-send to `implementer-max` (not a second Sonnet run); SendMessage to Sonnet only
  for mechanical deviations (text/CSS/config).
- `implementer-max` (Opus, high effort, maxTurns 120) is an ESCALATION, not a default: ONLY
  (a) a re-send after a failed audit on the same brief, or (b) debugging declared at plan
  time with a written reason. It carries the same context thresholds as any brief —
  maxTurns 120 is not an exemption from the 150k/220k hook.
- Scripter before repetitive work: at plan time, if a brief has ≥8 changes with the same
  pattern across ≥4 files, screenshots/measurements across ≥3 states or widths, or a check
  that will run in ≥2 briefs → the first brief goes to `scripter` (cheap model, high
  effort, maxTurns 80): it writes the script under `scripts/`, runs it (dry-run → one-file
  proof → full run → idempotency check), and adds a row to `scripts/SCRIPTS.md`.
  `scripter-complex` (worker model, medium effort, maxTurns 100) when the transform needs
  parsing (AST, multiline regex, frontmatter/JSON), per-file conditions, multi-file JS/TS
  logic, or a verifier that is not a simple exit code. Before writing the brief, read
  `scripts/SCRIPTS.md` (≤40 lines): a script marked "adaptability: easy" means the brief
  asks for adapting it, not writing a new one. The scripter brief gives ≥2 before/after
  examples and the definition of done in numbers (n files, m matches). The implementer that
  follows gets the script's path plus only the non-mechanical leftovers. A failed verifier
  after a SendMessage goes to `implementer-max`, not a second scripter run. A scripter run
  counts toward the 3-run cap per task. Reason (one day's transcripts): 6 repetitive runs
  cost $79 — manual find/replace ×38 on one CSS file by hand, a verifier run by hand ×21
  times, a script rebuilt from 24 incremental edits.
- Decision dossier (v1.4.1): a brief that needs >300 lines of decision material read (docs
  excerpts, config, comments, transcripts) before the first Edit → brief 0 = `explorer`
  writes `docs/dosar/<slug>.md`; the implementer gets the dossier's path plus the ranges,
  not whole files; `docs/dosar/` never enters a commit; the analyzer flags `late_first_edit`
  when the first Edit comes too late.
- `explorer` = the cheap read-only model, medium effort (tested against a pricier low-effort
  model: double the cost, no correctness gain — unchanged). `auditor` = the worker model,
  high effort (tested against medium: −3-6% cost, but medium misses silent deletions — do
  not downgrade it).
- Screenshots are compared by the agent, in its own context; it reports numbers and a
  conclusion. The orchestrator reads at most 1–2 final screenshots for the verdict, in the
  downscaled `*-small.png` variant, as late in the session as possible — every image read is
  re-paid on every following message.
- Parallelism: one agent at a time by default, but launch several in a single message when
  it saves wall-clock time without risk: (a) `explorer` runs with questions on different
  sources/topics, none depending on another's answer — no need to ask first; (b) up to 3
  `implementer*`/`scripter*` ONLY when, at plan time, each brief has its own file list and
  the lists do not overlap (shared tokens/config included), at most one runs a
  build/browser (or each has its own port and `--out`), and none depends on another's
  result; (c) `auditor` on Brief N while the implementer runs Brief N+1, ONLY if N+1 does
  not touch N's files and does not depend on its verdict — declared in the plan; (d) an
  `explorer` while an implementer runs, only on areas the brief does not touch (otherwise
  it reads files being modified). HARD CAP: at most 4 live agents at once, any type — the
  analyzer flags `parallel_over_cap` above 4. The operator wants to see the plan and the
  conclusion, not the execution. Audit after parallel runs: brief by brief. A
  worktree (`isolation: worktree`) only when declared in the plan, for lists that cannot be
  guaranteed disjoint or a risky delivery you want to be able to throw away: it costs the
  dependencies installed on the copy + a merge you audit yourself; it does not solve
  dependencies between briefs.
- Default ceilings: at most 2 re-sends to `implementer` on the same task (3 runs total; the
  first re-send after a failed audit goes to `implementer-max`) and
  at most 3 `explorer` runs per task (can run in parallel); SendMessage messages to a live agent
  are not re-sends — ceiling of 3 messages per agent. An agent stopped by `maxTurns` is a
  signal that the brief is too big; split it, do not relaunch it unchanged. One
  `implementer-sonnet` run per brief, counted in the 3 runs.
- One brief = ONE verifiable delivery. The ceiling is on FILES and RISK, not on the item
  count: CSS/text items in the same file, with the same verification, go 8–10 together.
  Split when the brief touches more than ~6 files, mixes JS with CSS, or one item can break
  another — sequential briefs, with the diff read and audited between them. Every agent
  run costs ~40–50k tokens of bootstrap (docs + Playwright), so one extra run is more
  expensive than a longer brief. The split is decided AT PLAN TIME: the approved plan
  already lists the briefs, one verifiable delivery each.
- Auditing: `git diff --stat` first, then the diff only on the relevant files. Never run
  `cat` on whole files next to a diff.
- Never read files from `tool-results/` (you re-pay for a result you already saw); if a fact
  is missing, ask the explorer for it. The ban applies to every agent (explorer,
  implementer*, scripter*, auditor) — written into each one's own prompt.
- Audit, directly, 3 fixed commands: `git diff --stat` · diff against the deliveries of
  EARLIER briefs on the same file (a brief that revisits an item can delete lines delivered
  before) · one grep/screenshot per "unclear/risky" line in the agent's report. In main,
  `git diff` ONLY with `--stat`; Threshold: `git diff --stat` with ≤150 changed lines
  (added+removed) AND ≤3 files AND no `.js/.ts/.mjs/.astro` file with new logic → the
  orchestrator reads the diff itself, ONCE, no re-reading; anything else → `auditor`. It
  reads the whole diff in its own context and reports deviations in at most 1.5k characters;
  you read `git diff --stat` + the report + only the files it flags.
  Plans under `docs/polish/*.md` are not read in main; the human-facing summary comes from
  the design-lead's report. The auditor dies with the delivery; only a re-audit after
  repairs on the same task continues the same agent.
- Never run commands with large output (build, full test scripts, whole diffs): the agent
  runs them in its own context and reports exit code and numbers.
- The BRIEF gives paths and criteria, not pasted code: do not read files in order to write
  the brief; the implementer reads its own code from the paths you give.
- Copy the relevant prohibitions (from DECISIONS/PATTERNS/phase docs) into the brief, in
  full, and write explicitly: "Do NOT read DECISIONS/PATTERNS/RECIPES in full; from the
  docs read only the sections named here" (heading names). Every agent that re-reads
  whole docs burns ~10–20k tokens on the same facts.
- A task with several briefs on the same target: the reusable verification script is
  delivered by the design-lead (in /polish) or by brief 1 (otherwise):
  `scripts/verify-<target>.mjs` — one browser, downscaled screenshots at the widths from
  CLAUDE.md, batch measurements, `browser.close()` in `finally`. Later briefs get its path
  and ONLY run it — no ad-hoc screenshots. Fixes after the verdict run the same script;
  the "before" numbers come from the design-lead's plan, not from a worktree.
- Above a ceiling (a wide audit, a 4th explorer, a 4th implementer run, more than 4 live agents):
  do NOT break the task and do NOT decide alone — ask the operator: how many agents, which
  model, what each one looks for, why the ceiling is not enough. The approval applies to
  the current task only.
- The BRIEF is self-contained (the agent does not see the conversation, has no skills, does
  not delegate). It must contain: the goal in one sentence · the steps · the exact files
  with paths · the definition of done (states, breakpoints, what DECISIONS forbids) · how it
  is verified (commands, measurements, screenshots) · what it must NOT do
  (commit/push/deploy/seed/real services). Write the rules out in full; do not reference a
  skill. Without a complete brief, nothing gets delegated.
- Task with plan mode: the plan (`~/.claude/plans/<slug>.md`) contains the complete briefs
  as `## Brief N — <title>` sections, each with every required element above. When
  delegating, the Agent prompt is ≤10 lines: the plan's path + "execute ONLY section
  «Brief N»" + the commit/push ban; do not rewrite the brief in the prompt. Plan = ≤10
  lines of context + briefs + verification; no alternatives, no narrative (every character
  is paid twice: once to write, once as ExitPlanMode's echo).

## Final report (after any task)

Exactly this structure, max 8 lines, no section headings:
1. One sentence: what was done and whether it works (verified how).
2. The files touched, one line each, only what matters.
3. "You have to:" — only if the operator has something to do. Otherwise omit.
4. "Unclear / risky:" — only if it exists. Otherwise omit.

No process summary, no what-I-tried-and-failed, no options you did not take.
