# Project CLAUDE.md — template

Drop this at the project root as `CLAUDE.md` and fill in the bracketed parts. The point is
not the content of any one project: it is the *shape*. Every project keeps a small set of
named documents that answer a fixed set of questions, and the agent is told to read those
instead of wandering through the codebase to orient itself.

---

# Rules

- Full specification: `docs/SPEC.md` — read ONLY the section for the current phase.
- Sources of truth (do NOT explore the codebase to orient yourself):
  - `HANDOFF.md` — the current state. A snapshot, not a history. Rewritten at the end of
    every session.
  - `docs/DESIGN.md` — the visual direction: tokens, sections, the animation inventory.
    The spec decides WHAT exists; DESIGN decides HOW it looks and HOW it moves.
  - `docs/PHASE-<n>-PLAN.md` — the approved wireframes and the state matrix for a phase.
    Implemented in the phases that follow; archived once that phase closes.
  - `docs/PHASE-<n>-DONE.md` — the definition of done for a phase, plus the operator's
    verdicts on it. Work is implemented against it, in full. Every new page or component
    gets its section HERE before any code is written.
  - `docs/PATTERNS.md` — the site/module map plus the technical rules.
  - `docs/DECISIONS.md` — adjudicated decisions and REJECTED ideas. Nothing REJECTED comes
    back without a new reason; nothing DECIDED is re-litigated without a new symptom.
  - `docs/RECIPES.md` — how things are verified and measured (only what is specific to this
    project; the generic recipes live in the shared recipes file).
  - `docs/INFRA.md` — deploy, storage, bindings, setup traps.
- Work strictly phase by phase; do not move to the next phase without the operator's OK.
- [Stack constraints — e.g. static site generator, vanilla TS, no UI framework. Name the
  allowed client-side dependencies and where. Any other dependency is discussed before it
  is installed.]
- Budget, stated as hard numbers per regime:
  - strict — [pages]: JS < [N] KB gzip/page, LCP < [N] s, CLS 0
  - the exception — [page]: bundle < [N] KB gzip, LCP on a static poster, CLS 0
  Any new JS is MEASURED before it is written; the gzip number is reported at delivery
  (`[your budget script]`).
- Do not run a build except at the end of a phase. Commands: `[dev]` / `[build]`.

# Design — the whole puzzle, not the pieces

- STOP. Any new visual element or re-polish starts with the DEFINITION OF DONE, not with
  code: all elements · all states (hover/active/focus/reduced-motion/no-JS) · breakpoints
  [min]→[max] · what DECISIONS forbids in that area · the criterion for "good" in words.
  Show it to the operator, who completes it, and only THEN implement against it, in full.
- The polish process: top ~10 proposals → double-check → 3–5 cut with a written reason →
  implement. On a vague verdict ("something's still off"): ask, or take a screenshot,
  BEFORE writing code — never on an assumption.
- Before reporting "done": screenshots at [narrow]/[medium]/[wide] (the recipes in
  RECIPES.md), compared against the definition, the list ticked point by point. No
  screenshots, no "done". Layout changes are shown on a preview BEFORE deploy.
- Verdicts are given on the live build, not on dev, and collected in ONE pass per delivery.

# Handoff — hard rules

- At the end of a session (when the operator says "done"/"let's close" or asks for it):
  rewrite `HANDOFF.md` as a snapshot of the current state. Not a log of what happened.
