# bench-haiku

Haiku 5.5 (medium, high) vs the current configuration of the scribe, explorer and explorer-max roles.
3 real tasks per role × 3 arms × 3 runs. Root `$ROOT` = `~/workflow/experimente/bench-haiku` (outside the repo).
Arm = suffix of the agent `cell-<role>-<arm>`. `setup.sh`: env `ARMS_SCRIBE` (default `s55-low h55-medium h55-high`), `ARMS_EXPLORER` (default `s55-medium h55-medium h55-high`, also explorer-max). Other scripts: env `ARMS` = union. Cell = `$ROOT/<role>/<task>-<arm>-<n>`.

## Order of commands
```
python3 extract-briefs.py --spec ... --out $ROOT/tasks            # tasks.json + <task>.md (brief 1)
./setup.sh $ROOT/tasks/tasks.json $ROOT [--dry-run] [--only TASK] [--runs N] [--force]
#   cell-runner launches the cells -> $ROOT/<role>/launch-log.md
python3 collect.py $ROOT/<role>/launch-log.md $ROOT [--only CELL] [--dry-run]   # report.md + meta.json; MODEL_MISMATCH -> exit 1
./verify-scribe.sh $ROOT [--only CELL]                           # diff.patch + verify.json (checks.py)
BENCH_ROOT=$ROOT ./anon.sh <role> <task> [--force]               # blind audit dir + mapping outside it
#   auditor: audit-prompt-explorer.md / audit-prompt-scribe.md -> audit/<role>/<task>/scores.json
python3 metrics.py --results-root /abs/path/to/bench-haiku       # summary.md + summary.json
BENCH_ROOT=$ROOT ./cleanup.sh [--dry-run]                        # deletes cells only
```

## Details
- `setup.sh`: scribe cell = `git archive <commit>` of the task repo, local git with commit + tag `base`, `BRIEF.md` with `{{CELL_DIR}}` replaced and the `<!-- sursa -->` line removed. Explorer cell = empty dir. Idempotent; `--force` rebuilds. `BRIEF.md report.md meta.json verify.json diff.patch` are in `.git/info/exclude`.
- `collect.py`: reads runner rows `<cell-agent> <task> <run> <agentId> <start> <end> <OK|FAIL>` (other lines, e.g. the launch order, are skipped); declared model/effort = frontmatter of `~/.claude/agents/<cell-agent>.md` (`--agents-dir`). Finds `agent-<id>*.jsonl` under `~/.claude/projects/*/subagents/` and `*/*/subagents/` (`--projects-dir`). `report.md` = `SubagentHandback` message or the last assistant text. `meta.json`: turns (unique message ids), tokens per model, peak context (max input + cache per turn), duration, models seen, `status` OK/MODEL_MISMATCH.
- `checks.py <task> <cell>`: hard checks from each brief's definition of done (scribe-T1/T2/T3); `(info)` checks do not affect PASS.
- `anon.sh`: explorer → `report.md`; scribe → `diff.patch` + target files + `report.md`. Replaces model names and arms → `MODEL`, cell names/paths → `CELL`, root → `ROOT`. Refuses to overwrite without `--force`. Also masks model names inside the documents themselves (scribe targets about experiments).
- `metrics.py`: cost via `tools/session_metrics.cost_of` on `usage_by_model`, median (min–max) per role × task × arm, join with `scores.json` through the mapping. Root must be absolute (`docs/RETETE.md` «Benchmark pe celule — capcane la rulare», item 6). `full_runs` is not reported.

Validated 10.10 on a fake tasks.json in /tmp (2 tasks, 18 cells) and on real scribe tasks with the historic after-state: T1 8/8, T2 6/6 hard PASS; T3 has no clean after-state commit.
