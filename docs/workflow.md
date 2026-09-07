# Workflow — how the governance is actually run

This is the operating document: what the architecture is, which hooks enforce what, what
gets measured, and how the measurement is taken. It is not project documentation — a
project has its own HANDOFF / PATTERNS / DECISIONS.

## Architecture

- **The orchestrator** (expensive, high-reasoning model, main session) — plans, writes
  briefs, audits, gives the final report. It does not write more than ~20 lines of code, it
  does not run commands with large output, it reads images only in the downscaled
  `*-small.png` variant, and as late in the session as possible.
- **The agents** (`~/.claude/agents/`):

  | agent | model | effort | maxTurns | role |
  |---|---|---|---|---|
  | `explorer` | cheap | medium | 40 | read-only, brings facts with path:line; on request writes a decision dossier (`docs/dosar/<slug>.md`) with Bash under `permissionMode: plan` (v1.4.1, tested 30.08) |
  | `explorer-max` | cheap | medium | 60 | read-only, same model, report ≤6k, for table-shaped answers (v1.5, A/B 30.08, `docs/experiments.md`) |
  | `implementer` | expensive | low | 100 | default for any brief, including logic |
  | `implementer-complex` | expensive | medium | 100 | plan-time choice for multi-file logic / declared debugging |
  | `implementer-max` | expensive | high | 120 | escalation only: re-send after a failed audit, or debugging declared at plan time |
  | `implementer-sonnet` | cheap (sonnet) | high | 100 | briefs with a cheap checker only, no cross-file JS/TS debugging |
  | `scripter` / `scripter-complex` | cheap / expensive | high / medium | 80 / 100 | write + run a one-off or reusable script under `scripts/` before repetitive edits; log it in `scripts/SCRIPTS.md` |
  | `scribe` | cheap | low | 40 | docs, renames, one-line fixes |
  | `auditor` | expensive | high | 60 | diffs over 150 lines / 3 files / new JS logic; reads, plus mechanical fixes via Edit (v1.4.1: tested against medium, medium misses silent deletions — stays high) |
  | `design-lead` | expensive | high | 60 | read-only + one plan file; gets paths and section headings, does not delegate; only via /polish |
  | `design-lead-expert` | expensive (opus) | xhigh | 50 | read-only + one plan file; two phases: concepts without data, then synthesis with measurements; gets a dossier (paths + line ranges) from an explorer and measurements from an implementer; reads fragments only; chosen by the router in /polish |
  | `refiner` | expensive (fable) | medium | 40 | read-only + one plan file; writes `docs/refine/<slug>.md` from a dossier, measurements and 3 screenshots; only via /refine |
  | `refiner-complex` | expensive (fable) | high | 50 | same as `refiner`, chosen by the router for targets needing more structural judgment; only via /refine |

- The auditor dies with the delivery and is respawned for the next one. The exception: a
  re-audit after repairs on the SAME task continues the same agent, which already has the
  diff in context.

**The commands** (`~/.claude/commands/`, mirrored in `commands/`): `/audit` (audit a commit
range against DECISIONS + definition of done), `/handoff` (rewrite HANDOFF.md as a snapshot),
`/polish` (design-lead writes an exhaustive polish plan to a file, the orchestrator reviews
it adversarially, then the normal implement → audit loop).

**/refine**: narrower than `/polish` — one page or section, not a whole redesign. An explorer
writes a dossier (structure, reusable site inventory, tokens) while a scripter writes/runs a
measurement script and takes ≤3 screenshots (≤1568px long side); `refiner` or `refiner-complex`
(router picks by target) turns those into a plan at `docs/refine/<slug>.md`, reviewed
adversarially in main (one round) before the user picks items. `docs/refine/` is never committed,
same as `docs/dosar/`.

Why it saves money: the orchestrator's context is the expensive resource, because every
token in it is re-paid (as cache reads) on every subsequent message. Agents have their own
throwaway contexts. So the rule is: **big reads happen inside cheap, disposable contexts;
only conclusions cross back into the orchestrator.**

## Active hooks

Registered in `settings.json` (see `hooks/settings.example.json`).

| hook | event | threshold | effect |
|---|---|---|---|
| `session-start.sh` | SessionStart | — | injects `HANDOFF*.md` from the project root |
| `read-mare.sh` | PreToolUse / Read | main only: re-read of a file already read this session, >300 lines without `offset`/`limit`, or an image over 200 KB; sub-agents (v1.7.4): Read on a file the agent itself just wrote, with no Read/Bash-on-basename in between (a ranged Read of ≤60 lines is allowed); **everyone** (v1.4.1): `file_path` under `/tool-results/` | denies (image without `-small`, plans, and short `.md` stay a reminder) |
| `brief-mare.sh` | PreToolUse / Agent | brief >7,000 characters | reminder: "split it into phases" |
| `bash-mare.sh` | PreToolUse / Bash | main only: whole-file reads >300 lines and heredoc writes >20 body lines run through Bash instead of Read/Write/Edit; sub-agents (v1.7.4): the 3rd identical Bash command with no Edit/Write in between; main (v1.8): the 3rd consecutive small Bash call (no heredoc, under 200 chars; calls under 3s apart count as one; reset by a large call or 90s idle) | denies in main, points at the proper tool; the batching case and sub-agents get an `additionalContext` nudge, never a block |
| `write-mare.sh` | PreToolUse / Write\|Edit | main only: >20 written lines | denies, points at scribe/implementer |
| `commit-gate.sh` | PreToolUse / Bash | main only: `git commit` (incl. `git -C <dir> commit`) with staged/unstaged diff touching `.ts/.tsx/.js/.jsx/.mjs/.astro`, no fresh `audit-ok-<session_id>` marker | `ask`: run `/audit` on the commit range first. **Disabled live 2026-09-04** (blocks unattended sessions); script kept, not wired in `settings.example.json` |
| `agenti-vii.sh check` | PreToolUse / Agent | ≥4 agents alive (state file `/tmp/claude-hooks/live-<session_id>`, 5 min grace) | `ask`, lists type/id of the live agents |
| `agenti-vii.sh start`/`stop` | SubagentStart / SubagentStop | — | writes/removes the agent's row in the state file |
| `autonom.sh prompt` | UserPromptSubmit (`prompt`) | prompt matches `\bplec\b`\|`\bnesupravegheat\b` | writes marker `autonom-<session_id>`; cleared by any prompt without the signal |
| `autonom.sh gate` | PreToolUse / `AskUserQuestion`\|`EnterPlanMode` (`gate`) | marker `autonom-<session_id>` exists | `deny`; also silences `agenti-vii.sh`'s `ask` |
| `context-agent.sh --scope main` | PreToolUse / * | main session, own context, same defaults ≥150k / ≥220k (overridable with `--warn`/`--deny`) | same effect as the agent-scope row below, scoped to main |
| `context-agent.sh --praguri-tip` | PreToolUse / * | sub-agent only (`implementer*`/`scripter*`): its own real transcript context (v1.4.1 fix — was reading main's), ≥150k / ≥220k, or ≥100k/≥150k for `implementer-sonnet`/`scripter` with `--praguri-tip`; plus a verification-command counter (3rd `astro check`/`npm test`/`verifica-*.mjs`/etc. on the same agent transcript) | ≥150k (or ≥100k per-type): reminder to wrap up (once); ≥220k (or ≥150k): denies every tool but `Bash`; 3rd verification: one-time `additionalContext` nudge, never blocks |
| `comentarii-cod.sh` | PreToolUse / Edit\|Write\|MultiEdit | main **and** sub-agents: a comment block of ≥2 added lines, an added comment line >160 chars, or >25% comments in the added lines (≥5 added) | sub-agents: **deny** on a block/long line (the ratio criterion stays advisory); main: `additionalContext` with the pointer rule; always one JSONL line in `/tmp/claude-hooks/comentarii-<session>.jsonl` |
| `raport-lung.sh` | SubagentStop | final report >2,000 characters | blocks once, asks for compression (background agents too — verified 2026-08-30 after switching the output to `hookSpecificOutput` + `last_assistant_message`) |
| `session-metrics.sh` | SessionEnd | — | runs the offline analyzer, zero tokens |

Three design notes:

- `read-mare.sh`, `brief-mare.sh`, `bash-mare.sh`, `write-mare.sh`, and `commit-gate.sh` skip
  subagents (`agent_id` present in the hook input). Reading/writing a lot is exactly what a
  subagent is *for*; the rule targets the orchestrator. On the main branch they also ask
  `hooks/main-model.sh` for the session model (plus `agenti-vii.sh check` and the
  `ORCHESTRATION` blocks of `session-start.sh`) and stay silent unless it is Fable/Mythos;
  `unknown` counts as Fable. See PATTERNS «The model inside hooks».
- `comentarii-cod.sh` is the only hook that runs everywhere, main and workers alike. It
  runs before the write: a sub-agent is denied on a comment block or an over-long line and
  rewrites the pointer on the spot, main only gets the warning, and the JSONL log lets
  `/handoff` move the explanations into `PATTERNS`/`DECIZII` later.
- `context-agent.sh` is wired twice: `--scope main` skips any call with `agent_id` set;
  `--praguri-tip` skips main and only watches `implementer*`/`scripter*` — the escalation
  carries the same thresholds, maxTurns is not an exemption.
- `agenti-vii.sh check` runs on main's `PreToolUse/Agent`; `start`/`stop` run on the
  subagent's own `SubagentStart`/`SubagentStop`, so the state file is written by the worker,
  not guessed by main.
- `raport-lung.sh` guards on `stop_hook_active`, so a stubborn agent cannot get stuck in a
  block/retry loop. It blocks at most once per stop.

## What changed when governance went in

1. A ceiling on agent reports: 25 lines AND 1,500 characters, plus the `raport-lung.sh` hook.
2. New comments only for constraints that are invisible in the code; existing ones stay.
3. Briefs give paths, not pasted code; split into phases above ~5 points / ~6 files.
4. Auditing: `git diff --stat` first; over 150 lines, or over 3 files, or new `.js/.ts/.mjs/.astro`
   logic → the auditor agent; otherwise the orchestrator reads the diff itself, once; no `cat` on whole
   files; no Read on `tool-results/`.
5. `implementer` maxTurns lowered 200 → 100.
6. `/polish` post-mortem (Aug 2026): design-lead and scribe get file paths and section
   headings, not whole files; the design-lead does not delegate — the orchestrator pulls
   the paths with `ls`/`grep -rl` and launches an `explorer` for the map only for a whole
   site or when the paths are unclear; design-lead maxTurns 80 → 60; brief ceilings on
   files and risk, not item count; audit = 3 fixed commands, auditor only above threshold.
7. Default flipped to `implementer-max` for any brief with logic; mandatory self-verify
   loop before the report, plus a `NOT RUN` line; audit findings go back to the living
   implementer via SendMessage instead of a new run; a plan file holds the briefs and the
   Agent prompt stays ≤10 lines; `agent_max_turns` now fires only on the harness result in
   main or when calls reach the limit, with a new `calls/limit` column and a `turns_limit`
   field.
8. Automatic `## Postmortem` section with severity and recommendations; a Fable-only cost
   counterfactual (floor/realistic) with context exposure; `TRENDS.md` regenerated by the
   hook for recurring inefficiencies.
9. `/polish` router (opus vs `design-lead-expert`, signals a-d) added for targets needing
   direction/taste; the expert route chains explorer → implementer → design-lead-expert (a
   dossier + measurements file replace live exploration); the aesthetic guard and `Variants`
   line moved into the design-lead's own plan format; the orchestrator adds a one-line
   cut/added note after the operator summary; a "different direction" verdict renames the
   plan to `.v<n>.md` and reuses the dossier/measurements. The long route is chosen by target
   size (site / unclear paths) or by the expert lead.
10. `design-lead-expert` moved to Opus 5 xhigh, in two phases: Phase A writes 3 concepts
   without data (concepts run alongside the measurements, in parallel with implementer 2b);
   Phase B, triggered by a `SendMessage` (no new agent launch), reads the measurements and
   synthesizes one backbone concept plus borrowed parts into the plan. Motivated by a
   post-mortem: anti-safe requests still produced 5-9 item, delta-only plans on the previous
   single-phase flow.
11. v1.8: phase-based effort is back under `~/.claude/v17-effort-auto` (changelog 2.1.260 —
   `/effort` no longer rewrites the cache; the hook only warns, the user runs `/effort`); the
   advisor is mandatory on triggers a-f, not just on 2+ JS/TS briefs; `bash-mare.sh` nudges
   main on the 3rd consecutive small Bash call; `subagentPromptCacheTtl` is deliberately not
   set (agents already write 100% at 5m); Fable 5.1 pricing corrected (cache read $1 at
   0.1x for calc, $0.25 is only the informative API price — blueprint 2026-09-03 goes
   $65.87 to $57.72, main stays $19.34, floor $89.44 vs realistic $556.44 on
   `claude-fable-5-1`), so orchestration savings are read on `realistic`, not floor.
   Narration got no hook: 27 of 88 main calls, about $0.73, roughly 1.5% of the session.

## What gets measured

v1.4.1 fixed the agent-context hook (it was reading main's transcript, not the sub-agent's —
see DECIZII «v1.4.1») and added `tool_results_read`, `late_first_edit`, an interval-aware
`reread`, and a per-brief `too_many_runs`.

- Do agent reports hold the ceiling? (final-report lengths, per agent, per session)
- `raport-lung.sh`: false triggers or loops? `brief-mare.sh`: did it fire when it should?
- Consumption per session against the baseline (target: −15–25% on how fast the
  orchestrator's context fills).
- Does the auditor catch real deviations? (spot check: 1–2 audits also done directly by the
  orchestrator.)
- `main_read_files`: Bash calls in main that read files (`cat`, `sed -n`, `head`, `tail`,
  `less`, long heredocs, `grep`/`wc`) instead of delegating the read — counted only when the
  result comes back over 2,000 characters, so a targeted lookup is not a flag.
- `main_read_report`: Bash calls in main that read a report under `docs/refine/` or
  `docs/polish/` — informative only, 0 tokens taxed, since reading a subagent's own report
  back is the feedback loop, not a delegation miss.
- `narration_turns`: API calls in main with no tool use and short text. A short answer to
  the user is not counted at all. The rest are split by what the turn could have done
  instead: `structural` (an async agent was still live, the note came right after a launch,
  the text ends in a question, or it is the session's last turn — the turn had to end
  anyway) is counted but not taxed; `avoidable` (nothing running, nothing asked — main wrote
  a line and stopped instead of continuing) is taxed at `cache_read / 10`. The flag fires
  above 2 avoidable calls. Sub-type `residual_poll`: a note after the harness re-notified an
  already-notified agent — always avoidable, reported separately since the cause is the
  harness, not the model.
- `batchable_bash`: runs of ≥3 consecutive small Bash calls in main that could have been one
  call.
- `plan_echo`: an `ExitPlanMode` result in main large enough that the plan is being paid for
  twice (write and echo).
- Every flag now carries a `severity` (high/medium/low), escalated when its estimated wasted
  tokens cross a threshold.
- A `postmortem` object per session: hands-on ratio (direct tool use vs. delegation),
  narration call count (split into avoidable and structural), and wasted tokens as a
  percentage of main's input volume.
- A `counterfactual` object per session: what the same work would have cost in a single
  Fable-only context, versus what actually happened.
- `reread`: keyed on `(file, offset, limit)` — distinct slices of one file are not a reread;
  a whole-file read after slices, or the same slice twice, is.
- `too_many_runs`: implementer/scripter runs grouped per brief (the launch description, minus
  `-fix` / `fix` / `reparații` / `re-`), flagged above 3 runs on the same brief.
- `tool_results_read`: a worker read a `tool-results/` file instead of re-running the command
  on a narrower range.
- `late_first_edit`: an implementer/scripter whose first write comes at ≥100k context or after
  ≥15 reading calls — decision reading belongs in an explorer's dossier.

## The measurement recipe

Transcripts live at `~/.claude/projects/<project-dir>/<session-id>.jsonl`, one JSON object
per line. Useful fields: `.type` (user/assistant), `.isSidechain` (true for subagent
turns), `.message.id` (dedup key — the same message id appears on several lines),
`.message.usage.output_tokens`, `.message.content` (text / tool_use / tool_result blocks).

The analyzer in this repo does the aggregation offline:

```sh
python3 tools/session_metrics.py ~/.claude/projects/<project-dir>/          # all sessions
python3 tools/session_metrics.py <session>.jsonl --md --out report.md       # one session
python3 tools/session_metrics.py <session>.jsonl --json --out report.json   # machine-readable
python3 tools/session_metrics.py ~/.claude/projects/<project-dir>/ --json --md --out-dir metrics-local/  # per-session files
python3 tools/session_metrics.py --rename metrics-local/          # rename old <uuid>.json/.md files
```

`--out-dir DIR` writes one `<name>.json` (with `--json`) and one `<name>.md` (with `--md`)
per session into `DIR`. `--rename DIR` renames old `<uuid>.json`/`.md` files in `DIR` to the
new naming scheme, skipping collisions unless `--force` is given. `--ctx-warn N` sets the
threshold for the `high_context_end` flag (default 150000). Files are named
`YYYY-MM-DD-sN-<project>.json`/`.md` (local start date, Nth session of that project that day
by start time, `<project>` = basename of the working directory).

It reports, per session: input/output/cache tokens per model, estimated cost from
`tools/pricing.json`, the share of output produced in sidechains (subagents), a per-agent
table with the final-report length in characters, the largest `tool_result` payloads, files
read more than once, and images read. `tools/versions.json` holds workflow versions (name +
start day, or a local minute `YYYY-MM-DDTHH:MM`); `TRENDS.md` groups sessions by version so you can compare before/after a
workflow change, and sessions before the first version are `older`. Moving a boundary in
`versions.json` and re-running `--trends` also rewrites the `version` field in every session's
`.json`/`.md`, so the files stay consistent with `TRENDS.md`.

Zero tokens: it is plain Python over local files. The `SessionEnd` hook runs it
automatically and drops the JSON and the Markdown report into `metrics-local/` (gitignored).

`--as-model` (default `claude-fable-5`) picks the rate card for the Fable-only estimate.
`--rot-at` (default 0.35) sets the context-exposure threshold as a fraction of the window.
`--window` (default 1,000,000) sets the context window size used for that threshold.
`--trends DIR` reads every session JSON in `DIR` and writes `DIR/TRENDS.md`; the
`SessionEnd` hook runs it after every session. TRENDS opens with an executive summary per
corpus and per version: spend, savings against the Fable-only realistic estimate ($ and %,
cumulative across versions), estimated waste in tokens and as % of main input volume, waste
grouped into families (reads, agent overhead, orchestration turns, discipline), and deltas
against the previous version and against `older`. Sessions where at least 50% of the main
session's tool calls are `mcp__claude-in-chrome__*` are listed separately under "Excluded"
and do not count toward the numbers (threshold: `--browser-threshold`, default 0.5;
version list: `--versions PATH`). `/rate N [note]` before closing a session attaches a 1-5
quality rating to it (via the SessionEnd hook); `--rate NAME N` rates a session after the
fact; TRENDS shows the mean quality per version.

Fable-only estimate: it re-plays the session's actual API calls as if they had all run in a
single Fable-5 context instead of across main + subagents, to see what the same work would
have cost without delegation overhead. Assumptions: same calls and outputs; worker bootstrap
removed; worker content persists in the single context; all context cached (1h TTL). It is a
cost counterfactual, not a quality claim: usage data carries no quality signal; the context
threshold is the operator's, not Anthropic's.

## Why orchestration lives in a hook, not in CLAUDE.md

Subagents receive the whole CLAUDE.md — the docs: "every level of the CLAUDE.md hierarchy
the main conversation loads, including ~/.claude/CLAUDE.md". A SessionStart hook reaches
only main (measured 2026-08-30: 110/267 main transcripts vs. 0/492 subagent ones), so
orchestration moved into `~/.claude/orchestrare.md` plus the hook is no longer paid on every
agent run — a saving of ≈3.5k tokens per agent run. Auto-compact is disabled in the config
(context is kept under 250k); if it is re-enabled, check that the hook re-injects after
`/compact`. The hook is context, not enforcement — rules bind only through blocking hooks.

## Open ideas

- Tighten `raport-lung.sh` to ~1,800 characters if the ceiling is held anyway.
- Session-length discipline: a handoff at every closed milestone. The biggest remaining
  lever, and the one hooks cannot fix — it is a habit.
