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

## How to rerun

Create the cell agents in `~/.claude/agents/` as copies with a different `effort`/`model`.
Wait ~1–2 min for "New agent types are now available" before launching them. Launch all
cells in one message with byte-identical prompts, so the comparison is apples-to-apples.
Read costs from the Workers table of `tools/session_metrics.py --out-dir`.

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
