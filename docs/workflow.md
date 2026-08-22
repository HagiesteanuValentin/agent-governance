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
  | `implementer` | expensive | medium | 100 | the default executor |
  | `implementer-max` | expensive | high | 200 | hard tasks only, reason named in the brief |
  | `scribe` | cheap | low | 40 | docs, renames, one-line fixes |
  | `auditor` | expensive | high | 60 | read-only, diffs over ~200 lines |

- The auditor dies with the delivery and is respawned for the next one. The exception: a
  re-audit after repairs on the SAME task continues the same agent, which already has the
  diff in context.

Why it saves money: the orchestrator's context is the expensive resource, because every
token in it is re-paid (as cache reads) on every subsequent message. Agents have their own
throwaway contexts. So the rule is: **big reads happen inside cheap, disposable contexts;
only conclusions cross back into the orchestrator.**

## Active hooks

Registered in `settings.json` (see `hooks/settings.example.json`).

| hook | event | threshold | effect |
|---|---|---|---|
| `session-start.sh` | SessionStart | — | injects `HANDOFF*.md` from the project root |
| `read-mare.sh` | PreToolUse / Read | >300 lines, or an image without `-small` | reminder, does not block |
| `brief-mare.sh` | PreToolUse / Agent | brief >7,000 characters | reminder: "split it into phases" |
| `raport-lung.sh` | SubagentStop | final report >2,500 characters | blocks once, asks for compression |
| `session-metrics.sh` | SessionEnd | — | runs the offline analyzer, zero tokens |

Two design notes:

- `read-mare.sh` and `brief-mare.sh` skip subagents (their transcript path contains
  `subagent`). Reading a lot is exactly what a subagent is *for*; the rule targets the
  orchestrator.
- `raport-lung.sh` guards on `stop_hook_active`, so a stubborn agent cannot get stuck in a
  block/retry loop. It blocks at most once per stop.

## What changed when governance went in

1. A ceiling on agent reports: 25 lines AND 1,500 characters, plus the `raport-lung.sh` hook.
2. New comments only for constraints that are invisible in the code; existing ones stay.
3. Briefs give paths, not pasted code; split into phases above ~5 points / ~6 files.
4. Auditing: `git diff --stat` first; over ~200 lines → the auditor agent; no `cat` on whole
   files; no Read on `tool-results/`.
5. `implementer` maxTurns lowered 200 → 100.

## What gets measured

- Do agent reports hold the ceiling? (final-report lengths, per agent, per session)
- `raport-lung.sh`: false triggers or loops? `brief-mare.sh`: did it fire when it should?
- Consumption per session against the baseline (target: −15–25% on how fast the
  orchestrator's context fills).
- Does the auditor catch real deviations? (spot check: 1–2 audits also done directly by the
  orchestrator.)

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
```

It reports, per session: input/output/cache tokens per model, estimated cost from
`tools/pricing.json`, the share of output produced in sidechains (subagents), a per-agent
table with the final-report length in characters, the largest `tool_result` payloads, files
read more than once, and images read.

Zero tokens: it is plain Python over local files. The `SessionEnd` hook runs it
automatically and drops the JSON into `metrics-local/` (gitignored).

## Open ideas

- Tighten `raport-lung.sh` to ~1,800 characters if the ceiling is held anyway.
- Session-length discipline: a handoff at every closed milestone. The biggest remaining
  lever, and the one hooks cannot fix — it is a habit.
