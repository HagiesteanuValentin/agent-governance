# agent-governance

Governance for Claude Code agent sessions: policies, enforcement hooks, and offline
telemetry. Cheap models do the work, the expensive model only plans and audits, and hooks
stop verbose agents from flooding the orchestrator's context.

Current version: **v1.8** (frozen) — the rules aren't changing anymore, it's now being
tested on product sessions (≥3 from 2026-09-05T14:45 onward, until a verdict is reached).
v1.8.1 (2026-09-09) changes nothing in the governance itself: only the analyzer (`tools/session_metrics.py`) was fixed so it stops reporting waste that wasn't there (false `big_tool_result_main` on image reads, false `batchable_bash` on non-mutating chains).
Phase-based effort is back (plan medium / implementation low; as of v1.8.2 a PreToolUse gate
blocks tools until claude_code_king runs `/effort <target>` and types go, Claude Code
2.1.260), the advisor is now mandatory on a wide set of triggers (a-f) and
re-reads the plan in round 2, `bash-mare.sh` nudges main on the 3rd consecutive small Bash
call, Fable 5.1 pricing and 5m/1h cache billing are corrected in the analyzer, the `/refine`
skill (agents `refiner` / `refiner-complex`, both Fable 5.1) ships for single-page changes,
and `orchestrare.md` is kept under 10 KB. Phase-based effort now also runs inside `/polish`
and `/refine` (both commands run the `effort-phase.sh` hook), and the `/refine` scripter
brief asks for line ranges plus per-project measurement scripts. Metrics from
2026-09-05T14:45 (local time) onward are the ones that count for v1.8.

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

There are four executors. `implementer` (Opus 5, low effort, 100 calls) is the DEFAULT for
any brief, logic included. `implementer-complex` (Opus 5, medium effort, 100 calls) is chosen
at plan time for multi-file logic, a non-trivial verifier, or declared debugging.
`implementer-sonnet` (Sonnet 5, high effort, 100 calls) is chosen
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
agents of any type (see "Parallelism" above). v1.4.1 (2026-08-30 evening) fixed
`context-agent.sh` to measure the sub-agent's own transcript instead of main's (it had never
actually enforced the 150k/220k ceiling); tested `explorer` and `auditor` against a
lower-cost cell each — both kept their model/effort, `explorer` on tied accuracy and
`auditor` because the cheaper cell missed silent-deletion deviations; and added a
decision-dossier pattern (`explorer` writes `docs/dosar/<slug>.md` before a >300-line-read
brief) plus two analyzer flags, `tool_results_read` and `late_first_edit`. v1.5 (2026-08-30
evening) routed main's own reading through `explorer`/`explorer-max` instead of direct
`Read`/grep, added `explorer-max` (Sonnet 5 medium, 6k report cap) and four analyzer flags
for the new rules (`main_read_before_first_agent`, `max_without_sendmessage`,
`agent_read_plan_whole`, `edit_via_bash`). v1.5.1 split orchestration out of
`~/.claude/CLAUDE.md` into `~/.claude/orchestrare.md`, injected only into the main session
by `hooks/session-start.sh`, so subagents no longer inherit it. v1.5.2 (2026-08-30 night)
split the SessionStart injection into two hook calls (`rules`, `handoff`) after finding the
combined 12KB output was persisted to a file with only a 2KB preview in context — sessions
had been starting with truncated rules and no handoff; verified on a test session, both
blocks now arrive whole. Same night: killed sessions get no SessionEnd, so their metrics are
recovered by running the analyzer manually. v1.5.3 (2026-09-01) redefined "narration
avoidable" in `tools/session_metrics.py` as a text-only call with no live agent and no
question to the user, adding a `residual_poll` subtype; across 12 sessions this cut avoidable
turns from 62 to 11 (5 of them residual). v1.6 (2026-09-02) added `bash-mare.sh`,
`write-mare.sh`, `commit-gate.sh`, and `agenti-vii.sh`, and gave `context-agent.sh` a
`--scope main` mode plus opt-in per-type thresholds (`--praguri-tip`) — see internal decision
notes, not published. Smoke-tested live 2026-09-02: deny hooks
enforce, ask hooks (commit gate, live-agent cap) are advisory under auto permission mode by
design; v1.6 is tuned for Fable 5.1 as orchestrator. v1.6.1 (2026-09-02) moved the default
implementer to Opus 5 low effort after the "simplu" experiment — see `docs/experiments.md`
«r2–r4 results»: opus-low audit 4/4/4 and eval 11/0 in all three lots at a mean $2.35 per
lot, vs opus-medium 4/4/3, eval 9–10/11, $2.52 (confounds listed in the same section); added
`implementer-complex` (Opus medium) as the plan-time choice for multi-file logic.

## v1.8.2 (2026-09-10)

settings.json does not hot-reload effort, and SessionStart writes the target too late for
the current session. Fix: SessionEnd writes medium for the next launch, and a new PreToolUse
gate denies tools until effective effort matches the `/effort <target>` claude_code_king ran, then
he types go. See `docs/DECIZII.md` «v1.8.2 — effort gate».

## v1.8 (2026-09-05)

Phase-based effort is back: the `~/.claude/v17-effort-auto` flag is set again, since
changelog 2.1.260 states `/effort` no longer rewrites the prompt cache. claude_code_king still runs
`/effort` by hand; the hook only warns. Check the first main call after a switch — if
`cache_read` drops to ~17k and `cache_creation` jumps, remove the flag and go back to
medium constant. The advisor is now mandatory on triggers a-f (2+ JS/TS briefs, hooks or
live config or data migration, claude_code_king's own word, any complex/max brief, 3+ briefs, parallel
implementers or a worktree), and it re-reads the updated plan in round 2. `bash-mare.sh`
adds a main-side nudge on the 3rd consecutive small Bash call.

`subagentPromptCacheTtl` is deliberately left unset: measured on the 2026-09-03 blueprint,
agents already write 100% at 5m (2.21M tokens) and main 100% at 1h (293k). Fable 5.1
pricing is corrected across the analyzer ($10/$50, cache read $1 at 0.1x for calc — claude_code_king is
on subscription; $0.25 is only the informative API price, write 5m $12.50 / 1h $20;
`scripts/pricing-cache-5m.py`): the same blueprint goes $65.87 to $57.72 in total (the drop
comes only from agent 5m writes billed at 1.25x instead of 2x), main stays $19.34 (main
writes 1h cache). The Fable-only floor now runs on `claude-fable-5-1` too (cache read $1,
0.1x): floor $89.44 (1.5x), realistic $556.44 — read orchestration savings on `realistic`,
not floor. Narration was left without a hook: 27 of 88 main calls on that blueprint,
~$0.73, about 1.5% of the session.

New skill `/refine`: like `/polish` but scoped to one page or section, routed to `refiner`
or `refiner-complex` (both Fable 5.1) — see the entry below for the shape. Separately,
`~/.claude/orchestrare.md` and `templates/orchestrare.md` are capped at 10 KB, since the
harness truncates the injected SessionStart block to 2 KB past that size; on 2026-09-05 the
margin was under 5 bytes, so any new line there needs a compensating cut.

Phase-based effort now also runs inside `/polish` and `/refine`: both commands call the
`effort-phase.sh` hook, at step 0/1 and again at step 5 after plan approval. The `/refine`
scripter brief (step 2b) asks for line ranges plus per-project measurement scripts. Metrics from
14:45 (local time) onward are the ones that count for the v1.8 verdict.

## v1.7.5 (stable, 2026-09-03)

New entry `v1.7.5` in `tools/versions.json` (from 2026-09-03T13:04 local): sessions from
now on are grouped separately in TRENDS; v1.7.1–v1.7.4 stay under `v1.7`. The three
v1.7.4 agent guards were validated live on a real agent (read-mare deny on re-reading its
own write, bash-mare additionalContext on the 3rd identical run, comentarii-cod deny on a
2-line comment block); all four offline suites pass (model-gate 25, read-mare 31,
bash-mare 8, comentarii-cod 12). The "verifier runs once, at the end" rule was already
present in the agent definitions; nothing added there.

## v1.7.4 (stable, 2026-09-03)

The effort-split experiment (plan=medium / implementation=low) is dropped; main now runs
Fable 5.1 medium constant. Reason: a real `/effort` rewrites the prompt cache — a
top-level effort change invalidates the cache per Anthropic's API docs, while Claude
Code's docs claimed otherwise (issue `anthropics/claude-code#61984`, unclear whether bug
or intended). Measured on promo-site 2026-09-02: two switches cost ~$3.2 in cache writes,
the low phase saved ~$2.0; low was only ~13% cheaper per main turn across 6 v1.7 sessions.

More enforcement: a model gate `hooks/main-model.sh` — on Opus (non-Fable) main, the
main-only guards (write-mare, read-mare, bash-mare, brief-mare, agenti-vii, commit-gate)
go silent and `SessionStart` no longer injects ORCHESTRATION; `comentarii-cod.sh` moved
to `PreToolUse` and now denies ≥2-line comment blocks in agents (warns in main).

`read-mare` now denies a re-read (agent Read on a path it just Wrote/Edited, no legitimate
Read/Bash-on-basename in between) and denies Read on `.png/.jpg/.jpeg/.webp/.gif` >200 KB in
main (agents unaffected); `bash-mare` warns in `additionalContext` on the 3rd identical
Bash command in an agent's transcript with no edit in between (main unaffected).

New test files: `hooks/test-model-gate.sh`, `hooks/test-comentarii-cod.sh`,
`hooks/test-bash-mare.sh`.

Bug fixes: `settings.json` `effortLevel` restored to medium (the phase hook had left it
on low); test suites no longer depend on live settings (`GOV_MODEL` env var instead).

## v1.7.3 EXPERIMENTAL (2026-09-02)

`/rate N [note]` now takes only the score (1-5) and one line of context; `advisor_score`
and `mistakes` are derived by the analyzer instead of typed by hand (`derive_quality` in
`tools/session_metrics.py`). Rough formula: start at 3, +1 if changes were actually
applied after the plan, +1 if the audit found zero deviations, -1 for ≥3 deviations, -1 if
a NO-GO verdict was implemented anyway, clamped 1-5; `mistakes` sums audit deviations,
low-effort-phase flags, and reruns. Both fields carry a `*_src` tag, `auto` or `manual`.

Bug fixes this round: `main=0` on 33 of 94 metrics records, because `inherited` compared
`session_id` — a process id that survives `/clear` — against the transcript file name; the
fix checks the foreign `session_id` AND that the line's `uuid` is present in the parent's
own transcript (a first attempt keyed on `sessionId` instead double-counted three
sessions, caught by the advisor before it shipped). `write_record` now writes `.json`/`.md`
through a temp file + atomic rename. `hooks/session-start.sh`: the v17 branch read
`settings.json` before the rules branch had written it, so a `/clear` could show a stale
effort — fixed with one shared reset function called from both branches.

The metrics corpus was regenerated: 21 records moved from `main=0` to their real cost,
so `TRENDS.md` and `V17.md` now attribute spend correctly.

## v1.7.1 EXPERIMENTAL (2026-09-02)

Two additions, both gated by a trigger, not always-on. An **advisor** agent (Fable 5.1
high, read-only) is called only for risky plans — see `orchestrare-v17.md` for the exact
a/b/c trigger conditions — and returns a fixed report (verdict, changes, risks, edge
cases, improvements); if it needs more information it asks for it via a `NEED` line
through the orchestrator, never by reading extra files itself. `orchestrare-v17.md` is
injected by a third, separate `SessionStart` hook call because the existing
`orchestrare.md` is already near the 10k-character cap per hook command. Second: effort
now switches by phase — medium while planning, low while implementing — flipped by hooks
around `EnterPlanMode`/`ExitPlanMode`, with a `WARN` line when the setting and the actual
effort disagree. Live-agent cap raised 4 → 6. Metrics: section «T-v17» in
`docs/experiments.md` + `metrics-local/V17.md`. Sessions are labeled `task_class`
(`governance-rd`/`product`), cost is read as `v17.cost_per_turn` (not counterfactual),
and `plan.echo` and `Summary` show up in the per-session report under `metrics-local/`.

**What we're testing**: claude_code_king's theory is that heavy reasoning earns its cost at plan time;
at implementation time governance (briefs, audit, hooks) already does the reasoning's job,
so the expensive second opinion (the advisor) is only worth it when the plan is risky.
Judged over ≥3 real sessions with `/rate`, $ spent by main per phase, and the flags from
`metrics-local`, compared against medium-throughout sessions; conclusion goes in
`docs/experiments.md` «T-v17».

**Known limitations**: switching effort currently needs a manual `/effort low` — the
running session's settings.json is not reloaded live, this was measured, not assumed; no
evidence yet either way for running main itself on low effort.

**v1.7.1 (2026-09-02, evening) — bugs found**: (1) `session-start.sh` reset effort to
medium on any `source` but `resume`; a fork (`source=fork`) hit it and WARN pointed the
wrong way — fixed (blacklist resume|fork|compact, 5 tests); (2) the analyzer saw only the
pre-fork part of a forked session (SessionEnd passes the origin path, fork messages carry
the new id) — fixed (`continued-in` chain, `forked_to`, one record); (3) Anthropic side:
Claude Code auto-forks main when it goes background with live subagents, undocumented,
rewrites the conversation cache (~63k tokens) — feedback filed 2026-09-02. Measured: a
real `/effort` rewrites the messages cache once (~52k); writing settings.json does not.

**2. Enforcement — hooks, not good intentions.**
A `SubagentStop` hook measures the final report and blocks it once if it exceeds 2,000
characters, demanding the compressed fixed format — it fires for background agents too (verified 2026-08-30; the earlier version was silently ignored because it emitted a top-level `decision` instead of `hookSpecificOutput`); the cap is enforced by the brief's report format, and the metric (`long_agent_report`) shows how often it holds. A `PreToolUse` hook on `Read`
(`read-mare.sh`) denies re-reading a file already read in main, and denies a 300+ line read
without `offset`/`limit` (plans and images stay a warning). Another on `Agent` (`brief-mare.sh`)
warns when a brief exceeds 7,000 characters — the signal that one brief is really three. A third,
`context-agent.sh`, tracks a subagent's own context: a reminder at 150k to wrap up, a deny
on every tool but `Bash` at 220k. A `PostToolUse` hook on `Edit`/`Write`, the only one active in
main and in every worker, flags comment blocks the call just added — a new comment is one
pointer line, the explanation belongs in `PATTERNS`/`DECIZII` — without ever blocking, and
logs them for `/handoff` (`comment_bloat` in the analyzer).

**3. Telemetry — offline, zero tokens.**
A `SessionEnd` hook (`session-metrics.sh`) runs a plain-Python analyzer over the session's
JSONL transcript and writes a JSON report to a gitignored directory. No model call, no tokens, no network. It
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

**/refine (v1.8)**: same shape as `/polish` but scoped to one page or section, not a
redesign. A router picks `refiner` or `refiner-complex`; an explorer writes a dossier and a
scripter writes/runs the measurement script plus ≤3 screenshots in parallel; the refiner
writes the plan to `docs/refine/<slug>.md`, the orchestrator reviews it adversarially (one
round, against DECISIONS and the target's spec sections) before claude_code_king picks items to
implement. `docs/refine/` is never committed.

**Scripter before repetitive work (v1.4b)**: when a brief has the same edit repeated across
many files, or a check that will run more than once, the first brief goes to `scripter`
(cheap model, high effort) instead of straight to `implementer`. It writes a script under
`scripts/`, runs it dry-run → one-file proof → full run → idempotency check, and logs it in
`scripts/SCRIPTS.md` so the next brief can reuse or adapt it instead of writing a new one.
Motive: one day's transcripts showed 6 repetitive runs costing $79 — manual find/replace
by hand across a CSS file, and a verification script run by hand 21 times in one brief.
v1.4 also (2026-08-30 afternoon) made the comment policy explicit — a new comment is a
one-line pointer to a PATTERNS/DECISIONS section, never a block — after measuring 49%
comment lines and 234 multi-line blocks in one project's `src/`.

**Parallelism (v1.4)**: explorers can run in parallel without asking; the auditor runs on
brief N while the worker runs brief N+1, when the two briefs' file lists are disjoint. Hard
cap of 4 live agents of any type; the analyzer flags a session that goes over it as
`parallel_over_cap`. Reason: parallelism does not change tokens, only wall-clock time.

**Comments (v1.4)**: a new code comment is a one-line pointer, `🔴 <constraint> —
PATTERNS/DECISIONS «section»`, never an explanatory block — the explanation lives in the
doc section, not the code. Enforced by `hooks/comentarii-cod.sh` (PreToolUse on
`Edit|Write|MultiEdit`, main and every subagent; sub-agents are denied on a block or an
over-long comment line, main only gets a warning),
which logs every flagged Edit/Write to a JSONL file read by `/handoff`; the analyzer's
`comment_bloat` flag caught it in 178 of 257 past sessions.

**Decision dossier (v1.4.1)**: a brief that needs >300 lines of decision material read
(docs excerpts, config, comments, transcripts) before the first `Edit` sends `explorer`
first — it writes `docs/dosar/<slug>.md` (Bash `cat >`, works under `permissionMode: plan`)
and the implementer gets the path plus line ranges instead of whole files.
`late_first_edit` flags an implementer/scripter whose first write comes late anyway (≥100k
context or ≥15 reading calls); `tool_results_read` flags any worker reading a
`tool-results/` file instead of re-running the command narrower. Reason: on one postmortem,
the first `Edit` landed at call 29 of 41 (197k context, 242k characters read first).

**Reading through explorers (v1.5)**: main reads only `git diff --stat`, agent reports and
one dossier — facts over 3k characters go to `explorer`, table-shaped answers to
`explorer-max` (Sonnet 5 medium, 6k report cap, per-agent cap in `raport-lung.sh`). Each
agent gets its brief as its own file, never the whole plan. After a non-compliant audit the
order is auditor-fix → `SendMessage` to the live implementer → `implementer-max` only for
logic deviations with a written reason. The analyzer flags `main_read_before_first_agent`,
`max_without_sendmessage`, `agent_read_plan_whole`, `edit_via_bash`. Reason: on one
postmortem (s10) main read 64k characters before the first agent because "the table didn't
fit in 2k"; on another (s1) two `implementer-max` runs cost $7.8 for 9 of 10 deviations that
were mechanical.

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

Requirements: Claude Code, Python 3.6+ (no f-strings, no walrus, no `match`; 3.7+
recommended). No dependencies, no config file needed.

Comments shaped `🔴 … — DECIZII/PATTERNS «…»` are pointers to internal decision notes
not included in this repo. The regexes with Romanian diacritics target the Romanian
wording of agent reports from the author's own system.

**Quick install**

```sh
git clone <this-repo> ~/agent-governance
bash ~/agent-governance/easy_install.sh
```

Backs up your current `~/.claude` first and asks for confirmation. See `HOW_TO_USE.md`
for what it changes, what `--dry-run`/`--restore` do, and settings that break the engine.

**Install the agents and hooks**

```sh
git clone <this-repo> ~/agent-governance
cd ~/agent-governance

cp agents/*.md   ~/.claude/agents/
cp commands/*.md ~/.claude/commands/
cp hooks/*.sh    ~/.claude/hooks/
chmod +x         ~/.claude/hooks/*.sh
```

`jq` is only needed by `hooks/test-main-guards.sh`.

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

`~/.claude/CLAUDE.md` stays small — addressing, report format, conventions any agent needs.
The orchestration rules (which agent for which task, escalation, parallelism caps) live in
`~/.claude/orchestrare.md` instead, injected by `hooks/session-start.sh` only into the main
session, never into subagents. Install: `cp templates/orchestrare.md ~/.claude/orchestrare.md`,
the hook itself into `~/.claude/hooks/`, and the SessionStart entry from
`hooks/settings.example.json` into `~/.claude/settings.json`.

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
`YYYY-MM-DD-HHMM-<project>.json`/`.md` (local start date and time, `HHMMSS` if another
session started the same minute, `<project>` = basename of the working directory);
`--migrate-names DIR` renames files left over from the old `-sN-` scheme (dry-run without
`--yes`).

Run it on a single transcript and check the tests:

```sh
python3 tools/session_metrics.py --md ~/.claude/projects/<project-dir>/<session>.jsonl
python3 tools/tests/test_v17.py     # expected: 0 failed
```

`tools/pricing.json` is optional: without it every cost is reported as `0.0`, one WARN line
goes to stderr, and all other metrics are unaffected. On a session with no subagents and no
governance hooks the `## v1.7` block (effort phases, advisor, low phase) is empty, while the
generic metrics — turns, tool calls, context, reads, inefficiencies, postmortem — are all
filled in.

The `.md` report includes
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
agents/     the agent definitions (explorer, implementer, implementer-complex, implementer-max,
            implementer-sonnet, scripter, scripter-complex, scribe, auditor, design-lead,
            design-lead-expert, refiner, refiner-complex) — model, effort, maxTurns, allowed
            tools, fixed report format
commands/   slash commands (polish, refine, rate) — mirrors ~/.claude/commands/
hooks/      the 14 enforcement hooks + 10 tests + settings.example.json
templates/  CLAUDE.global.md (orchestration policy), CLAUDE.project.md
            (the sources-of-truth pattern for a project), and SCRIPTS.md (the
            per-project reusable-script log the scripter agent keeps current)
tools/      session_metrics.py, the offline transcript analyzer, pricing.json (prices
            re-checked 2026-08-30, cache write = 2× input, 1h TTL), and
            versions.json (workflow versions: name + start day or local minute; TRENDS.md groups
            sessions by version so you can compare before/after a workflow change;
            sessions before the first version are `older`)
docs/       PATTERNS.md — recurring technical traps; RECIPES.md — step-by-step procedures;
            experiments.md — model/effort A-B tests for read-heavy agents (explorer, auditor);
            postmortem — incident writeups
metrics/    baseline-2026-08.md — the numbers above, with method and caveats
            (metrics-local/TRENDS.md holds the cross-session Fable-only counterfactual,
            and per-session reports include a calls/limit column per worker)
```

## License

MIT. See `LICENSE`.
