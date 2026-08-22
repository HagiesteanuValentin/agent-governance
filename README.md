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

**2. Enforcement — hooks, not good intentions.**
A `SubagentStop` hook measures the final report and blocks it once if it exceeds 2,500
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

Both governed reports land under the 2,500-character threshold the `SubagentStop` hook
enforces. The before corpus totals 4,638,329 output tokens against 717M cache-read tokens
(~$687 estimated), and **22 of its 36 sessions show 0% subagent output** — all the work done
in the orchestrator's own context.

Not a controlled experiment: the two projects are different workloads, and the *after*
session was still running when this was written, so its session totals are an interim
snapshot rather than a result. Both caveats, the hand-logged versus analyzer-measured
distinction, and the raw numbers are written out in
[`metrics/baseline-2026-08.md`](metrics/baseline-2026-08.md).

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
```

Nothing here calls a network service or a model. `metrics-local/` is gitignored so raw
session data never leaves the machine.

## Layout

```
agents/     the five agent definitions (explorer, implementer, implementer-max,
            scribe, auditor) — model, effort, maxTurns, allowed tools, fixed
            report format
hooks/      the five enforcement hooks + settings.example.json
templates/  CLAUDE.global.md (orchestration policy) and CLAUDE.project.md
            (the sources-of-truth pattern for a project)
tools/      session_metrics.py, the offline transcript analyzer, and pricing.json
docs/       workflow.md — architecture, thresholds, what is measured, how
metrics/    baseline-2026-08.md — the numbers above, with method and caveats
```

## License

MIT. See `LICENSE`.
