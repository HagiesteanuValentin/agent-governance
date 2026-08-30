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
  | `explorer` | cheap | medium | 40 | read-only, brings facts with path:line |
  | `implementer` | expensive | medium | 100 | default for any brief, logic included |
  | `implementer-max` | expensive | high | 120 | escalation only: re-send after a failed audit, or debugging declared at plan time |
  | `implementer-sonnet` | cheap (sonnet) | high | 100 | briefs with a cheap checker only, no cross-file JS/TS debugging |
  | `scribe` | cheap | low | 40 | docs, renames, one-line fixes |
  | `auditor` | expensive | high | 60 | diffs over 150 lines / 3 files / new JS logic; reads, plus mechanical fixes via Edit |
  | `design-lead` | expensive | high | 60 | read-only + one plan file; gets paths and section headings, does not delegate; only via /polish |
  | `design-lead-expert` | expensive (opus) | xhigh | 50 | read-only + one plan file; two phases: concepts without data, then synthesis with measurements; gets a dossier (paths + line ranges) from an explorer and measurements from an implementer; reads fragments only; chosen by the router in /polish |

- The auditor dies with the delivery and is respawned for the next one. The exception: a
  re-audit after repairs on the SAME task continues the same agent, which already has the
  diff in context.

**The commands** (`~/.claude/commands/`, mirrored in `commands/`): `/audit` (audit a commit
range against DECISIONS + definition of done), `/handoff` (rewrite HANDOFF.md as a snapshot),
`/polish` (design-lead writes an exhaustive polish plan to a file, the orchestrator reviews
it adversarially, then the normal implement → audit loop).

Why it saves money: the orchestrator's context is the expensive resource, because every
token in it is re-paid (as cache reads) on every subsequent message. Agents have their own
throwaway contexts. So the rule is: **big reads happen inside cheap, disposable contexts;
only conclusions cross back into the orchestrator.**

## Active hooks

Registered in `settings.json` (see `hooks/settings.example.json`).

| hook | event | threshold | effect |
|---|---|---|---|
| `session-start.sh` | SessionStart | — | injects `HANDOFF*.md` from the project root |
| `read-mare.sh` | PreToolUse / Read | main only: re-read of a file already read this session, or >300 lines without `offset`/`limit` | denies (image without `-small`, plans, and short `.md` stay a reminder) |
| `brief-mare.sh` | PreToolUse / Agent | brief >7,000 characters | reminder: "split it into phases" |
| `context-agent.sh` | PreToolUse / * | sub-agent only (`implementer*`): its own context ≥150k / ≥220k | ≥150k: reminder to wrap up (once); ≥220k: denies every tool but `Bash` |
| `raport-lung.sh` | SubagentStop | final report >2,000 characters | blocks once, asks for compression (background agents too — verified 2026-08-30 after switching the output to `hookSpecificOutput` + `last_assistant_message`) |
| `session-metrics.sh` | SessionEnd | — | runs the offline analyzer, zero tokens |

Three design notes:

- `read-mare.sh` and `brief-mare.sh` skip subagents (`agent_id` present in the hook input).
  Reading a lot is exactly what a subagent is *for*; the rule targets the orchestrator.
- `context-agent.sh` is the mirror: it skips main (no `agent_id`) and only watches
  `implementer`/`implementer-sonnet`/`implementer-max` — the escalation carries the same
  thresholds, maxTurns is not an exemption.
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

## What gets measured

- Do agent reports hold the ceiling? (final-report lengths, per agent, per session)
- `raport-lung.sh`: false triggers or loops? `brief-mare.sh`: did it fire when it should?
- Consumption per session against the baseline (target: −15–25% on how fast the
  orchestrator's context fills).
- Does the auditor catch real deviations? (spot check: 1–2 audits also done directly by the
  orchestrator.)
- `main_read_files`: Bash calls in main that read files (`cat`, `sed -n`, `head`, `tail`,
  `less`, long heredocs, `grep`/`wc`) instead of delegating the read — counted only when the
  result comes back over 2,000 characters, so a targeted lookup is not a flag.
- `narration_turns`: API calls in main with no tool use and short text. A short answer to
  the user is not counted at all. The rest are split by what came before them: `structural`
  (right after an agent launch or a `SendMessage` — the launch returns at once, so the turn
  has to end) is counted but not taxed; `avoidable` (after a task notification or any other
  tool result — main wrote a line and stopped instead of continuing) is taxed at
  `cache_read / 10`. The flag fires above 2 avoidable calls.
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
`SessionEnd` hook runs it after every session. Sessions where at least 50% of the main
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

## Open ideas

- Tighten `raport-lung.sh` to ~1,800 characters if the ceiling is held anyway.
- Session-length discipline: a handoff at every closed milestone. The biggest remaining
  lever, and the one hooks cannot fix — it is a habit.
