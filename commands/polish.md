Polish the target: $ARGUMENTS
Format: /polish <component | section | site> [dev-url]. No arguments → ask for the target.

You (the orchestrator) do NOT read the target's code and do NOT propose items off the top of
your head. The flow, in order:

1. Preparation (no agents). Plan path: `docs/polish/<target-slug>.md`. If the file already
   exists → this is round 2: skip to step 6. Gather for the brief: the target exactly as the
   operator said it, the URL, the paths of the sources of truth that exist (CLAUDE.md,
   docs/DECISIONS.md, PATTERNS.md, docs/RECIPES.md), the breakpoints from CLAUDE.md if you
   know them.
   The target's paths: get them cheaply, without reading code (`ls`, `grep -rl <name>` — file
   lists only). ≤ ~6 clear files → they go straight into the brief. The target is "site" /
   "the whole site" OR the grep does not give a clear list → ONE `explorer` for a map ("the
   list of pages, sections and shared components, with paths and one line on what each is");
   the map goes into the brief. The explorer brings PATHS, not content: the design-lead reads
   the code itself, so that it has file:line evidence. You are also the one who names in the
   brief the relevant SECTIONS from DECISIONS / PATTERNS / RECIPES (the headings); the
   design-lead does not read the docs in full.
   If the target does not name the page ("this page", "here", a component without a page) →
   ask for the page with AskUserQuestion IMMEDIATELY, before any agent.
2. Design-lead: a single run of the `design-lead` agent. Brief: the goal in one sentence, the
   target, the paths (or the map), the plan path, the sections from the sources (headings),
   the URL, breakpoints. The design-lead does not have the Agent tool and does not delegate.
   Ask it for the file in its fixed format. Do not ask it for code. Ceilings in the brief:
   screenshots at 3 widths (the mandatory ones from CLAUDE.md, e.g. 320/390/1200), the states
   (error/success/no-JS/reduced-motion) only where the code or the resting screenshot shows a
   symptom, the measurements through a batch script, not a tool call per element; ~40 turns
   for one page, not 80. Its "before" numbers are the reference for every brief — they are
   not re-measured.
   You also ask it for the reusable verification script `scripts/verify-<slug>.mjs` (contents:
   the "Task with several briefs" rule from CLAUDE.md); the briefs do not rewrite it, they
   only run it.
   Any item that proposes a new technique on an existing asset (cutout from a mask, blend,
   image retouching, filter) gets a 5-minute PROOF on the real file, with the result in the
   item; otherwise the item is marked "feasibility unproven" and the orchestrator treats it
   as a question, not as an item.
3. Adversarial review (you). Read the plan file ONCE. Against:
   DECISIONS (rejected items reintroduced? ceilings?), the JS/CSS budget, the scope the
   operator asked for, the dimensions checklist (a dimension marked "OK" without evidence →
   new item or question). For each item: KEEP / CUT (one-line reason, move it to "Rejected") /
   MERGE / ADD (same format, with acceptance). Rewrite vague items with measurable
   acceptance. Edit the file directly with Edit, change "State: v2 orchestrator".
   Do not launch a second design-lead for this.
   Every numeric acceptance also gets an aesthetic guard in words ("no drawn outline", "not
   darker than the wall") — an item with only a number does not pass; the metric alone
   produced a 0.94 rim that read as a drawn line.
4. The operator's OK. You do NOT read `docs/polish/<target-slug>.md` (no `cat`, `sed`, or
   `wc`) to produce this summary. Show the operator, verbatim, the SUMMARY FOR THE OPERATOR
   section from the design-lead's own report — it already groups the items by visible element
   (button, card, menu, section spacing…), one line per element in plain language with the
   item numbers in brackets, MUST/SHOULD/COULD as group headings, no technical terms, at most
   15 lines — plus its CUT/ADDED BY YOU line and the plan path.
   Wait for: approve all / cut / add. Their changes go into the file before step 5 (ask an
   `explorer` with the item number to apply a change if you need to check the item first;
   never read the plan yourself).
5. Implementation. Split the approved items into sequential briefs under the normal rules
   (ceiling on files and risk, not on count: CSS items in the same file go 8–10 at a time;
   ≤6 files; JS separate from CSS; MUST first). The verification script comes from the
   design-lead (step 2); every brief runs it, none redo the screenshots.
   The prohibitions: as in CLAUDE.md ("The relevant prohibitions"). The brief gives: the plan
   path + the item numbers (the implementer reads its own acceptance criteria from the plan;
   you do not copy them in, you do not read the plan) + the verification (build, screenshots
   at each breakpoint in the downscaled variant, compared by IT against the acceptance).
   PARALLEL briefs (max 3) are allowed when the files are disjoint (e.g. assets/images vs
   CSS, shared tokens/config included), none depends on another's result, at most one runs a
   build/browser (or each has its own port and `--out`); the build is done by the last brief
   or by the orchestrator. Declared at plan time, with the file list per brief. A worktree
   only when the lists cannot be guaranteed disjoint (it costs the dependencies + the merge,
   audited by you).
   For texture/material targets (subjective ones): brief 1 is a PROOF PAGE with 2–3 variants
   side by side (e.g. rim 0.94 / 0.86 / none), the operator's verdict on it, then the
   implementation — a proof costs less than a re-send.
   A PERFORMANCE criterion is mandatory when the items add SVG filters / `feTurbulence` /
   multiple masks / `mix-blend-mode`: the verification script measures the render time at 390
   with the CPU throttled 4× (Playwright CDP `Emulation.setCPUThrottlingRate`), before/after;
   default threshold: paint under 100ms (the operator can change it at plan time).
   Audit after each brief, as in CLAUDE.md ("Audit": 3 commands directly, `auditor` only above
   the threshold). An item delivered and audited →
   mark it in the plan `✔ <date>`.
6. Live verification (the operator). After the last brief, tell them, per element and in the
   same plain style as step 4, what changed and where to look. What they report as incomplete is NOT redesigned: reopen the item or add
   a new one in the SAME file and go straight to step 5. The design-lead is relaunched only
   if the operator asks for a different design direction, not for remaining items.

Ceilings per /polish: 1 design-lead, ≤2 explorers, ≤3 implementation briefs without a new OK
from the operator. Final report as usual.
