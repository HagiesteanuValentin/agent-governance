# agent-governance

Governance for Claude Code agent sessions: policies, enforcement hooks, and offline
telemetry. Cheap models do the work, the expensive model only plans and audits, and hooks
stop verbose agents from flooding the orchestrator's context.

## The problem

In a multi-agent Claude Code setup, the expensive orchestrator model burns its budget on
things that are not thinking:

- **Verbose agent reports.** A subagent finishes and hands back a 5,000–11,000 character
  essay. All of it lands in the orchestrator's context, permanently.
- **Fat tool results.** One `Bash` call that runs `git diff` and `cat`s a whole file: 21,000
  characters. One `Read` of a `tool-results/` directory: 31,000 characters — re-paying for
  a result already seen once. (Both hand-logged before the analyzer existed; the analyzer's
  own worst `Read` payload in that corpus is 624,414 characters, mostly image data.)
- **Everything is re-paid.** Context is re-sent as cache reads on every following message.
  In the measured corpus, cache-read tokens ran ~155× the output tokens. A large payload
  read once is charged for the rest of the session.

Telling a model "keep it to 25 lines" does not work. It was in the instructions and it was
ignored systematically, because nothing enforced it.

## The solution

Three layers, each doing what the layer above cannot.

**1. Policy — split the roles by cost.**
The orchestrator plans, writes briefs, audits diffs, reports. It does not write code over
~20 lines, does not run commands with large output, does not read whole files. Everything
else runs in a disposable subagent context on the cheapest model that can do the job. Only
conclusions cross back.

There are two executors. `implementer-max` (Opus, high effort, 200 calls) is the DEFAULT
for any brief with logic, a refactor, or debugging. `implementer` (Opus, medium effort, 100
calls) is for simple briefs — CSS, text, config — and for parallel briefs, up to 3 at once
with disjoint file lists. Worker turns and tokens are not a cost to save: the worker's
context dies at the end of the run and only a ≤1,500-character report reaches the
orchestrator. The plan file holds the briefs as `## Brief N` sections; the `Agent` prompt
sent to the worker is ≤10 lines — the path to the plan file, "execute only section N," no
commit — so the orchestrator writes the brief once, not twice. Before reporting, the worker
runs a mandatory self-verify loop (build/tests/type-check/regression as applicable) and
lists anything it could not run, and why, on a `NOT RUN` line of the fixed report.

**2. Enforcement — hooks, not good intentions.**
A `SubagentStop` hook measures the final report and blocks it once if it exceeds 2,000
characters, demanding the compressed fixed format. A `PreToolUse` hook on `Read` warns when
the orchestrator reads a 300+ line file without `offset`/`limit`. Another on `Agent` warns
when a brief exceeds 7,000 characters — the signal that one brief is really three.

**3. Telemetry — offline, zero tokens.**
A `SessionEnd` hook runs a plain-Python analyzer over the session's JSONL transcript and
writes a JSON report to a gitignored directory. No model call, no tokens, no network. It
reports tokens and cost per model, the share of output produced in subagents, per-agent
final-report lengths, the largest tool results, and files read more than once.

## The flow

```
  operator
     │  approves
     ▼
┌──────────────────────────────────────────────────────────┐
│  ORCHESTRATOR  (expensive model, the scarce context)     │
│                                                          │
│   plan ──► brief ─────────┐        ┌────── audit ──┐     │
│    ▲                      │        │               │     │
│    │                      ▼        │               ▼     │
│    │              ╔═══════════════════╗    ╔═════════════╗
│    │              ║   implementer     ║    ║   auditor   ║
│    │              ║  (own context)    ║    ║ (own ctx,   ║
│    │              ╚═══════════════════╝    ║  read-only) ║
│    │                      │                ╚═════════════╝
│    │       report ≤1.5k   │  diff                │
│    │       [raport-lung]  ▼                      │ ≤1.5k
│    │              ┌───────────────┐              │
│    └──── repair ◄─┤   re-audit    │◄─────────────┘
│                   └───────────────┘
│                          │ clean
└──────────────────────────┼───────────────────────────────┘
                           ▼
                    final report ──► operator

  every session end ──► session_metrics.py ──► metrics-local/*.json  (0 tokens)
```

The dashed budget on every arrow crossing back into the orchestrator is 1,500 characters.
That is the whole trick: the diff can be 4,000 lines, but what the expensive model reads
about it is a page.

Audit itself is 3 fixed commands run by the orchestrator: `git diff --stat`, a diff against
the earlier briefs on the same file, and one grep per "unclear/risky" line in the worker's
report. The `auditor` agent is only used above ~200 diff lines, on the 3rd brief touching a
file, or when JS is touched. Findings go back to the still-alive implementer via
`SendMessage` — one message, near-zero bootstrap — instead of spawning a new run.

**/polish (v1.1)**: design-lead writes the plan to a file (≤8k chars), orchestrator reads
only its ≤1.5k report; a router picks the lead — `design-lead` (expensive model) for
components with clear paths, `design-lead-expert` (orchestrator-tier model) for targets
needing direction/taste; large or taste targets take the long route: explorer writes a
dossier (paths + line ranges), implementer writes and runs the measurement script, the lead
reads only the dossier, the numbers and 3 small screenshots, with at most 5 extra reads
reported back — so the expensive lead never reads whole files or writes Playwright.

## Measured results

From `metrics/baseline-2026-08.md`. `project-a` is a 36-session frontend project that ran
without governance; `governance-repo` is this repo's first governed session.

The comparable metric is the **agent final report** — the payload that crosses from a
disposable subagent context into the orchestrator's permanent one. It is the same slot in
the same workflow regardless of project, and it is fixed the moment an agent stops, so it
does not drift.

| agent report slot | before (project-a, 36 sessions) | after (governed) |
|---|---:|---:|
| implementer / implementer-max | 2,691 – 5,303 chars | **1,640** |
| explorer | up to 11,091 chars | — |
| auditor | no auditor role existed | **1,586** |
| worst hand-logged report | 11,756 chars | — |

Both governed reports land under the 2,000-character threshold the `SubagentStop` hook
enforces. The before corpus totals 4,638,329 output tokens against 717M cache-read tokens
(~$687 estimated), and **22 of its 36 sessions show 0% subagent output** — all the work done
in the orchestrator's own context.

Not a controlled experiment: the two projects are different workloads, and the *after*
session was still running when this was written, so its session totals are an interim
snapshot rather than a result. Both caveats, the hand-logged versus analyzer-measured
distinction, and the raw numbers are written out in
[`metrics/baseline-2026-08.md`](metrics/baseline-2026-08.md).

### Fable-only counterfactual

For session `2026-08-26-s2-agent-governance`, actual cost was $12.00 against a Fable-only
floor of $15.78 and a realistic Fable-only estimate of $30.55 — ×1.3–×2.5. Across the 25
sessions kept (`metrics-local/TRENDS.md`; 18 older + 7 v1.0, 3 excluded — 1 browser, 2
empty), actual cost sums to $521.13 ($335.60 older + $185.53 v1.0) against a realistic
Fable-only sum of $2,106.36, mean ratio ×2.9 realistic for older and ×4.2 for v1.0.
Sessions are grouped by workflow version (`tools/versions.json`); from v1.1 (2026-08-28)
each session also gets a manual 1–5 quality rating (`/rate`) so versions compare on
outcome, not just cost. This is a cost counterfactual computed from the real per-call
usage (same calls and outputs, worker bootstrap removed, worker content stacked on the
main context, everything cached); it is not a quality claim — usage data carries no
quality signal, and the 35% context threshold is the operator's, not Anthropic's.

## Reproduce it

Requirements: Claude Code, Python 3.9+. No dependencies.

**Install the agents and hooks**

```sh
git clone <this-repo> ~/agent-governance
cd ~/agent-governance

cp agents/*.md   ~/.claude/agents/
cp hooks/*.sh    ~/.claude/hooks/
chmod +x         ~/.claude/hooks/*.sh
```

Merge the `hooks` block from `hooks/settings.example.json` into `~/.claude/settings.json`.
If you cloned somewhere other than `~/agent-governance`, point the metrics hook at it:

```sh
export AGENT_GOVERNANCE_DIR=/path/to/your/clone
```

**Install the policies**

```sh
cp templates/CLAUDE.global.md  ~/.claude/CLAUDE.md      # orchestration rules
cp templates/CLAUDE.project.md /your/project/CLAUDE.md  # then fill in the brackets
```

**Run the analyzer**

```sh
python3 tools/session_metrics.py ~/.claude/projects/<project-dir>/            # all sessions
python3 tools/session_metrics.py <session>.jsonl --md   --out report.md
python3 tools/session_metrics.py <session>.jsonl --json --out report.json
python3 tools/session_metrics.py ~/.claude/projects/<project-dir>/ --json --md --out-dir metrics-local/  # per-session files
python3 tools/session_metrics.py --rename metrics-local/          # rename old <uuid>.json/.md files
```

`--out-dir DIR` writes one `<name>.json` (with `--json`) and one `<name>.md` (with `--md`)
per session into `DIR`. `--rename DIR` renames old `<uuid>.json`/`.md` files in `DIR` to the
new naming scheme, skipping collisions unless `--force` is given. `--ctx-warn N` sets the
threshold for the `high_context_end` flag (default 150000). Files are named
`YYYY-MM-DD-sN-<project>.json`/`.md` (local start date, Nth session of that project that day
by start time, `<project>` = basename of the working directory); the `.md` report includes
the summary plus the "Inefficiencies" list, an automatic "Postmortem" section with severity
and recommendations, and a Fable-only cost estimate. `--trends DIR` regenerates
`DIR/TRENDS.md`, a cross-session view of recurring inefficiencies. Sessions where at least
50% of the main session's tool calls are `mcp__claude-in-chrome__*` are listed separately
under "Excluded" and do not count toward the numbers (threshold: `--browser-threshold`,
default 0.5; version list: `--versions PATH`). `/rate N [note]` before closing a session
attaches a 1-5 quality rating to it (via the SessionEnd hook); `--rate NAME N` rates a
session after the fact; TRENDS shows the mean quality per version.

Nothing here calls a network service or a model. `metrics-local/` is gitignored so raw
session data never leaves the machine.

## Layout

```
agents/     the agent definitions (explorer, implementer, implementer-max,
            scribe, auditor, design-lead, design-lead-expert) — model, effort,
            maxTurns, allowed tools, fixed report format
commands/   slash commands (polish, rate) — mirrors ~/.claude/commands/
hooks/      the five enforcement hooks + settings.example.json
templates/  CLAUDE.global.md (orchestration policy) and CLAUDE.project.md
            (the sources-of-truth pattern for a project)
tools/      session_metrics.py, the offline transcript analyzer, pricing.json, and
            versions.json (workflow versions: name + start day; TRENDS.md groups
            sessions by version so you can compare before/after a workflow change;
            sessions before the first version are `older`)
docs/       workflow.md — architecture, thresholds, what is measured, how
metrics/    baseline-2026-08.md — the numbers above, with method and caveats
            (metrics-local/TRENDS.md holds the cross-session Fable-only counterfactual,
            and per-session reports include a calls/limit column per worker)
```

## License

MIT. See `LICENSE`.
