Audit the commit range: $ARGUMENTS
Audit session, NOT a fix session — you don't touch code.

Against three sources, in this order:
1. docs/DECISIONS.md — the area touched by the diff (rejected
   ideas reintroduced? caps violated?)
2. The definition of done from the implementation session's plan
   (missing states? skipped breakpoints?)
3. The project's checks: `./scripts/verifica.sh all` if it exists;
   otherwise the `scripts/check_*` / `test_*` scripts relevant to
   the area touched (see docs/RECIPES.md) — run them, attach output.

Deliver: the list of deviations, each with PROOF (screenshot,
measurement, or the exact quote from DECISIONS) + severity
(blocking / to fix / cosmetic). Zero deviations = state
explicitly what you checked and what passed. Don't explore anything
outside the diff + the named files.
