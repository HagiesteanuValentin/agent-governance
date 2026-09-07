# How to use this repo

## 1. What `easy_install.sh` does

Run from a clone of this repo: `bash easy_install.sh [--dry-run] [--yes] [--restore <backup-dir>]`.

Steps, in order:

1. Checks the OS (`OSTYPE`). Linux is tested. On macOS it warns that `tac` may be
   missing (`brew install coreutils`); without it, `main-model.sh` fails open instead
   of failing hard. Windows Git Bash is untested. Anything else aborts.
2. Requires `python3` on PATH (used by the metrics analyzer and by the installer's
   own JSON check).
3. Verifies the directory the script lives in is a real clone of this repo (checks for
   `agents/`, `hooks/`, `commands/`, `templates/`, etc.); aborts otherwise.
4. Prints the plan (what gets replaced, how many agents/hooks/commands) and, unless
   `--dry-run`, asks `[y/N]` to continue (skipped with `--yes`).
5. Backs up `~/.claude/{agents,hooks,commands,skills,settings.json,CLAUDE.md,
   orchestrare*.md}` into `~/.claude-backup-<timestamp>`. If that path already
   exists (same-second re-run), it appends `-2`, `-3`, ... Aborts if the backup
   ends up with fewer entries than the source.
6. Deletes and replaces `agents/`, `hooks/`, `commands/`, `skills/` under
   `~/.claude`, and copies `CLAUDE.md`, `orchestrare.md`, `orchestrare-v17.md`,
   `settings.json` from `templates/` and `hooks/settings.example.json`.
7. Rewrites the `REPO_DIR=` line inside the installed `hooks/session-metrics.sh`
   to point at this clone (or at `$AGENT_GOVERNANCE_DIR` if you set it), so
   `TRENDS.md` generation finds the right repo later.
8. Validates the installed `settings.json` is valid JSON.
9. Prints how many agents/hooks/commands landed, and warns if `orchestrare.md` is over
   10,240 bytes (above that, SessionStart truncates the injected block).

`--dry-run` only prints the plan, writes nothing. `--restore <backup-dir>` reverses
step 6: deletes the current `agents/hooks/commands/skills` and top-level files
under `~/.claude` and copies everything from the backup dir back in, then exits —
it does not run the rest of the install.

**Left untouched, always**: `~/.claude/memory/`, `~/.claude/projects/`,
`~/.claude/plans/`, any `history*` files, and anything outside the
`INSTALLED_FILES`/`INSTALLED_DIRS` list above.

## 2. Why STRICT: settings that break the engine

Some `~/.claude/settings.json` edits silently disable the governance hooks and
agents this repo installs:

- Pinning a specific model for the main session: the guard hooks that check for
  model drift (`main-model.sh`) never trigger, because there's no drift to see.
- `permissions.deny` on `Bash`: the hooks that run through Bash (commit-gate,
  session-metrics, etc.) never fire.
- `disableAllHooks`: turns off every hook installed by `easy_install.sh`, engine
  and all.
- `env` limits that cap tool output: hook stdout/stderr gets truncated, so
  ask/deny decisions and session-metrics can silently lose data.
- Foreign skills or hooks with overlapping triggers (e.g. another `SessionStart`
  or `Stop` hook): they can race or shadow the ones this repo installs.

To recover: restore permissions from the backup written by the installer, either
by hand (`cp ~/.claude-backup-<timestamp>/settings.json ~/.claude/settings.json`)
or with `bash easy_install.sh --restore ~/.claude-backup-<timestamp>`.

**Careful with `--restore`**: it deletes the *current* `~/.claude` install first,
including anything you changed there after the original install (custom hooks,
manual settings edits) — not just the engine's own files.

## 2b. Don't move or delete the clone after install

`easy_install.sh` points `~/.claude/hooks/session-metrics.sh` at this clone's
path. `SessionEnd` runs `tools/session_metrics.py` from there to build
`TRENDS.md`. If you move, rename, or delete the clone, that hook fails silently
and metrics stop. If you must move it, re-run `easy_install.sh`, or set
`AGENT_GOVERNANCE_DIR` to the new path and re-run the installer so the hook
picks it up.

## 3. `/onboarding`

Run once per project, after the engine is installed. It never touches
`~/.claude`. It asks up to 7 questions (language, project type/commands, what
"verified" means, reader level, commit policy, which source-of-truth docs to
create, report length), then writes `./CLAUDE.md` with three sections: `# Rules`
(which docs to read instead of exploring the codebase), `# Preferences` (from
your answers), and `# Engine freeze` (see below). If `CLAUDE.md` already exists,
it asks before appending or writing `CLAUDE.local.md` instead.

## 4. Engine freeze

Once installed, leave `~/.claude` (hooks, agents, `orchestrare.md`) untouched
for the first 5–10 sessions. Change it only on evidence from `TRENDS.md`,
produced by `python3 tools/session_metrics.py`, and never mid-session.

## 5. Platform notes

- **Linux**: tested.
- **macOS**: should work; needs `python3`. The only external command the engine
  depends on that macOS may lack is `tac` (used by `main-model.sh`); without it,
  that hook fails open rather than blocking you. Installable via
  `brew install coreutils`.
- **Windows (Git Bash)**: untested; needs `python3` on PATH.
- **WSL**: works like Linux.
