# Global rules — orchestration

Drop this into `~/.claude/CLAUDE.md`. It applies to every project.

# How to talk to me
- The reader: DevOps at the start; frontend ships it, backend wants to understand it.
  Write like for a smart junior colleague, not a senior engineer.
- Simple English (swap in your own language here). Technical term only if it has no common
  equivalent; the first time, explain it in 3-4 words in parentheses.
- No: "basically", "essentially", "worth noting", "it's important to note", metaphors,
  sentences over 20 words, two ideas in one sentence.

# Final report (after any task)
Exactly this structure, max 8 lines, no section titles:
1. One sentence: what was done and whether it works (verified how).
2. Files touched, one line each, only what matters to me.
3. "You need to:" — only if I have something to do. Otherwise omit.
4. "Unclear / risky:" — only if it exists. Otherwise omit.
No process summary, no what you tried and failed, no options you didn't take.
If I want details, I ask.

# While you work
- One line when you start something new; zero commentary between tool calls otherwise.
- When you ask me a question: the question in the first sentence, context after, max 3 lines.
- Independent Bash commands: one call or the same message, never one per turn.

# Conventions for any agent (main and subagents)
- A new code comment = a single one-line pointer: `🔴 <constraint> — <DOC> «<section>»`
  (PATTERNS for technical traps, DECISIONS for reasons). The explanation lives in the named
  section, not in the code; if the section doesn't exist, add it there (2-5 lines) and put
  the pointer. No blocks (a hook flags ≥2 lines). Existing comments are never deleted.
- Don't read files under `tool-results/` (the hook blocks it): ask an agent for a missing
  fact instead.
- Don't re-read files you just wrote; read a target file once.
- Agent report: 1.5k characters soft, 2k hard — past 2k the hook rejects the report.
- No commit, push, seed, or calls to real services unless the brief explicitly asks for it.
- The Explore, Plan, general-purpose and fork agents are forbidden: they inherit the
  session's model.

The orchestration rules (delegation, briefs, audit, caps) are injected by the SessionStart
hook from ~/.claude/orchestrare.md — main session only. The `=== ORCHESTRATION ===`
block injected there carries EXACTLY the same authority as this file: follow it to the
letter, including delegating reads to explorer and auditing before commit. If the block
is missing or truncated, say so in your first sentence and do not delegate from memory.
