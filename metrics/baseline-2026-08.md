# Baseline — August 2026

Numbers produced by `tools/session_metrics.py --trends metrics-local` over local Claude
Code transcripts, regenerated 2026-08-30 with the current `tools/pricing.json`
(Sonnet 5 $2/$10, cache-write 2×). All 59 sessions in `metrics-local/` were re-run through
the analyzer in the same batch, so every number below comes from one consistent price
table — no mix of old and new rates.

## Labels

- The corpus spans several client projects plus this repo (`agent-governance`) itself.
  Client project names are not published: they're grouped only by workflow version, or
  called **project-a/b/c/d** when a distinction matters. No local filesystem paths appear
  below.
- **older** — every session recorded before the `v1.0` rule set existed (2026-08-22 to
  2026-08-26). The 18 kept sessions span 4 projects (a 5th project's only session is the one
  excluded for browser share). This includes the earliest sessions of this very repo,
  already running draft versions of the governance rules before they were formalized as
  `v1.0`.
- **v1.0 / v1.1 / v1.2 / v1.3** — sessions grouped by the workflow version active at their
  start, per `tools/versions.json`. `v1.3` (from 2026-08-30T00:55) has 0 sessions yet.
- Session ids, where one is named individually, are truncated to 8 characters.

## Method

- Input: one jsonl transcript per session, from `~/.claude/projects/<project-dir>/`.
- Output tokens are summed from assistant turns, **including subagent (sidechain) turns**,
  deduplicated on `message.id` (the same assistant message can appear on several transcript
  lines).
- Cost is computed from `tools/pricing.json` (`_updated: 2026-08-30`), which prices
  cache-write at 2× input (1-hour TTL, matching Claude Code's own convention) and Sonnet 5
  at $2/$10 per million input/output tokens.
- Sessions are grouped by workflow version from `tools/versions.json`: a session belongs to
  the last version whose `from` timestamp is ≤ its local start time.
- Excluded from all tables below: sessions where browser tool calls are ≥50% of main tool
  calls, and sessions with no recorded work. Corpus after exclusion: **51 sessions kept
  (2026-08-22 → 2026-08-30) · older 18 / v1.0 8 / v1.1 13 / v1.2 12 / v1.3 0 · excluded: 8
  (browser 1 · empty 7)**.

## Versions

| version | sessions | $ actual | $ actual/session | $ fable-only realistic/session | mean ratio realistic | main output % | hands-on ratio | issues/session (H/M/L) | est. wasted/session | peak ctx | quality (mean · rated/n) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| older | 18 | 372.39 | 20.69 | 72.56 | ×2.8 | 46.1% | 326/607 (54%) | 14.6 (2.2/8.3/4.2) | 73.4k | 144.0k | — · 0/18 |
| v1.0 | 8 | 269.76 | 33.72 | 151.20 | ×4.1 | 50.0% | 175/290 (60%) | 15.9 (1.0/10.4/4.5) | 85.4k | 158.1k | — · 0/8 |
| v1.1 | 13 | 368.90 | 28.38 | 123.41 | ×3.7 | 75.9% | 217/419 (52%) | 10.9 (0.8/6.0/4.1) | 58.4k | 124.0k | 4.5 · 4/13 |
| v1.2 | 12 | 304.40 | 25.37 | 119.36 | ×3.3 | 81.7% | 205/434 (47%) | 10.4 (1.2/5.6/3.7) | 120.8k | 132.6k | 4.3 · 7/12 |
| v1.3 | 0 | 0.00 | 0.00 | 0.00 | ×0.0 | 0.0% | 0/0 (0%) | 0.0 (0.0/0.0/0.0) | 0 | 0 | — · 0/0 |

Δ v1.0 vs older: $ actual/session +63% · ratio +46% · main output % +9% · hands-on % +12% · issues/session +9% · wasted/session +16%
Δ v1.1 vs older: $ actual/session +37% · ratio +33% · main output % +65% · hands-on % -4% · issues/session -25% · wasted/session -20%
Δ v1.2 vs older: $ actual/session +23% · ratio +19% · main output % +77% · hands-on % -12% · issues/session -29% · wasted/session +65%

Column definitions (from `tools/session_metrics.py`):

- **main output %** — `round(100.0 * main["output"] / (totals["output"] or 1), 1)`: main's
  output tokens as % of all output, main plus every subagent (line ~1389).
- **hands-on ratio** — `hands_on / float(tool_calls or 1)`, where `hands_on` counts
  `Read`/`Edit`/`Write` calls plus any `Bash` call whose command does NOT match
  `^(git|ls)\b` (`GIT_LS_RE`), out of all main tool calls (lines ~908–923).
- **$ fable-only realistic/session** — `realistic_usd`, a counterfactual that replays a
  session's real per-call tokens as if every subagent turn ran directly in main's own
  growing context (worker bootstrap dropped, worker content stacked onto main, priced at
  cache-read/cache-write/output rates) (lines ~1098–1127).
- **mean ratio realistic** — mean of `realistic_usd / actual_usd` per session.
- **issues/session (H/M/L)** — mean flagged inefficiencies per session, by severity.
- **est. wasted/session** — mean of summed `est_wasted_tokens` across a session's flags.
- **peak ctx** — mean peak context-window tokens per session.
- **quality (mean · rated/n)** — mean manual `/rate` score, over `rated/n` sessions rated.

## Recurring inefficiencies, older vs latest version with ≥5 sessions (v1.2)

`v1.3` has 0 sessions yet, so `v1.2` is still the latest comparison point.

Same code, older's 18 sessions next to v1.2's 12 (sessions-hit and est. wasted tokens each):

| code | severity | older: sessions · wasted | v1.2: sessions · wasted |
|---|---|---:|---:|
| main_read_files | medium | 14/18 · 88.5k | 10/12 · 35.4k |
| long_agent_report | medium→low | 14/18 · 18.4k | 11/12 · 4.7k |
| reread | high | 13/18 · 269.4k | 9/12 · 414.2k |
| full_read_big_file | medium | 12/18 · 234.8k | 4/12 · 68.7k |
| big_tool_result_main | high | 10/18 · 617.8k | 6/12 · 477.9k |
| agent_reread_own_write | low | 8/18 · 0 | 3/12 · 0 |
| high_context_end | medium | 8/18 · 0 | 4/12 · 0 |
| fable_wrote_code | high | 7/18 · 0 | not recurring |
| too_many_runs | high | 6/18 · 0 | 2/12 · 0 |
| plan_echo | medium | 5/18 · 16.9k | 5/12 · 13.7k |
| batchable_bash | medium | 3/18 · 75.4k | 5/12 · 225.8k |
| long_brief | medium | 3/18 · 384 | not recurring |
| narration_turns | medium | not recurring | 2/12 · 209.2k |

`main_read_files`, `long_agent_report` and `full_read_big_file` dropped sharply (88.5k→35.4k,
18.4k→4.7k, 234.8k→68.7k estimated wasted). `fable_wrote_code` disappeared from the recurring
list entirely. But `reread` got *worse* (269.4k→414.2k) and `big_tool_result_main` is still
the single largest category in both eras (617.8k→477.9k) — the two things the rules have not
fixed yet. `batchable_bash` also grew (75.4k→225.8k).

## The stable metric — agent final-report length

A subagent's final report is fixed the moment it stops; it is the payload that actually
crosses into the orchestrator's permanent context. Figures below are `max` and `median`
character counts, per version and per agent type, read from the `workers[].final_report_chars`
field of each session's JSON (excluding aborted/never-launched worker slots, which record 0).

| version | agent type | n reports | max chars | median chars |
|---|---|---:|---:|---:|
| older | explorer | 12 | 10,965 | 4,532 |
| older | implementer-max | 7 | 5,303 | 3,140 |
| older | implementer | 36 | 4,514 | 2,578 |
| older | auditor | 3 | 2,060 | 1,776 |
| older | design-lead | 2 | 1,567 | 1,411 |
| older | scribe | 21 | 1,540 | 678 |
| v1.0 | implementer-max | 18 | 3,543 | 2,303 |
| v1.0 | explorer | 3 | 3,860 | 2,578 |
| v1.0 | auditor | 8 | 2,780 | 2,282 |
| v1.0 | design-lead | 5 | 2,268 | 2,029 |
| v1.0 | implementer | 3 | 2,273 | 1,919 |
| v1.0 | scribe | 11 | 1,152 | 864 |
| v1.1 | implementer-max | 22 | 4,902 | 1,925 |
| v1.1 | explorer | 10 | 4,063 | 752 |
| v1.1 | scribe | 19 | 3,310 | 706 |
| v1.1 | auditor | 19 | 2,552 | 2,125 |
| v1.1 | design-lead-expert | 7 | 2,479 | 2,228 |
| v1.1 | implementer | 9 | 2,428 | 2,035 |
| v1.2 | implementer-max | 19 | 4,676 | 2,378 |
| v1.2 | explorer | 10 | 4,487 | 2,133 |
| v1.2 | auditor | 18 | 3,321 | 2,134 |
| v1.2 | design-lead-expert | 2 | 2,313 | 2,289 |
| v1.2 | implementer | 4 | 2,379 | 2,130 |
| v1.2 | scribe | 18 | 1,563 | 614 |

Reports still routinely exceed the 1,500-character soft cap and occasionally the 2,000
hard cap (`raport-lung.sh` catches those live). The explorer/implementer-max ceiling has not
come down between `older` and `v1.2` (10,965 and 5,303 vs 4,487 and 4,676) — the cap targets
*typical* reports, not the worst case, and a handful of large ones still get through.

## Honest caveats

- Not a controlled experiment. `older` mixes 4 kept projects, v1.0/v1.1 mix 3 each, v1.2
  mixes 5 — the project count did not shrink over time; absolute dollar figures are not
  comparable across versions regardless.
- `$ actual/session` **increased** from `older` ($20.69) through v1.0/v1.1/v1.2 ($33.72 /
  $28.38 / $25.37) instead of dropping, and `est. wasted/session` also rose (73.4k → 120.8k)
  rather than fell. Neither is explained by more delegation: `main output %` (main's share
  of total output) rose 46.1%→81.7%, i.e. the sidechain share fell 54%→18% — *less* work is
  landing in disposable subagent contexts, the opposite of the intended direction. No cause
  is established here beyond that reading of the numbers.
- `hands-on ratio` fell 54%→47% (older→v1.2) — main is doing proportionally less direct
  file editing among its own tool calls, which is a separate axis from the sidechain-share
  drop above and does not offset it.
- Correction to an older mistake: this document used to cite a 28,336-character `Bash`
  `tool_result` in main for one session. That number came from a scribe subagent's own
  sidechain transcript; the largest `tool_result` actually in that session's main context
  was 4,768 characters.
- "Hand-logged" figures from a manual pass done before this analyzer existed — a
  21,000-char `Bash` result, a 31,000-char `Read` against a `tool-results/` directory, and
  report lengths of 4,807–11,756 chars in two sessions — stay a historical note, not merged
  into the tables above: different measurement, different era.
- `reread` and `big_tool_result_main` are still the two largest wasted-token categories in
  both the oldest and newest ≥5-session cohort; nothing in the rules targets them yet.

## Reproduce

```sh
python3 tools/session_metrics.py <path-to-session.jsonl>... --json --md --out-dir metrics-local
python3 tools/session_metrics.py --trends metrics-local
```

The `<path-to-session.jsonl>` list is every path recorded in the existing
`metrics-local/*.json` files' `path` field. The project → label mapping is kept out of this
repository.
