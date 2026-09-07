# Postmortem 2026-09-01 — Fable 5.1

## 1. What happened (s2 vs s3)

| metric | s2 | s3 |
|---|---|---|
| tool calls (main) | 32 | 82 |
| Read direct | 0 | 1 |
| Write+Edit (main) | 1 | 20 |
| agents | 5 | 21 |
| narration blocks | 6 | 22 |
| waste | 47.8k (11.6%) | 439.9k (32.6%) |
| cost | $10.07 | $76.20 |

s3 agent mix: auditor×3, explorer×1, explorer-max×3, implementer-sonnet×1, scribe×1, scripter×1, scripter-complex×2, cells×9.

s3 flags: fable_wrote_code×5, parallel_over_cap 6>4, plan_echo 20.4k, main_read_files×4, full_read_big_file×38, high_context_end 251.6k.

For reference, s1 (31.08, fable-5): tool calls 34, Read direct 2, Write+Edit main 3, agents 3, narration 5, waste 58.4k (14.8%), cost $7.32.

## 2. Why the cells hit 300k

| cell | peak ctx | ctx@1st edit | dossier read | whole src files | verify tok |
|---|---|---|---|---|---|
| opus-low | 277.6k | 216.6k | all 20 files | 1 | <4k |
| opus-medium | 314.1k | 191.0k | all 20 files | 4 (read twice) | <4k |
| sonnet-medium | 288.1k | 72.9k | 4 of 20 | 14+ | <4k |
| sonnet-low | 121.3k | 47.5k | 4 of 20 | 0 | <4k |

Cell tool calls / Read chars: opus-low 160 / 343.3k; opus-medium 150 / 436.5k; sonnet-medium 171 / 289.0k; sonnet-low 103 / 24.4k.

Brief line 10, identical in all 4 briefs: "Read the docs/dosar/simplu/ dossier in full, file by file (Read, in number order)" (20 files, 6,671 lines). `context-agent.sh` skips cell-* (name filter, only implementer*/scripter*).

## 3. Degradation curve (per 50k bucket: calls | Edit/Write | ed_fail | reread | verify(fail) | out_tok | cost$ | $/call)

cell-opus-low:
0-50: 9|0|0|0|0|42|1.12|0.125; 50-100: 6|0|0|0|0|14|1.70|0.283; 100-150: 5|0|0|0|0|63|1.28|0.255; 150-200: 15|0|0|0|2(1)|93|3.89|0.260; 200-250: 72|40|0|3|0|2486|11.96|0.166; 250-300: 53|33|1|4|1(0)|1121|9.13|0.172

cell-opus-medium:
0-50: 9|0|0|0|0|22|0.87|0.096; 50-100: 6|0|0|0|0|42|2.02|0.337; 100-150: 6|0|0|0|0|93|1.14|0.189; 150-200: 15|6|0|0|0|529|3.72|0.248; 200-250: 26|12|0|1|0|1085|5.37|0.206; 250-300: 65|39|1|3|0|1331|13.66|0.210; 300+: 23|14|0|2|2(1)|230|5.31|0.231

cell-sonnet-low:
0-50: 23|2|0|0|0|444|0.72|0.031; 50-100: 64|30|1|1|0|5527|1.97|0.031; 100-150: 16|0|0|0|2(2)|67|0.89|0.056

cell-sonnet-medium:
0-50: 17|0|0|0|0|392|0.63|0.037; 50-100: 27|18|0|1|0|721|0.90|0.033; 100-150: 24|8|1|1|1(0)|134|1.58|0.066; 150-200: 27|9|0|0|0|145|2.09|0.077; 200-250: 31|17|1|0|0|215|2.81|0.091; 250-300: 45|17|1|1|2(2)|609|6.55|0.146

Notes: retry (Edit loops on same hunk) = 0 in all cells; all 5 ed_fail are "File has not been read yet" (structural). Audit grades (r1/audit.md): opus-low 4 (9 correct/1 wrong/2 missing), opus-medium 4 (8/0/4), sonnet-medium 3 (8/2/2), sonnet-low 2 (8/3/1). Edit range (ctx first→last Edit): opus-low 216.6k–273.5k, opus-medium 191.0k–308.5k, sonnet-low 47.5k–99.8k, sonnet-medium 73.0k–279.4k.

Historical (38 agents with peak_ctx, metrics-local/*.json): bucket | n | mean rate | % reread/full_read | % maxTurns
<100k: 18, rate 5.0, reread 17%, maxTurns 0%; 100–150k: 9, rate 4.8, reread 33%, maxTurns 0%; 150–220k: 7, rate 4.8, reread 57%, maxTurns 0%; >220k: 4, rate 5.0, reread 100%, maxTurns 0%.

Per type (median peak ctx / median calls): implementer 97,420 / 37 (13 of 66 with ctx); implementer-max 127,114 / 67 (3 of 68); implementer-sonnet 81,504 / 30 (9 of 12); scripter-complex 79,200 / 31.

## 4. What is enforced in main today vs advisory

| rule | status |
|---|---|
| read-mare (Read >300 lines / reread, deny) | enforced |
| brief-mare (reminder >7000 chars) | enforced |
| comentarii-cod (additionalContext) | enforced |
| context-agent skips main | enforced (as configured) |
| cap 4 live agents | advisory |
| ≤20 lines written by main | advisory |
| audit before commit | advisory |
| no cat/sed on big files via Bash | advisory |
| plan ≤10 lines context | advisory |

## 5. Fable 5.1 documented changes

Per platform.claude.com/docs/en/models/fable-5-1/whats-new-fable-5-1 and .../build-with-claude/prompt-engineering/prompting-claude-fable-5-1: "may issue one tool call per turn where Claude Fable 5 batched several"; "writes less user-facing text between tool calls"; "more likely to rewrite the entire file than make a targeted edit"; effort default high, adaptive thinking always on; "follows explicit tool instructions reliably". Subagents: "don't force the lead agent to stop and wait"; "End your turn only when the task is complete or you are blocked on input only the user can provide"; "asking 'Want me to…?' will block the work". Claude Code 2.1.257 made Fable 5.1 the default Fable model; 2.1.251 added PreModelSwitch/PostModelSwitch hooks.

## 6. Decisions

Thresholds per agent type, the new main-session hooks and the rationale (economic cap, not a quality cliff) are recorded in docs/DECIZII.md «v1.6 — hook-uri pentru orchestrator (02.09.2026)».
