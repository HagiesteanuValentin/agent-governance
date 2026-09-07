Rewrite HANDOFF.md as a SNAPSHOT of the current state. Absolute rules:

1. REWRITE the file FROM SCRATCH. Don't append, don't add per-session sections, don't keep history.
   History lives in git log and commit messages — don't reproduce it.
2. Maximum 60 lines. If it doesn't fit, do NOT compress into the handoff — MOVE it into the durable files:
   - technical rules / code pitfalls → PATTERNS.md
   - design decisions, repealed caps, rejected ideas → docs/DECISIONS.md
   - verification / measurement recipes / commands → docs/RECIPES.md
   - infrastructure / deploy / setup → docs/INFRA.md
   - comment blocks flagged during the session (`cat /tmp/claude-hooks/comentarii-*.jsonl`,
     filtered on the project's `cwd`) → the explanation goes in PATTERNS/DECISIONS (the named
     section), the code keeps a one-line pointer
   (if one of these files doesn't exist in the current project, create it with a minimal header)
3. Fixed snapshot structure:
   ## Now — 2-3 lines: phase, what's shipped, what verdict is pending
   ## Active thread — what's being worked on in the next session, with starting conditions
   ## ⏳ To validate live — table: what | how/where it's judged
   ## Next steps — max 5, in order
   ## Active pitfalls — max 3, ONLY what bites right now
   ## Blocked on others — what's waiting on a client / account / third party
4. Admission test for each line: "does this change what the next session does?"
   If not — either migrate it (durable rule) or delete it (history).
5. Migration happens IN THE SAME session as the rewrite, not "next time".
6. Archiving: any file in docs/ that describes CLOSED work (executed plan, shipped fix,
   consumed audit) moves to docs/arhiva/ and disappears from CLAUDE.md/HANDOFF references.
7. Before writing: verify that every file and command you reference exists at the path
   written (including paths in CLAUDE.md). Don't reference what doesn't exist.

Execution (orchestration):
a. You (Fable) write a BRIEF of max 20 lines with the session's facts: what shipped and on which
   commit, verdicts received, what's waiting on live validation, next steps, active pitfalls,
   what's blocked on others, what needs migrating and to which durable file. If
   `/tmp/claude-hooks/comentarii-*.jsonl` has rows for the project's `cwd`, the brief
   includes the list (file:snippet).
b. You apply rule 4 (the admission test) in the brief. You explicitly name the lines that get
   REMOVED, the ones that get CHANGED, and the ones that get ADDED. The rest stays word for word.
   You send the brief + rules 1-7 to the `scribe` agent, who rewrites HANDOFF.md and does the
   migrations/archiving. For each migration you name the TARGET SECTION (the header in
   DECISIONS/PATTERNS/RECIPES), so the scribe only reads around it, not the whole doc.
c. You verify rule 7 (referenced paths exist) and rule 2 (≤60 lines) on the file written.
d. The command's arguments (e.g. "commit push", verdicts) you treat as usual.

At the end, show me a short diff: what went into the snapshot, what migrated and where.

Argument "go" = autonomous mode (hook `autonom.sh`, per-session marker); after handoff + commit +
push you close the shift without questions and without plan mode.
