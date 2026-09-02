# Experiments

Which model/effort to use for read-heavy agents — measured, not assumed.

Reference prices (Anthropic list, 2026-08): Opus 5 $5/$25, Sonnet 5 $2/$10 per MTok.

## 2026-08-30 — explorer: Sonnet 5 medium vs Sonnet 5 high vs Opus 5 low

Setup: same prompt text, 3 cells in parallel, 2 questions with known ground truth.
Q1 = 841 pointers in a real codebase, 1 pointing to a missing section, found by grep + header
check. Q2 = 3 facts from an 870 KB JSONL transcript, parsed with Python.

| cell | Q1 correct | Q1 calls / $ / time | Q2 correct | Q2 calls / $ / time | dossier written (permissionMode plan) |
|---|---|---|---|---|---|
| Sonnet 5 medium (current explorer) | yes | 5 / $0.15 / 29s | yes | 2 / $0.06 / 19s | yes |
| Sonnet 5 high | yes | 6 / $0.16 / 39s | yes | 2 / $0.09 / 21s | yes |
| Opus 5 low | yes | 4 / $0.30 / 26s | yes (+ full, untruncated commands) | 2 / $0.14 / 18s | yes |

Conclusion: all correct, same tool calls. Opus low ≈ 2× cost. Effort moves neither calls nor
cost on a read-dominated agent (the agent is bottlenecked on reading, not reasoning).
`explorer` stays Sonnet 5 medium; Opus low is not adopted. Dossier writing via Bash `cat >`
works under `permissionMode: plan`, 3/3.

## 2026-08-30 — auditor: Opus 5 high vs Opus 5 medium

Setup: same brief file, two real diffs from a comment-cleanup task (35 and 37 files), plus 4
planted deviations in the second diff: a 2-line comment block, a pointer to a missing
section, a pointer without the 🔴 marker, a 1-line doc section. Ground truth = planted recall
+ every disagreement checked with grep. No edits allowed.

Diff B (37 files, 4 planted): high found 4/4 planted, $1.11, 14 calls, 2m38s; medium found
4/4 planted, $1.04, 14 calls, 2m13s — but medium missed 2 real natural deviations (a 40-line
block left in `functions/_lib/email.ts`, 5 pointers deleted without replacement), confirmed
with grep.

Diff A (35 files): high $0.76, 16 calls, 3m05s; medium $0.74, 15 calls, 2m32s — medium missed
the class "31 pointers deleted without replacement = scope silently narrowed" (found by
high); medium flagged more leftover blocks (galerie-fx.css, atelier.css) that high put in
"needs checking".

Conclusion: medium saves 3–6% (cost is dominated by reading the diff, not thinking), and
medium missed the "deleted without replacement" class 3 times. `auditor` stays Opus 5 high;
no `auditor-max`.

## 2026-08-30 — explorer-max: Sonnet 5 medium vs Opus 5 low (6k report)

Setup: byte-identical prompt, 2 cells in parallel, question = per-agent profile of 6 JSONL
transcripts (calls, first Edit + context, chars read before it, top 3 results, chars per tool,
final context); ground truth = the same profile computed independently, plus a check on the
real transcripts at every disagreement. Hook `raport-lung.sh` with a 6,000 cap for `explorer-max*`.

| cell | correct | calls / $ / time | peak ctx | report chars |
|---|---|---|---|---|
| Sonnet 5 medium | yes (0 errors vs ground truth) | 6 / $0.20 / 1m25s | 38.8k | 2,609 |
| Opus 5 low | 1 confirmed error (impl#1: counted a `git log … 2>/dev/null` redirect as the first write, idx 1 instead of 12) + final-context values rounded off by 1–4k | 2 / $0.32 / 39s | 27.6k | 2,346 |

Both reports complete (6 agents × 6 fields); both passed the 6k hook at >2k (the old 2k cap would have blocked both). Conclusion: `explorer-max` = Sonnet 5 medium, maxTurns 60, report ≤6k; Opus low not adopted (1.6× cost, more errors on exact numbers).

## simplu — lessons from r1 and how to resume (2026-09-02)

**What r1 showed**: peak context — opus-low 277.6k, opus-medium 314.1k, sonnet-medium 288.1k,
sonnet-low 121.3k; grades 4/4/3/2. No quality cliff up to 300k for Opus (retry 0, all 5 Edit
failures = "File has not been read yet"). Cost per call is linear in context: Sonnet
$0.03→$0.146 at 250–300k, Opus $0.17–0.25 above 200k. All four cells reported traps T1–T3 as
NOT RUN (r1/audit.md).

**Why it went off the rails (5 causes → fix in place)**: (1) brief line 10 said "read the
whole dossier" (20 files, 6,671 lines) → Opus at 191–217k before the first Edit → r2/r3
briefs now say ranges, ≤150 lines per Read, files 02–08 only the sections named per item;
(2) no context hook on `cell-*` (name filter) → frontmatter hooks in `~/.claude/agents/cell-*.md`:
opus warn 150k / deny 220k, sonnet 100k / 150k; (3) sonnet-medium read 14 src files whole,
Galerie3D 3× → `read-mare.sh` now denies whole reads >300 lines and whole re-reads for
`cell-*`; (4) Edit before Read → brief must say "Read the range, then Edit"; (5) main ran 6
agents at once and hit 251k → `agenti-vii` cap 4 means: launch the 4 cells and NOTHING else
in parallel, auditor only after the cells finish.

**Comparability**: r1 = baseline without enforcement; r2/r3 run with the fixed brief + hooks.
Do not average r1 with r2/r3; report r1 separately. Under the caps an Opus cell may be cut at
220k — count items delivered before the cap as the result, not as a failure of the model.

**Resume protocol (r2, then r3)**: 0. new session, smoke the hooks first (RETETE «Smoke
hook-uri v1.6 și reluarea lotului»); 1. usage window <70% of 5h (a lot ≈ $36, ~20 min);
2. `scripts/cell-teardown.sh simplu r2 --yes` → `scripts/cell-setup.sh simplu r2 --dosar
metrics-local/experiments/simplu/dosar` → `r2/env.txt` (`claude --version`, `date -Iseconds`);
3. one message, 4 Agent calls cell-opus-low/cell-opus-medium/cell-sonnet-low/cell-sonnet-medium
with prompt „Brief: metrics-local/experiments/simplu/input/brief-3.\<cell\>-r2.md. Îl citești
integral și îl execuți. Nu faci commit/push."; 4. wait for all four; 5. RETETE «Experiment
celule — evaluarea unui lot» (cell_metrics.py, evalueaza-simplu.mjs, auditor); killed agents
→ r2/EXCLUDE.txt + `--min-calls 2`; 6. r3 identical; 7. scribe → aggregated table here +
confounds from r1/audit.md, no default decision.

### r2–r4: protocol fără dosar

From r2 on the cells get `input/brief-4.template.md`: no dossier at all, real paths and line
ranges under `src/`, "before" counts taken from `verifica-simplu.mjs` on clean `master`
(I1 33, I2 9, I3 15, I4 3, I6 28, I7 8). The trap items (T1–T5) stay verbatim
— they are the traps. Per-cell briefs come from `scripts/cell-brief.sh <task> <run>
<template>` (same `CELLS` array as `cell-setup.sh`, no `--dosar`); `cell-setup.sh` runs
without `--dosar`. Opus cells now carry context thresholds `--warn 150000 --deny 220000`.
r2 restarts from scratch under this protocol (its `EXCLUDE.txt` stays); r1 and any earlier
r2 are a different design and are not compared with r2–r4.

### r2–r4 results

| cell | run | audit grade | eval ok/fail | ctx@1st edit | ctx peak | calls | cost $ | duration | stop |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cell-opus-low | r2 | 4 | 11/0 | 21.8k | 90.9k | 52 | 2.3461 | 8m 2s | self |
| cell-opus-low | r3 | 4 | 11/0 | 19.6k | 88.7k | 56 | 2.3824 | 8m 1s | self |
| cell-opus-low | r4 | 4 | 11/0 | 20.9k | 88.4k | 58 | 2.3298 | 8m 25s | self |
| cell-opus-low | mean | 4 | 11/0 | — | 89.3k | 55 (52-58) | 2.3528 | 8m9s | self (3/3) |
| cell-opus-medium | r2 | 4 | 10/1 | 20.4k | 92.8k | 62 | 2.5795 | 9m 25s | self |
| cell-opus-medium | r3 | 4 | 9/2 | 19.6k | 92.7k | 60 | 2.6280 | 8m 48s | self |
| cell-opus-medium | r4 | 3 | 9/2 | 20.6k | 98.5k | 51 | 2.3453 | 8m 43s | self |
| cell-opus-medium | mean | — | — | — | 94.7k | 58 (51-62) | 2.5176 | 8m59s | self (3/3) |
| cell-sonnet-low | r2 | 3 | 10/1 | 22.3k | 100.8k | 145 | 2.2136 | 10m 24s | self (145/150 turns) |
| cell-sonnet-low | r3 | 3 | 10/1 | 23.7k | 122.0k | 109 | 2.0921 | 10m 31s | hook warn 100k @100.2k, continued to 122k, self-stop |
| cell-sonnet-low | r4 | 3 | 10/1 | 23.9k | 112.5k | 77 | 1.4743 | 8m 56s | self |
| cell-sonnet-low | mean | — | — | — | 111.8k | 110 (77-145) | 1.9267 | 9m57s | mixed |
| cell-sonnet-medium | r2 | 2 | 9/2 | 22.0k | 116.3k | 145 | 2.3500 | 12m 5s | self (145/150 turns, no hook warn) |
| cell-sonnet-medium | r3 | 3 | 9/2 | 24.5k | 105.7k | 78 | 1.4380 | 9m 25s | hook warn 100k REAL @100.2k, stopped immediately |
| cell-sonnet-medium | r4 | 2 | 8/3 | 22.4k | 104.0k | 150 | 2.1783 | 11m 2s | maxTurns 150/150 cut, no report |
| cell-sonnet-medium | mean | — | — | — | 108.7k | 124 (78-150) | 1.9888 | 10m51s | mixed |

Ordering per lot, identical in all three runs: opus-low > opus-medium > sonnet-low > sonnet-medium.
Opus-low scored 11/0 in all three lots.

Confounds:
- asymmetric context thresholds by design: sonnet warn 100k/deny 150k vs opus warn 150k/deny 220k → the 100k warning stopped sonnet-medium r3 at 78 calls (real, logged in `/tmp/claude-hooks/context-agent.jsonl`, not in the agent jsonl)
- maxTurns 150 cut sonnet-medium r4 with no report (turns spent on rereads: 29 of 49 Reads) and r2 sonnets ended at 145/150; evaluator `not_run_silent` is an artifact when the report is missing
- `npm run check` baseline run once per lot, in the first worktree only
- launch order fixed (opus-low, opus-medium, sonnet-low, sonnet-medium) in one message; prompt cache not controlled
- target repo CLAUDE.md inherited by every cell
- `@supports (mask-image: … var())` regression produced by all cells that touched despre.astro, not caught by verifier nor `npm run check`
- I3 does not discriminate (`grep -v '{'` excludes the 7 dynamic `style="--i"` attributes); I7 has a true-but-misleading premise (Base already has `descriere`) so it measures judgment, not mechanics: alias / rename / justified refusal / not started all appear
- `verify` column in cells.md counts greps/seds on the verifier as verification runs (hook regex `VERIF` in `~/.claude/hooks/context-agent.sh:96`)
- r1 (dossier design) is not comparable and not averaged in

## How to rerun

Create the cell agents in `~/.claude/agents/` as copies with a different `effort`/`model`.
Wait ~1–2 min for "New agent types are now available" before launching them. Launch all
cells in one message with byte-identical prompts, so the comparison is apples-to-apples.
Read costs from the Workers table of `tools/session_metrics.py --out-dir`.
