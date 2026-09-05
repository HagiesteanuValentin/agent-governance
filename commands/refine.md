Refine on target: $ARGUMENTS
Format: /refine <page | section> [dev-url]. No arguments → ask for the target.

You (the orchestrator) do NOT read the target's code and do NOT propose items off the top of
your head. The flow, in order:

0. Router. Print exactly one line:
   `refine: <page|section> → refiner-complex|refiner`
   `refiner-complex` for a whole page or two or more sections; `refiner` for one section or
   one element. Mixed signals → `refiner-complex`. Slug: the target, lowercased, dashes.
   Effort: run `bash ~/.claude/hooks/effort-phase.sh medium </dev/null` in the same Bash as
   the first command of step 1 (ignore its JSON line); if that result carries `WARN effort`,
   print «You: /effort medium» and wait.

1. Preparation (no agents). At most 3 commands (`ls`, `grep -rl <name>` — file lists only) →
   the list of the target's paths. Then name the spec sections: file + heading from the
   project's DECISIONS / PATTERNS (you do not read them), and `docs/polish/<slug>*.md` if such
   a file already exists (the refiner reuses its numbers instead of asking for new ones).
   If the target does not name the page ("this page", "here") → `AskUserQuestion` immediately,
   before any agent.

2. Two agents in parallel, launched in the SAME message. The files are disjoint (explorer:
   the dossier; scripter: the script, the screenshots, the measurements), neither depends on
   the other's result, only the scripter runs a browser. On the first result notification
   write one line, no action; on the second move to step 3.

   2a. `explorer` — brief:
       Goal: write `docs/refine/<slug>.dossier.md` (≤4,000 characters), the file the refiner
       reads instead of exploring.
       Files: write only that one. Read: the paths below + the named spec sections.
       Target's paths: <the list from step 1>. Spec sections: <file + heading, each>.
       Contents, in this order: the target's structure (sections, components, tokens used,
       line ranges `file:from-to`) · the SITE INVENTORY — reusable components and sections
       from other pages, one line each: name, path, what it does · the spacing, typography and
       color scales from the tokens file · the key rules from the named spec sections, quoted
       short (at most 2 lines each).
       Done when: the file exists, is ≤4,000 characters, every section of the target has a
       line range, the inventory has at least 5 entries or an explicit "the site has no other
       pages", every named spec section is quoted.
       Verification: `wc -c` on the file; `grep -c ':' ` on the ranges.
       Forbidden: commit, push, seed, calls to real services, editing any other file, copying
       whole file contents into the dossier (paths and ranges only).

   2b. `scripter` (Sonnet, high) — brief:
       Goal: write and run `scripts/verify-<slug>.mjs`, which produces the three screenshots
       and `docs/refine/<slug>.measurements.md`. If a script from /polish already exists for
       this slug, adapt it instead of writing a new one.
       The brief gives the line ranges to read (server start/stop, screenshots, hover — you
       take them from `grep -n` on the old script, you do not read it) and names any sibling
       `scripts/masoara-*.mjs` whose measurement functions are reused.
       Files: `scripts/verify-<slug>.mjs`, `docs/refine/<slug>.measurements.md`,
       `docs/refine/<slug>-{mobile,tablet,desktop}.png`.
       The script: ONE browser for the whole run, `browser.close()` in `finally`. Starts and
       stops the dev server itself (also in `finally`) when it does not receive a URL.
       Screenshots: full page, long side ≤1568px — the API downscales anything above, so a
       very tall mobile page is clipped to the requested target, not to the whole page.
       Flags: `--crop "<selector>" <breakpoint>` for one extra crop, `--has "<selector>"` for
       the presence/absence checks used by the ADD/REMOVE acceptances. Idempotent: running it
       twice gives the same numbers.
       The measurements (≤4,000 characters), per section and per breakpoint: box (top,
       height) · padding and gap · font-size, line-height, weight · colors + contrast ratio ·
       image dimensions · offset from the container · empty areas over 120px · the number of
       distinct spacing values and of distinct font-size values (consistency) · overflow · the
       presence or absence of the given selector. Numbers only — no proposed items.
       Done when: the script runs once, exit code 0, the three PNGs exist with the long side
       ≤1568px, the measurements file is ≤4,000 characters and every section from the target
       has a line with numbers at all three breakpoints.
       Verification: run the script; `ls -l` on the three PNGs; `wc -c` on the measurements.
       Forbidden: commit, push, seed, calls to real services, proposing design items, writing
       to any path outside the four files above.

   You never open the screenshots yourself.

3. The refiner (`refiner` or `refiner-complex`, per step 0) — one launch. The brief gives:
   the operator's prompt verbatim · the target · the paths of the target's files (at most 6;
   above that only the line ranges from the dossier) · the dossier path · the measurements
   path · the three PNG paths · the spec sections (file + heading, to be read with `Read`
   `offset`/`limit`) · the plan path `docs/refine/<slug>.md`.
   Ceilings in the brief: at most 5 reads beyond the dossier, each ≤80 lines, reported under
   `READ BEYOND DOSSIER`. Forbidden for it: browser, scripts, `Edit`, extra screenshots,
   commit/push, DECISIONS in full.
   It may ask for ONE extra crop with `CROP NEEDED: <selector> <breakpoint>` → you
   `SendMessage` the scripter to produce it → you `SendMessage` the refiner with the path.
   Once only.

4. Adversarial review (you). First `wc -c` on the plan — the refiner has no Bash and cannot
   check its own ceiling; the plan is ≤10,000 characters. Then read the plan ONCE. Check, in
   this order:
   1. Every SHOULD quotes a number from the measurements or a screenshot.
   2. Every section of the page appears — as an item, or as "OK, no change + reason".
   3. There is at least one ADD from the inventory and at least one REMOVE, or an explicit
      "none, because …" for each.
   4. No item contradicts the named spec sections.
   5. Every acceptance is measurable by `scripts/verify-<slug>.mjs`.
   6. At least one SHOULD is structural (adds, removes, or rearranges) — not only pixels.
   Print the verdict as one line: `refine review: PASS | FAIL (n)`.
   On FAIL → ONE `SendMessage` to the same refiner with the numbered list of failures. The
   second check reads ONLY with `Read` `offset`/`limit` on the ranges from the refiner's
   `CHANGED: <items + lines>` — a second full read is refused. Fails again → `AskUserQuestion`.
   You mark `CUT` only on items that contradict the spec; you do not rewrite items.

5. The operator chooses the items (SHOULD / COULD / MAYBE). Then implementation briefs as in
   Effort: after the operator's approval, run `bash ~/.claude/hooks/effort-phase.sh low </dev/null`
   (ignore its JSON line; the WARN comes on this same result), then print «You: /effort low»
   on its own line and wait for the reply before the first brief.
   /polish step 5: the item numbers + the plan path + the script as the verifier (the "after"
   numbers). The implementer reads its own acceptance criteria from the plan; you do not copy
   them in and you do not read the plan again. The refiner dies after the review; it is not
   relaunched.

Ceilings per /refine: 1 refiner · 1 explorer + 1 scripter · at most 2 `SendMessage` to the
refiner (review + crop) · at most 3 live agents for the skill. `docs/refine/` does not enter
a commit, like `docs/dosar/`. Final report as usual.
