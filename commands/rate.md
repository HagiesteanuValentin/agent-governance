Rate the session: $ARGUMENTS
Format: /rate N [--advisor M] [--mistakes K] [note]. N is an integer 1-5; --advisor M and
--mistakes K are optional integer flags (any position after N); note is optional free text
(the remaining, non-flag words).

Before rating, if the session record has `v17.advisor`, show `verdict` / `n_schimbari` and `v17.low_phase.audit_abateri_total` so `--advisor` has a basis.

Validate N is an integer between 1 and 5. If not, say so and stop — no tool calls.
Scale: 5 complete on the first try, zero repairs · 4 one round of small repairs · 3 two
rounds or a deviation caught · 2 partial, repaired or relaunched · 1 unusable; rate the
result, not the cost. Later: `python3 tools/session_metrics.py --rate <session-name> N`.

Otherwise, run exactly ONE Bash command that writes
`${AGENT_GOVERNANCE_DIR:-$HOME/agent-governance}/metrics-local/pending-rating.json` with:
`{"score": N, "note": "<note or empty>", "project": "$(basename "$PWD")", "ts": "<UTC ISO timestamp>"}`
(timestamp from `date -u +%Y-%m-%dT%H:%M:%SZ`), plus `"advisor_score": M` when --advisor was
given and `"mistakes": K` when --mistakes was given (omit each key entirely when its flag is
absent). No other tool calls, no reads.

Reply with exactly one line: "rated N/5, attaches to the session on close".
