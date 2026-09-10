# Recipes — agent-governance

## SubagentStop hook test
A probe agent under `~/.claude/agents/` (sonnet, effort low, maxTurns 6, no Bash/Edit/Write).
Prompt: "write ~3,000 characters; if you get stuck, compress and write COMPRESSED AFTER BLOCK
on the first line". Verdict = the report starts with the marker. Block shape:
`{"hookSpecificOutput":{"hookEventName":"SubagentStop","decision":"block","reason":"…"}}`.
Delete the agent after the test.

Threshold per agent (v1.5): 2,000 characters by default, 6,000 for agents whose name starts
with `explorer-max` (A/B cells with a long report). The SubagentStop payload doesn't carry
`agent_type` — it's inferred from `agent-<agent_id>.meta.json`, the transcript's sibling file
in the same `subagents/`, key `agentType`.

## Regenerate metrics-local after a pricing change
For each `metrics-local/*.json` take its `path` (jsonl), then:
```
python3 tools/session_metrics.py <paths…> --json --md --out-dir metrics-local
python3 tools/session_metrics.py --trends metrics-local
```
`/rate` notes are kept automatically. Check the `quality` count before/after.
`sed -n`/`awk` on the whole TRENDS.md is blocked by bash-mare in main (>300 lines); read it
with `grep -n` filtered to line numbers, or via explorer.

## Hook tests and /rate
`bash hooks/test-hooks.sh` — 39 offline cases, exit 0. `/rate` matches the note by the cwd's
basename and the session time: from another directory it doesn't attach; two sessions on the
same project → the note goes to the first one closed; in a worktree, note it with
`python3 tools/session_metrics.py --rate <name> N`.

## Regenerate TRENDS and invariants
`python3 tools/session_metrics.py --trends metrics-local/` (runs refresh_versions first, so
changing `from` in `tools/versions.json` relabels sessions). Invariants to check after a
change in the TRENDS area: Σ actual across versions = Corpus; the last `saved cumulative` =
Corpus saved; Σ families = Σ codes = version waste; per-session `wasted %` =
`postmortem.wasted_pct_of_main_input` from the JSON, but the cell is `n/a` and the session
drops out of the version average when `main` is 0 (PATTERNS «Percentages with a missing
denominator»). A second run must produce an identical `TRENDS.md` (idempotent).

## Editing live config when the classifier blocks
Order: agent (SendMessage/brief) → if still blocked, `python3 - <<'EOF'` from main that
rewrites the file with `pathlib` (full rewrite, not `sed -i`) → if that still doesn't pass,
the user edits it by hand. Line-wrap check after any edit to `~/.claude/CLAUDE.md`:
`awk 'length > 100' ~/.claude/CLAUDE.md | wc -l`.

## State from the transcript, not from a file (read-mare, test-hooks)
`hooks/read-mare.sh` keeps no state in a separate file: it reads the current session's JSONL
transcript on every call — the current `tool_use` call is already written into the jsonl, so
it's skipped by `tool_use_id` to avoid self-blocking. Rule 0 (deny on `/tool-results/`) applies
to everyone; rules a-c are only for the main session. `hooks/test-hooks.sh` runs the same logic
offline, with synthetic JSONL transcripts on stdin, with no network and no Claude.

## Cleaning up comment blocks in a project (scripter-complex)
Run from the target project's repo. Step 0 (Fable):
`grep -rnE "^\s*(//|/\*|\*|#|<!--)" src/ | wc -l` for the "before" figure; read
`scripts/SCRIPTS.md`. scripter-complex brief (script `scripts/comentarii-pointer.py`,
arguments `--dry-run`, `--only <file>`, `--src src/`):
1) inventory: blocks of ≥2 consecutive comment lines (`//`, `/* */`, `<!-- -->`, `{/* */}`)
per file, with the first line; 2) extraction: each block's text goes into a staging file
`docs/comentarii-extrase.md`, grouped by source file, with anchor `<file>#<n>` and the code
line below the block; 3) replacement in code: the block → one line
`// 🔴 <first line of the block, ≤80 chars> — PATTERNS «<file>#<n>»` (comment syntax per
extension; in `.astro`, no `<`/`>` inside comments — the project's PATTERNS forbids it);
4) verifier: a second `--dry-run` reports 0 blocks, `npx astro check` (or `tsc --noEmit`)
exit 0, a second run = 0 changes. Definition of done in numbers: n files, 234 blocks → 0.
Step 2 (implementer or scribe, separate brief): condenses `docs/comentarii-extrase.md` into
real sections of PATTERNS.md/DECIZII.md (2–5 lines each), rewrites the pointers with the real
section name, deletes the staging file. The audit only reads the `--dry-run` from after and
`git diff --stat`. Why from the target project, not from agent-governance: the project's
CLAUDE.md loads, PATTERNS/DECIZII are the target, `scripts/SCRIPTS.md` belongs to the project,
the hook and the analyzer log on cwd.

## Cell experiment — evaluating a batch
S = `~/.claude/projects/-home-user-projects-my-app/<session>/subagents`
(batch 1 = `eb3b7cff-2e84-44ec-b9de-fe02fa88366c`; batches 2–4 =
`1582af01-4db0-4d07-8298-10b83d183134`; each new batch adds its session's `--subagents-dir`).
R = `metrics-local/experiments/simplu/r<k>`. Steps:
1. `python3 tools/cell_metrics.py --subagents-dir S… --first-run k --min-calls 2
   --exclude-agent <id from r2/EXCLUDE.txt>… --dump-reports R/rapoarte`
2. `node scripts/evalueaza-simplu.mjs ~/workflow/experimente/simplu/<cell>-r<k>
   --report R/rapoarte/<cell>-r<k>.md --json R/<cell>-r<k>.json` × 4 (once per cell)
3. `python3 tools/cell_metrics.py --subagents-dir S… --first-run k --min-calls 2
   --exclude-agent … \
   --results-dir R --md --json --out-dir R`
4. Auditor (Brief 4 in the plan) → `R/audit.md`.

The verifier the cells see is `scripts/verifica-simplu.mjs` (only I1–I8); traps T1–T5 live
only in `scripts/evalueaza-simplu.mjs`, never exposed to the cells.
In fish, `--exclude-agent` is given repeatedly right in the command, not through a variable
with spaces (argparse sees it as a single argument). `--results-dir` must contain the JSON
files of ALL rounds in the session (copy `r2/*.json` into `r3/`, etc.), otherwise status `-`.

## v1.6 hooks smoke test and resuming the batch
Smoke, a NEW session, in this order:
1) `cat tools/session_metrics.py` from main → deny ">300 lines in main → explorer";
   `sed -n '1,40p' tools/session_metrics.py` → passes.
2) Ask main to write 30 lines with Write into `docs/smoke.md` → deny ">20 lines from
   main → scribe/implementer".
3) Staging in a SEPARATE command: `touch smoke.mjs && git add smoke.mjs`, then
   `git commit -m smoke` alone; in auto mode NO prompt appears — the verdict is read from the
   transcript: `grep -c '"permissionDecision\": \"ask'
   ~/.claude/projects/-home-user-projects-my-app/<session-id>.jsonl`
   (session-id = the file `/tmp/claude-hooks/live-<sid>`); then
   `git reset --soft HEAD~1 && git reset smoke.mjs && rm smoke.mjs`.
4) 4 explorers run `python3 -c "import time; time.sleep(180)"` then answer "ok"; check
   `wc -l /tmp/claude-hooks/live-<sid>` = 4 before the 5th one; the 5th one crosses the cap in
   auto mode, the "ask" shows up in the transcript (same grep, PreToolUse:Agent).
5) `ls /tmp/claude-hooks/live-* /tmp/claude-hooks/audit-ok-*` after an audit with VERDICT: OK
   → the marker exists.

Note: in auto mode "ask" is decided by the classifier, not the user; only "deny" stops it.
The decision is in DECIZII «Autoritate hook + commit gate (31.08.2026)».

If a hook wrongly blocks an everyday command: don't disable it, note the command in
HANDOFF «Neclar».

Then steps 1–7 from docs/experiments.md «simplu — lessons from r1 and how to resume».

## Window experiment: orchestrator at two effort levels
A prompt written blind into `task.md`, in the user's voice, with no solution. Start two
sessions from the same commit: `claude --effort <x> --permission-mode plan` (once per
effort). On any question from the orchestrator: "decide for yourself and note the
assumption". `ExitPlanMode` gets rejected — exit with `/exit`, not with kill. Plans land in
`~/.claude/plans/`; find them with
`grep -o '~/.claude/plans/[^"]*\.md' <session>.jsonl` and copy them blind as
plan-K/plan-M plus a `mapping.txt` (written in bash, not in fish — the syntax differs). The
auditor judges by the rubric in `docs/experiments.md`; the user picks the winning effort
without seeing the K/M → real effort mapping.

Trap: plan mode blocks `Write` for subagents (an explorer cannot write `docs/dosar/` while
in plan mode) — the dossier is written after `ExitPlanMode`, or the explorer only reports.

## Migrating session names
`tools/session_metrics.py --migrate-names DIR [--yes]`: run it first without `--yes`
(dry-run), check the list, then with `--yes`. Do the backup YOURSELF beforehand:
`cp -r metrics-local metrics-local.bak-<date>` (the script does not back up; `.gitignore`
covers it). Idempotent — a second run over already-renamed records changes nothing. New
names: `<day>-HHMM-<project>` (HHMMSS only on collision). Old records do NOT get the new
fields (effort, main $ %, scripter) automatically — re-analyze with
`scripts/reanalyze-metrics.sh metrics-local` (manual backup first).
For chronological TRENDS after a migration: `--trends`.

## Effort by phase (v1.7)
Exact flow: 1) you approve the plan → the `ExitPlanMode` hook writes `low` into settings and
injects `effort: settings->low`; 2) on the first successful tool call, the `check` hook
injects, once, `WARN effort effective=medium settings=low -> You: /effort low`; 3) main stops
with "You: /effort low, then go"; 4) `/effort low`, then "go"; 5) a new session (startup)
reverts to medium in settings; a resume keeps it; `EnterPlanMode` writes medium →
`/effort medium` by hand when the WARN appears. Stopping the experiment:
`rm ~/.claude/v17-effort-auto`. Restarting it: `touch ~/.claude/v17-effort-auto`
Trap: `PostToolUse` doesn't fire on a tool with exit≠0.
/polish (step 1) and /refine (step 0): the command runs `effort-phase.sh medium`; step 5,
after approval, `effort-phase.sh low`; same WARN.

## Scripts
`hooks/bash-mare.sh` (PreToolUse/Bash, main session only): blocks big whole-file reads and
big heredocs written straight into the project — the thresholds are `BIG_LINES=300` (lines
read) and `BODY_LINES=20` (heredoc lines).
</content>

## Sync offline_telemetry_script
Manual; the public export script does not cover it:
copy `tools/session_metrics.py` over `session_metrics.py` in the offline_telemetry_script checkout,
then `diff -q` against pricing.json, commit with
`-c user.name=claude_code_king -c user.email=claude_code_king@users.noreply.github.com`,
`push origin main`.
