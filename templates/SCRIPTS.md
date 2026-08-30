# Scripts — <project>

One line per script; the scripter agent keeps it current; the orchestrator reads it before writing a scripter brief.

| script | what it does | files/pages affected | args | adaptability: easy/medium/hard — what changes | one-off/reusable |
| --- | --- | --- | --- | --- | --- |
| `scripts/verifica-<target>.mjs` | batch screenshots + measurements at given widths | `<target>` pages | `--out <dir>` | easy — swap widths/paths | reusable |
| `scripts/migrate-<x>.py` | one-time find/replace across a file set | `<glob>` | `--dry-run`, `--only <file>` | hard — pattern is specific to this migration | one-off |
