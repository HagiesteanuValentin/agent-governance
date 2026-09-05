Polish the target: $ARGUMENTS
Format: /polish <component | section | site> [dev-url] [lead=opus|expert]. No arguments →
ask for the target.

You (the orchestrator) do NOT read the target's code and do NOT propose items off the top of
your head. The flow, in order:

1. Preparation (no agents). Plan path: `docs/polish/<target-slug>.md`. If the file already
   exists → this is round 2: skip to step 6; exception: `lead=` given explicitly (stay here).
   "Different direction" goes to step 6 FIRST, which renames the plan to `.v<n>.md` (otherwise
   the second design-lead overwrites v1), then comes back here with signal (c).
   Gather for the brief: the target exactly as the
   operator said it, the URL, the paths of the sources of truth that exist (CLAUDE.md,
   docs/DECISIONS.md, PATTERNS.md, docs/RECIPES.md), the breakpoints from CLAUDE.md if you
   know them. Concepts path: `docs/polish/<target-slug>.concepts.md` (only the expert uses
   it).
   Effort: run `bash ~/.claude/hooks/effort-phase.sh medium </dev/null` in the same Bash as
   the first command of step 1 (ignore its JSON line); if that result carries `WARN effort`,
   print «You: /effort medium» and wait.
   Choosing the design lead, BEFORE any explorer. `lead=` forces it. Otherwise
   `design-lead-expert` (Opus 5 xhigh, two phases) on ≥1 signal: (a) the target is a site / whole page or the
   request is about direction ("premium", "identity", "atmosphere", "I don't like it"), with
   no concrete defect named; (b) material, texture, image, blend, mask; (c) round 2 after
   "different direction"; (d) ≤1 relevant section found in DECISIONS/PATTERNS (the target is
   not constrained). `design-lead` (opus) on: component/section with existing patterns;
   objective defects named by the operator (contrast, spacing, overflow, states, a11y). Mixed
   signals → opus. Write one line: "Design lead: <opus|expert> — <reason>"; the reason goes
   into the brief, on the `Lead:` line.
   Then choosing the ROUTE: the long route (2a-2c) when the lead is expert OR the target is a
   site / whole page / the grep does not give a clear list of paths; the short route (step 2,
   as today) only for opus on a component/section with ≤6 clear files.
   The target's paths — ONLY on the short route (on the long route step 2a pulls them):
   get them cheaply, without reading code (`ls`, `grep -rl <name>` — file
   lists only) and go straight into the brief; the design-lead reads
   the code itself, so that it has file:line evidence. You are also the one who names in the
   brief the relevant SECTIONS from DECISIONS / PATTERNS / RECIPES (the headings); the
   design-lead does not read the docs in full.
   If the target does not name the page ("this page", "here", a component without a page) →
   ask for the page with AskUserQuestion IMMEDIATELY, before any agent.
2. Design lead. Two routes, per the choice from step 1. Either way: a single design lead.
   SHORT ROUTE — a single run of the `design-lead` agent. Brief: the goal in one sentence, the
   target, the paths, the plan path, the sections from the sources (headings),
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
   LONG ROUTE — 2a, then 2b ∥ 2c, then 2d; no text from you between them:
   2a. `explorer` → writes `docs/polish/<slug>.dossier.md` (≤3,000 characters): the target's
       paths with line counts, direct imports (one level), for every relevant section from
       CLAUDE.md / DECISIONS / PATTERNS / RECIPES a `file:from-to`, the path of tokens/theme,
       URL, breakpoints, the screenshot recipe (the range from RECIPES). Paths and ranges
       only, zero copied content. Reports the path + 3 lines.
   2b. `implementer` → writes `scripts/verify-<slug>.mjs` (the "Task with several briefs" rule
       from CLAUDE.md), runs it, writes `docs/polish/<slug>.measurements.md` (≤3,000: numbers
       at each width — positions, dimensions, contrasts, overflow — and the paths of the
       three `-small.png` screenshots). Takes the selectors from the dossier. Does not
       propose items. No URL → just the script with the screenshot part commented out and a
       "no live" line in the measurements.
   2c. ONLY when the lead is the expert: `design-lead-expert`, Phase A, launched in the SAME
       message as 2b. Brief: the goal, the target, the dossier path, the path of
       `docs/polish/<slug>.concepts.md`, the plan path, the reason from `Lead:`, breakpoints.
       No measurements, no code paths, no copied sections — they are in the dossier. The
       exception to "one agent at a time" is declared here: the files are disjoint
       (implementer: `scripts/verify-<slug>.mjs`, `measurements.md`, screenshots; expert:
       `.concepts.md`), only the implementer runs a browser, neither depends on the other's
       result. On the first result notification write one line, no action; on the second move
       to 2d, in the same message.
   2d. `SendMessage` to the expert, on the agentId from launch 2c, ≤5 lines: "Phase B", the
       `measurements.md` path, the plan path. A finished subagent resumes automatically on
       `SendMessage`, with its full context (docs "Resume subagents"); do NOT launch a second
       `design-lead-expert` — that was yesterday's mistake (2 launches, 0 SendMessage).
       When the lead is `design-lead` (opus): 2a → 2b → then the design lead, in series, a
       single phase, no concepts; brief: the goal, the target, the paths of the two files, the
       plan path, the reason from `Lead:`, breakpoints.
       No URL: the implementer delivers the script with the screenshot part commented out and
       "no live" in the measurements; Phase B runs without screenshots.
3. Adversarial review (you). Read the plan file ONCE. Against:
   DECISIONS (rejected items reintroduced? ceilings?), the JS/CSS budget, the scope the
   operator asked for, the dimensions checklist (a dimension marked "OK" without evidence →
   new item or question). For each item: KEEP / CUT (one-line reason, move it to "Rejected") /
   MERGE / ADD (same format, with acceptance). Rewrite vague items with measurable
   acceptance. Edit the file directly with Edit, change "State: v2 orchestrator".
   Do not launch a second design-lead for this.
   The aesthetic guard is required by the design-lead's format, you do not add it: verify
   that every numeric acceptance has a guard in words; missing → ask for it in one
   SendMessage to the live design-lead.
   Plan from `design-lead-expert`: the review is ONLY against DECISIONS / budget / the
   operator's scope / missing dimensions — you do not rewrite taste items. Plus four
   objective checks (not taste): a `## Synthesis` section exists; the backbone concept is not
   "the page as it is + fixes"; at least one MUST has `From:` = the backbone concept; every
   element from "What looks different" of the backbone that survived synthesis has an item
   (otherwise it goes to "Rejected", with a reason). Missing one → a `SendMessage` to the
   live expert (counts in the 3-messages-per-agent ceiling).
   On the long route (either lead), `READ BEYOND DOSSIER` non-empty → note it in the final
   report: the dossier was incomplete, fix the explorer's brief next time.
4. The operator's OK. You do NOT read `docs/polish/<target-slug>.md` (no `cat`, `sed`, or
   `wc`) to produce this summary. Plan from the expert: before the summary show the 3
   `SYNTHESIS:` lines from the report. Show the operator, verbatim, the SUMMARY FOR THE
   OPERATOR section from the design-lead's own report — it already groups the items by
   visible element (button, card, menu, section spacing…), one line per element in plain
   language with the item numbers in brackets, MUST/SHOULD/COULD as group headings, no
   technical terms, at most 15 lines — plus its CUT/ADDED BY YOU line and the plan path.
   After its summary add ONE line of your own: "Cut/added by the orchestrator: P<n> (reason) /
   none".
   Wait for: approve all / cut / add. Their changes go into the file before step 5 (ask an
   `explorer` with the item number to apply a change if you need to check the item first;
   never read the plan yourself). Direction-level replies ("more from C3", "make the backbone
   C2", "cut X") go to the SAME live expert via `SendMessage` → it rewrites the plan; you do
   not launch another lead. Ceiling: 2 such messages per /polish (a 3rd is the CLAUDE.md
   ceiling).
5. Implementation. Split the approved items into sequential briefs under the normal rules
   Effort: after the operator's approval, run `bash ~/.claude/hooks/effort-phase.sh low </dev/null`
   (ignore its JSON line; the WARN comes on this same result), then print «You: /effort low»
   on its own line and wait for the reply before the first brief.
   (ceiling on files and risk, not on count: CSS items in the same file go 8–10 at a time;
   ≤6 files; JS separate from CSS; MUST first). The verification script comes from the
   design-lead (short route) or from implementer 2b (long route); every brief runs it,
   none redo the screenshots.
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
   implementation — a proof costs less than a re-send. Take the variants from the item's
   `Variants` line, do not invent them.
   A PERFORMANCE criterion is mandatory when the items add SVG filters / `feTurbulence` /
   multiple masks / `mix-blend-mode`: the verification script measures the render time at 390
   with the CPU throttled 4× (Playwright CDP `Emulation.setCPUThrottlingRate`), before/after;
   default threshold: paint under 100ms (the operator can change it at plan time).
   Audit after each brief, as in CLAUDE.md ("Audit": 3 commands directly, `auditor` only above
   the threshold). An item delivered and audited →
   mark it in the plan `✔ <date>`.
6. Live verification (the operator). After the last brief, tell them, per element and in the
   same plain style as step 4, what changed and where to look. What they report as incomplete is NOT redesigned: reopen the item or add
   a new one in the SAME file and go straight to step 5. The design lead is relaunched only
   if the operator asks for a different design direction, not for remaining items.
   "Different direction" → rename the plan to `docs/polish/<slug>.v<n>.md`, then step 1 with
   signal (c) active. The dossier, measurements, and `.concepts.md` are reused if the target
   is the same — you do not relaunch 2a/2b. The new expert starts directly in Phase B, with
   the backbone named by the operator (or the remaining concept); Phase A is only redone if
   the operator asks for new concepts.

Ceilings per /polish: 1 design lead (`design-lead` or `design-lead-expert`); the long route
= explorer + implementer + the chosen lead (the expert in two phases, one launch, at most 3
`SendMessage`), not counted in the 3 implementation briefs; ≤2 agents in parallel on the long
route; ≤2 explorers total; ≤3 implementation briefs without a new OK from the operator. Final
report as usual.
