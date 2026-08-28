Rate the session: $ARGUMENTS
Format: /rate N [note]. N is an integer 1-5; note is optional free text.

Validate N is an integer between 1 and 5. If not, say so and stop — no tool calls.

Otherwise, run exactly ONE Bash command that writes
`${AGENT_GOVERNANCE_DIR:-$HOME/agent-governance}/metrics-local/pending-rating.json` with:
`{"score": N, "note": "<note or empty>", "project": "$(basename "$PWD")", "ts": "<UTC ISO timestamp>"}`
(timestamp from `date -u +%Y-%m-%dT%H:%M:%SZ`). No other tool calls, no reads.

Reply with exactly one line: "rated N/5, attaches to the session on close".
