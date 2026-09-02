Rate the session: $ARGUMENTS
Format: /rate N [note]. N is an integer 1-5; note is optional free text.

`advisor_score` and `mistakes` are no longer typed in: session_metrics derives them from the
v1.7 block (advisor verdict, ABATERI, low-phase flags, reruns). Do not read the record first.

Validate N is an integer between 1 and 5. If not, say so and stop — no tool calls.
Scale: 5 complete on the first try, zero repairs · 4 one round of small repairs · 3 two
rounds or a deviation caught · 2 partial, repaired or relaunched · 1 unusable; rate the
result, not the cost. Later: `python3 tools/session_metrics.py --rate <session-name> N`.

Otherwise, run exactly ONE Bash command that writes
`${AGENT_GOVERNANCE_DIR:-$HOME/agent-governance}/metrics-local/pending-rating.json` with:
`{"score": N, "note": "<note or empty>", "project": "$(basename "$PWD")", "ts": "<UTC ISO timestamp>"}`
(timestamp from `date -u +%Y-%m-%dT%H:%M:%SZ`). No other keys, no other tool calls, no reads.

Reply with exactly one line: "rated N/5, attaches to the session on close".
