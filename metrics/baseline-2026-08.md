# Baseline — August 2026

Numbers produced by `tools/session_metrics.py` over local Claude Code transcripts.

Labels are anonymised:

- **project-a** — a long-running frontend project, 36 recorded sessions. All of it predates
  the governance rules, so it is the *before* corpus.
- **governance-repo** — this repository. Its first session ran with the full rule set and
  all five hooks active, so it is the *after* sample.

Session ids are truncated to 8 characters.

## Method

- Input: `~/.claude/projects/<project-dir>/*.jsonl`, one JSON object per line.
- Output tokens are summed from `.message.usage.output_tokens` on assistant lines,
  **including subagent (sidechain) turns** — a subagent's output is billed too, and it is
  the part that governance targets.
- Deduplication on `.message.id`: the same assistant message appears on several transcript
  lines (streaming and tool-result attachment), so a naive sum double-counts.
- "Final report (chars)" is the length of the last text-only assistant message in a
  subagent's turn — the thing that actually crosses back into the orchestrator's context.
- Cost is an estimate from `tools/pricing.json`, not a bill.

## Before — project-a, five representative sessions

(The three heaviest, plus two more from the same range. Sessions 549b0aad at 271,624 and
33ed8d91 at 232,917 output tokens also sit above the last row; the table is a sample, not
a top-5.)

| session | output tokens | output in sidechains | est. cost | agent final reports (chars) |
|---|---:|---:|---:|---|
| 012d7594 | 502,859 | 81.5% | $74.01 | implementer 3,343 · scribe 839 |
| bca4ed8b | 412,703 | 79.1% | $51.73 | implementer 3,096 · implementer-max 3,869 · scribe 1,147 |
| 2d02e45a | 341,235 | 73.2% | $40.39 | implementer 3,396 · implementer-max 4,076 · scribe 678 |
| f0ce0336 | 247,374 | 71.3% | $34.47 | implementer-max 3,369 · implementer 2,691 · explorer 7,080 |
| e43d1a60 | 219,539 | 69.6% | $25.18 | implementer-max 5,303 · explorer 10,965 |

Worst final report per agent across the whole 36-session corpus: explorer **11,091** ·
implementer-max **5,303** · implementer **5,126** · scribe **1,639**.

Corpus total, all 36 sessions: **4,638,329 output tokens · 717,007,257 cache-read tokens ·
$687.45 estimated**. Cache reads are ~155× the output tokens — that ratio is the whole
argument: what sits in the orchestrator's context is re-paid on every message.

Worst individual payloads logged by hand before the analyzer existed:

- agent final reports of **4,807 / 5,249 / 4,121** characters in one session, and
  **11,756 / 6,053 / 5,745** in another;
- one `Bash` tool_result of **21,000** characters (a `git diff` and a `cat` of a whole file
  in the same command);
- one `Read` of **31,000** characters against a `tool-results/` directory — re-reading a
  result the orchestrator had already paid for once.

The nominal instruction at the time was "max 25 lines (~2,000 characters)". It was ignored
systematically, because nothing enforced it.

## After — governance-repo, session bad03f47

### The stable metric: agent final-report length

These are the numbers that matter, and the only ones that are already final. A delivery's
report is fixed the moment the agent stops; it does not change afterwards.

| slot | before (project-a, 36 sessions) | after (governed deliveries) |
|---|---:|---:|
| implementer / implementer-max report | 2,691 – 5,303 chars | **1,640** |
| auditor report | no auditor role existed | **1,586** |
| explorer report | up to **11,091** chars | — |
| hand-logged worst case | 11,756 chars | — |

Both governed reports sit above the 1,500-character target but comfortably under the
2,500-character threshold enforced by `raport-lung.sh`. In the *before* corpus, every
implementer report exceeded 2,500 and the worst explorer report was 11,091 — roughly 7×
what the same slot costs now.

### Session totals — interim snapshot, session still open at commit time

Snapshot taken **2026-08-22T13:26Z**, while session `bad03f47` was still running. Treat
these as a partial reading, not a result: they were already ~75% higher than an earlier
snapshot taken 30 minutes before.

| metric | value at snapshot |
|---|---:|
| output tokens | 100,895 |
| output in sidechains | 71.5% |
| cache-read tokens | 5,947,509 |
| est. cost | $10.42 |
| largest `tool_result` | Bash, 28,336 chars |
| second largest | Bash, 18,365 chars |
| largest `Read` tool_result | 15,645 chars |

The final figure for this session is captured automatically by the `SessionEnd` hook into
`metrics-local/<session-id>.json`. This file gets updated from that capture; until then the
session-total row is provisional.

## Honest caveats

- This is not a controlled experiment. project-a is a large frontend build with screenshots
  and 3D work; governance-repo is a documentation and tooling repo. Absolute session totals
  are not comparable, and the *after* session was not even finished when this was written.
- What *is* comparable is the per-report ceiling, because it is the same slot in the same
  workflow regardless of the project: agent final report → orchestrator context. There it
  went from 2,691–11,091 characters down to 1,586–1,640.
- The other structural number to watch is the sidechain share. High is good — it means work
  happened in disposable contexts. project-a already reached 70–81% in its best sessions,
  but with expensive reports crossing back; the goal is to keep the share high *and* the
  crossings small.
- **22 of the 36 before-sessions show 0.0% sidechain output** — no delegation at all, every
  token spent in the orchestrator's own context. Fifteen of those produced real work,
  totalling **1,470,398 output tokens**, about 32% of the corpus. Those are the sessions
  governance exists to prevent.
- Figures marked "hand-logged" (the 21,000-character `Bash` result, the 31,000-character
  `Read` on `tool-results/`, the 4,807–11,756 report lengths) come from a manual analysis
  done before this analyzer existed, and were measured differently. The analyzer's own
  worst `Read` payload in 012d7594 is 624,414 characters — mostly image data — so the two
  sets of numbers are not on the same scale and are kept separate on purpose.

## Reproduce

```sh
python3 tools/session_metrics.py ~/.claude/projects/<project-dir>/
python3 tools/session_metrics.py <session>.jsonl --md --out report.md
```

The label → real project mapping is kept out of this repository.
