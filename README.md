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

There are three executors. `implementer` (Opus, medium effort, 100 calls) is the DEFAULT for
any brief, logic included. `implementer-sonnet` (Sonnet 5, high effort, 100 calls) is chosen
at plan time only for briefs with a cheap checker (a `verifica-*.mjs` script, build, test, a
grep that catches failure) and no cross-file JS/TS debugging. `implementer-max` (Opus, high
effort, 120 calls) is an escalation, not a default: only a re-send after a failed audit on
the same brief, or debugging declared at plan time with a written reason; a logic deviation
at audit on Sonnet work goes to `implementer-max`, not a second Sonnet run. Worker turns and
tokens are not a cost to save: the worker's
context dies at the end of the run and only a ≤1,500-character report reaches the
orchestrator. The plan file holds the briefs as `## Brief N` sections; the `Agent` prompt
sent to the worker is ≤10 lines — the path to the plan file, "execute only section N," no
commit — so the orchestrator writes the brief once, not twice. Before reporting, the worker
runs a mandatory self-verify loop (build/tests/type-check/regression as applicable) and
lists anything it could not run, and why, on a `NOT RUN` line of the fixed report.

History: v1.3 (2026-08-30 00:55) added `implementer-sonnet`; v1.4 (2026-08-30 08:53) moved
the default to `implementer` at medium effort and capped a brief at ~150k agent context, on
evidence from 10 large runs (tool errors 0.9% → 5.1% from the first to the last quarter of a
run, cost per call doubled) and Anthropic's published effort curve (medium ≈ −2 points at
half the cost on long-horizon coding); the auditor now fixes mechanical deviations itself
(35/37 audits reported deviations, median fix 526 characters); verification runs once at the
end (12% of 507 verification calls led to a fix). Expected effect: measured on ≥5 v1.4
sessions against v1.2's $23.13/session, not claimed in advance. v1.4b added `scripter`
(cheap model, high effort) and `scripter-complex` (worker model, medium effort) for
repetitive edits before straight-to-worker briefs — same medium-vs-high reasoning as above
(medium ≈ high accuracy at 70–85% cost), on evidence from a $79/6-run day of manual
find/replace and hand-run verification. It also relaxed parallelism to a hard cap of 4 live
agents of any type (see "Parallelism" above).

**2. Enforcement — hooks, not good intentions.**
A `SubagentStop` hook measures the final report and blocks it once if it exceeds 2,000
characters, demanding the compressed fixed format — it fires for background agents too (verified 2026-08-30; the earlier version was silently ignored because it emitted a top-level `decision` instead of `hookSpecificOutput`); the cap is enforced by the brief's report format, and the metric (`long_agent_report`) shows how often it holds. A `PreToolUse` hook on `Read`
denies re-reading a file already read in main, and denies a 300+ line read without
`offset`/`limit` (plans and images stay a warning). Another on `Agent` warns
when a brief exceeds 7,000 characters — the signal that one brief is really three. A third,
`context-agent.sh`, tracks a subagent's own context: a reminder at 150k to wrap up, a deny
on every tool but `Bash` at 220k. A `PostToolUse` hook on `Edit`/`Write`, the only one active in
main and in every worker, flags comment blocks the call just added — a new comment is one
pointer line, the explanation belongs in `PATTERNS`/`DECIZII` — without ever blocking, and
logs them for `/handoff` (`comment_bloat` in the analyzer).

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
report. The `auditor` agent is used above a threshold — `git diff --stat` over 150 lines
changed, more than 3 files, or any `.js/.ts/.mjs/.astro` file with new logic; below it the
orchestrator reads the diff itself, once, no re-reading. The auditor fixes mechanical
deviations directly (≤20 lines/file, ≤3 files, no new logic) and reports them as `FIXED`
with the hunk; the rest go back to the still-alive implementer via
`SendMessage` — one message, near-zero bootstrap — instead of spawning a new run.

**/polish (v1.2)**: design-lead writes the plan to a file (≤8k chars), orchestrator reads
only its ≤1.5k report; a router picks the lead — `design-lead` (expensive model) for
components with clear paths, `design-lead-expert` (orchestrator-tier model, Opus 5 xhigh)
for targets needing direction/taste. The long route (2a explorer → 2b implementer ∥ 2c
expert Phase A → 2d SendMessage Phase B): explorer writes a dossier (paths + line ranges);
implementer writes and runs the measurement script, in parallel with the expert's Phase A,
which writes 3 fixed concepts without data (C1/C2/C3, so "safe" is not an option); Phase B
resumes the same agent via `SendMessage` (no second launch) for synthesis — a backbone
concept plus borrowed parts, with numbers from the measurement script. The orchestrator
reviews the plan against DECISIONS/budget and does the steering by text, not the design.
History: v1.1 (2026-08-28) added the router and the long route; v1.2 (2026-08-29) moved
the expert to Opus 5 xhigh and split it into the two phases above.

**Scripter before repetitive work (v1.4b)**: when a brief has the same edit repeated across
many files, or a check that will run more than once, the first brief goes to `scripter`
(cheap model, high effort) instead of straight to `implementer`. It writes a script under
`scripts/`, runs it dry-run → one-file proof → full run → idempotency check, and logs it in
`scripts/SCRIPTS.md` so the next brief can reuse or adapt it instead of writing a new one.
Motive: one day's transcripts showed 6 repetitive runs costing $79 — manual find/replace
by hand across a CSS file, and a verification script run by hand 21 times in one brief.

**Parallelism (v1.4)**: explorers can run in parallel without asking; the auditor runs on
brief N while the worker runs brief N+1, when the two briefs' file lists are disjoint. Hard
cap of 4 live agents of any type; the analyzer flags a session that goes over it as
`parallel_over_cap`. Reason: parallelism does not change tokens, only wall-clock time.

## Measured results

From `metrics/baseline-2026-08.md`, regenerated 2026-08-30 over 51 kept sessions
(`metrics-local/TRENDS.md`): 18 from before any rule set existed ("older"), down to 12 on
the latest version with ≥5 sessions ("v1.2").

| metric | older (18 sessions) | v1.2 (12 sessions) |
|---|---:|---:|
| $ actual/session | 20.69 | 25.37 |
| main output % | 46.1% | 81.7% |
| issues/session (H/M/L) | 14.6 (2.2/8.3/4.2) | 10.4 (1.2/5.6/3.7) |
| est. wasted/session | 73.4k tokens | 120.8k tokens |
| quality (mean · rated/n) | — · 0/18 | 4.3 · 7/12 |

The comparable structural metric is the **agent final report** — the payload that crosses
from a disposable subagent context into the orchestrator's permanent one. Medians by slot,
older vs v1.2: implementer/implementer-max 2,578/3,140 → 2,130/2,378 chars; auditor
1,776 → 2,134; explorer 4,532 → 2,133; scribe 678 → 614. Full max/median-by-agent-type
tables are in the baseline doc.

Not a controlled experiment: `older`'s 18 kept sessions span 4 projects, v1.2's 12 span
5 — the project mix did not shrink. Two numbers moved the wrong way: `$ actual/session` rose
(20.69 → 25.37) instead of fell, and so did `est. wasted/session` (73.4k → 120.8k). Sidechain
share of output fell 54% → 18% (`main output %` 46.1% → 81.7%) — less work is landing in
disposable subagent contexts, not more. All caveats, the historical hand-logged figures, and
full per-version tables are in [`metrics/baseline-2026-08.md`](metrics/baseline-2026-08.md).

### Fable-only counterfactual

Across the same 51 kept sessions, actual cost sums to **$1,315.45** against a realistic
Fable-only counterfactual of **$5,552.26** — sum ratio **×4.22** (Σ realistic / Σ actual);
the mean per-session ratio across those 51 sessions is **×3.34**. Sessions are grouped by
workflow version (`tools/versions.json`); from v1.1 (2026-08-28) each session also gets a
manual 1–5 quality rating (`/rate`) so versions compare on outcome, not just cost. This is
a cost counterfactual computed from the real per-call usage (same calls and outputs,
worker bootstrap removed, worker content stacked on the main context, everything cached);
it is not a quality claim — usage data carries no quality signal, and the 35% context
threshold is the operator's, not Anthropic's.

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
`DIR/TRENDS.md`, a cross-session view of recurring inefficiencies. It opens with an
executive summary per corpus and per version: spend, savings against the Fable-only
realistic estimate ($ and %, cumulative across versions), estimated waste in tokens and as
% of main input volume, waste grouped into families (reads, agent overhead, orchestration
turns, discipline), and deltas against the previous version and against `older`. Sessions where at least
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
            implementer-sonnet, scripter, scripter-complex, scribe, auditor, design-lead,
            design-lead-expert) — model, effort, maxTurns, allowed tools, fixed report format
commands/   slash commands (polish, rate) — mirrors ~/.claude/commands/
hooks/      the six enforcement hooks + settings.example.json
templates/  CLAUDE.global.md (orchestration policy), CLAUDE.project.md
            (the sources-of-truth pattern for a project), and SCRIPTS.md (the
            per-project reusable-script log the scripter agent keeps current)
tools/      session_metrics.py, the offline transcript analyzer, pricing.json (prices
            re-checked 2026-08-30, cache write = 2× input, 1h TTL), and
            versions.json (workflow versions: name + start day or local minute; TRENDS.md groups
            sessions by version so you can compare before/after a workflow change;
            sessions before the first version are `older`)
docs/       workflow.md — architecture, thresholds, what is measured, how
metrics/    baseline-2026-08.md — the numbers above, with method and caveats
            (metrics-local/TRENDS.md holds the cross-session Fable-only counterfactual,
            and per-session reports include a calls/limit column per worker)
```

## License

MIT. See `LICENSE`.
