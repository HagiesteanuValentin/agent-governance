# PATTERNS — technical traps

## Session names

`<day>-<HHMM>-<project>`, derived only from the session itself (first timestamp + `cwd`). The
old `-s<N>-` scheme counted siblings in the transcript directory, so the rank changed whenever
a file appeared or disappeared. Do not reintroduce directory scanning into `session_name`.
A collision (a different session id in the same minute) → `HHMMSS`; `--out-dir` deletes the
record of the same session id saved under another name, so re-analysis doesn't leave duplicates.

## Resumed sessions
On `--resume`, the new transcript copies the old session's messages; they carry the parent's
`session_id`, different from the file name. Their tokens were already billed there, so the
usage of these messages does not enter `main` or `totals` — otherwise the cost is counted
twice. The record keeps `resumed_from` and `inherited_assistant_msgs` as a trace.
Likewise, inherited agent launches have no transcript of their own (`transcript` empty, 0
calls, $0). They stay in the list, but don't enter per-agent counts or costs (scripter runs,
files_changed, $/edit) — otherwise a resumed session doubles the numbers.
A fork is analyzed from its origin through the `continued-in` chain; a fork does not produce
its own record.

## New fields in old records
Records in `metrics-local/` are not re-analyzed on every run, so a new field is missing from
the old ones. In aggregates (averages, $/edit) skip them, don't treat them as 0: the numerator
would come from all sessions, the denominator only from the new ones. Tables show `—`.

## Claude Code — limits verified in docs (2026-09-02)
1. Hook output ≤10,000 characters PER hook command; above that → file + preview. Alternatives
   with no hard cap: CLAUDE.md `@import`, `.claude/rules/`.
2. Only the user changes main's effort: `/effort` (persists per model in settings),
   `effortLevel`/`modelSettings.<model>.effortLevel`, env `CLAUDE_CODE_EFFORT_LEVEL`; the model
   has no tool for it; reloading settings.json live is NOT documented.
3. Hooks receive `effort.level` on stdin (PreToolUse/PostToolUse/Stop/SubagentStop),
   `permission_mode`, `transcript_path`, `session_id`.
4. Subagent frontmatter: `model: sonnet|opus|haiku|fable|inherit|<id>`,
   `effort: low|medium|high|xhigh|max`, `maxTurns`, `tools`, `disallowedTools`.
5. Subagents can launch subagents (depth 3, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`) — this
   project forbids it via `tools` without Agent.
6. SendMessage to a finished subagent resumes it with full history.
7. PostToolUse/PreToolUse hooks run inside subagents as well; stdin carries `agent_id`;
   main-only hooks must guard on it.
8. Multiple PostToolUse hook entries matching the same tool call run without guaranteed
   ordering; a "check the write" hook must gate on `tool_name`, not assume it runs after
   a sibling "do the write" hook for that same call.
9. SessionStart stdin carries `source`: startup|resume|clear|compact|fork. A resumed session
   must not reset per-phase state (e.g. effort level) set by the session it resumes.
10. A real `/effort` command invalidates the messages cache: cache_read 67,818 → 17,234 on
    the next turn (system + tools stay cached); a hook writing `effortLevel` into
    settings.json does not touch the cache (63,240 → 67,818). One rewrite of ~52k tokens
    per switch.
11. An automatic fork (`SessionStart source=fork`, seen when main goes `sessionKind: bg`
    with live subagents) invalidates the cache the same way (69,326 → 14,904), also with
    no effort change (session 1457: 104,536 → 14,904). Undocumented; cannot be disabled.
12. Documented officially: top-level (session) effort invalidates the cache; per-message effort
    keeps it — see issue anthropics/claude-code #61984 (per-message effort).
Source: code.claude.com/docs (hooks, sub-agents, model-config, settings-reference).
- Measured 2026-09-02: editing `settings.json` from a hook does NOT change the live effort (main stayed medium after the hook wrote low); only `/effort` does. PostToolUse does not fire when the tool exits non-zero (PostToolUseFailure does) — a check hook stays silent on failed calls.

## Effort baseline: turns, not lines
An assistant message is written across several lines in `.jsonl` (one per block: thinking,
text, tool_use), all sharing the same `message.id` and the same `usage`. Counted by line, the
corpus gives n=1033 and median output 785; counted by turn (deduplicated on `message.id`
globally across the corpus — a resumed session copies the parent's turns) gives n=403 and
median 502. The counterfactual replaces the output of one TURN, so it uses 502;
`effort-baseline.json` still keeps the per-line figures, so it doesn't look like a regression.

## Effort from the transcript
The `effort` field is written on the `.jsonl` line (not inside the `message` object);
`thinking_tokens` sits under `message.usage.output_tokens_details`, not directly under
`usage`. Whoever parses the transcript for effort/tokens must read both at their correct
level, otherwise it silently comes out `None` instead of an error.

## Percentages with a missing denominator
When attribution to main fails, `main.*` comes out all 0, but `wasted_total` stays large. The
fallback `x / (total or 1)` turns this into absurd percentages (v1.5: 4,807,400%). A 0
denominator means "cannot be computed": the session drops out of BOTH the numerator and the
denominator, and the cell is shown as `n/a`. The rule holds for the percentage saved in the
record too, not only for the one computed at aggregation.

## SessionStart hooks run in parallel
`session-start.sh` has several branches (`rules`, `handoff`, `v17`) that can be invoked
separately. If the effort-reset logic (the `source` case: resume|fork|compact keep it,
otherwise `medium`) lives in only one branch, the other branches read `settings.json` before
the reset has run and show the stale value. The logic lives in a single function
(`reset_effort_for_source`) called by EVERY branch that reads effort, before it reads it.

## sessionId vs session_id in jsonl
`sessionId` (camelCase) equals the file name, but it is REwritten on lines copied at resume;
`session_id` (snake_case) is the process id, survives `/clear`, and can be foreign on a
session's own lines. Neither one alone tells the original from the copy: a line is inherited
only if `session_id` is foreign AND its `uuid` appears in `<dir>/<session_id>.jsonl` (already
billed there). Missing parent → the line is its own; its uuids are read once, into
`_PARENT_UUIDS`. A parent from another project (a different directory) is not detected → the
line comes out as its own.

## The model inside hooks
`hooks/main-model.sh <transcript>` gives the session's model: `GOV_MODEL` (tests) → last
`"type":"assistant"` line with `"model":"claude-…"` (`tac | grep -m1`, not `tail -c`:
tool_results can contain the text `claude-opus`) → `.model` from settings, minus `[1m]` →
`unknown`.
Main's guards (write-mare, brief-mare, the ORCHESTRATION blocks in session-start) act only
when the model contains `fable` or `mythos`; `unknown` is treated as Fable (fail-closed).
The agent branch does not change: agents have their own guards, regardless of model.
A `--model` given from the CLI doesn't show up in `settings.json` (the default key stays) —
the transcript source still catches the real model; if the transcript is missing, the guard
stays active (fail-closed) even on Opus started from the CLI. Blocking (deny) only works from
`PreToolUse` hooks; a `PostToolUse` hook can only warn or log, it cannot stop the action.

## comentarii-cod on MultiEdit
`MultiEdit` sends `tool_input.edits[]`, not `new_string`. The hook glues the `new_string`s
together with a blank line between them: the blank line breaks the comment run, so two
one-line pointers from different edits are not read as a single 2-line block (false deny).
The old `old_string` is glued the same way, so moving a comment doesn't come out as "added".

## Reread after your own write
In an agent's transcript, a rejected `Edit` (`tool_result.is_error`: "file modified since
read", "old_string not found") is not a successful write: the agent genuinely needs a Read.
The hook skips it and keeps looking further back. A `Bash` call that contains the file's
basename (a build/test run on it) resets the counter: the result may call for a reread.
A Read with `offset`/`limit` over ≤60 lines stays allowed — it's a spot check, not a reread.

## Reread after regeneration
A second read of a file that was regenerated in between — by `magick`/`convert`, a build, or
similar — is not waste. The analyzer exempts the Read if an intervening Bash command whose
first word is not read-only (`cat`, `grep`, `ls`, `head`, `git`, …) contains the file's
basename as a whole token. Write/Edit do not exempt: Read → Edit → Read is real waste.

## Bash batching
PreToolUse sees only the command, not the output: "small" means no heredoc and under 200
characters. The counter (`/tmp/claude-hooks/bash-batch-<session_id>`) sits before the RANGE
output, so `sed -n`/`head` are counted; reset on a big command or after 90s. Parallelism
cannot be read from the transcript (at PreToolUse the assistant message with the current
`tool_use_id` isn't written yet): under 3s since the last small call = same message — no
increment, no reset.

## orchestrare.md under 10 KB
`~/.claude/orchestrare.md` and `templates/orchestrare.md` must stay under 10,000 bytes: above
that, the harness truncates the SessionStart block to 2 KB and the session loses rules. On
2026-09-05 the margin was under 5 bytes (9,996/9,997) — any new line needs a compensating cut
elsewhere in the file, not just an addition.

## analyzer: locale
`session_metrics.py` writes `·`, `≤`, `—` in the report. Under `LANG=C`/`LC_ALL=C` (or on
Windows) stdout comes out ascii and the print crashes with `UnicodeEncodeError`. That's why
`main()` forces `reconfigure(encoding="utf-8", errors="replace")` on stdout and stderr,
before any print.

## easy_install.sh
The installer replaces four folders under `$HOME/.claude` with `rm -rf`, so every delete goes
through `safe_rm`: it refuses when `$HOME` is empty or not a directory, and refuses any path
outside `$HOME/.claude`. Line 5 of `hooks/session-metrics.sh` hardcodes
`$HOME/agent-governance`; the installer rewrites that line in the *installed copy* with the
absolute path of the clone, otherwise SessionEnd exits silently and TRENDS.md never appears.
The repo copy stays unchanged, so "settings == example" style comparisons still hold.

## context-agent reads the sub-agent's own transcript
Inside a sub-agent, the `transcript_path` a hook receives is MAIN's transcript, not the
agent's; measuring it counts main's tokens against the agent's budget (blueprint postmortem:
main at 163k-187k while two implementers passed 217k/182k undetected). So `context-agent.sh`
rebuilds `<dir(transcript_path)>/<session_id>/subagents/agent-<agent_id>.jsonl` and returns
without measuring when that file is missing — it never falls back to main's transcript.
</content>
