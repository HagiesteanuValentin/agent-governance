---
description: Set up this project for the governance engine: ask a few questions, write CLAUDE.md.
disable-model-invocation: true
allowed-tools: Bash(test:*), Bash(grep:*), Bash(echo:*)
---

Engine state: !`test -f ~/.claude/orchestrare.md && test -x ~/.claude/hooks/session-start.sh && grep -q session-start ~/.claude/settings.json && echo INSTALLED || echo NOT_INSTALLED`
Project CLAUDE.md: !`test -f ./CLAUDE.md && echo HAS_CLAUDE_MD || echo NO_CLAUDE_MD`
Installer here: !`test -f ./easy_install.sh && echo EASY_INSTALL_HERE || echo EASY_INSTALL_ELSEWHERE`

You are setting up ONE project. Hard limits, no exceptions:

- You do NOT modify anything under `~/.claude` (hooks, agents, orchestrare.md, settings).
- You do NOT propose changes to the engine.
- You do NOT read the codebase to guess answers. If you need a fact, you ASK.

0. If the state above is `NOT_INSTALLED`: the engine is not installed. Do NOT run the
   installer from this session (its `[y/N]` prompt gets EOF and its `rm -rf` on `~/.claude`
   needs a permission you cannot give here). Print, in the user's terminal words:

       bash <clone>/easy_install.sh

   `<clone>` is the current working directory when the state says `EASY_INSTALL_HERE`,
   otherwise write `<path to clone>`. Then: "run `/exit`, start a new session in your
   project, run `/onboarding` again." STOP there. Ask nothing else.

0b. If the state is `INSTALLED` but the `=== ORCHESTRATION ===` block is NOT in your
   context, the hooks were installed after this session started. Say: "hooks installed after
   this session started: `/exit`, new session, `/onboarding`." STOP.

1. Ask, with AskUserQuestion, at most 2 rounds of up to 4 questions. These 7, in order,
   general questions about the project, never about the engine itself:
   1. Language of the answers you will get from agents (English / Romanian / other).
   2. Project type and the build / test / lint commands (offer options + Other).
   3. What "verified" means here: tests pass / build passes / manual check / screenshots.
   4. Reader level: explain the terms as for a junior / senior, terse.
   5. Commit policy: the agent commits after an OK audit (the default in this repo) /
      never commits / asks first.
   6. Source-of-truth documents: do they already exist, or should you create the skeleton
      (`HANDOFF.md`, `docs/PATTERNS.md`, `docs/DECISIONS.md`, empty, one header each)?
   7. Final report: short (default) / detailed.

2. Write `./CLAUDE.md`, at most 80 lines, with exactly three sections:
   - `# Rules` — the sources-of-truth shape from `templates/CLAUDE.project.md`: the agent
     reads the named documents instead of exploring the codebase; phase by phase; verified
     means what answer 3 said. Keep only the documents that answer 6 confirmed.
   - `# Preferences` — at most 20 lines, built from the answers (language, stack and
     commands, reader level, commit policy, report length).
   - `# Engine freeze` — 3 lines: do not modify `~/.claude` hooks, agents or
     `orchestrare.md` for the first 10 sessions; change the engine only on the evidence in
     `TRENDS.md` produced by `python3 tools/session_metrics.py`; never mid-session.

   If the state says `HAS_CLAUDE_MD`, do NOT overwrite it. Ask (AskUserQuestion) whether to
   append `# Preferences` + `# Engine freeze` to it, or to write `CLAUDE.local.md` instead.
   Create the document skeleton only if answer 6 asked for it.

3. Report, at most 6 lines: the files you created or changed, then: "next: start working;
   after 5-10 sessions run `python3 tools/session_metrics.py` and read TRENDS.md before
   touching the engine."
