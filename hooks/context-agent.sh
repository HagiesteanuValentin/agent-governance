#!/bin/bash
# 🔴 must read the sub-agent's own transcript, not main's — PATTERNS «context-agent reads the sub-agent's own transcript»
MARKER_DIR=/tmp/claude-hooks
input=$(cat)
python3 - "$input" "$MARKER_DIR" "$@" <<'PY'
import json, os, re, sys, time

RAW = sys.argv[1]
MARKER_DIR = sys.argv[2]
ARGV = sys.argv[3:]

WARN_AT, BLOCK_AT = 150000, 220000
SCOPE = "agent"
ANY_TYPE = False
PER_TYPE = False
# 🔴 per-type thresholds only with --praguri-tip, default stays 150k/220k — docs/DECIZII.md «context-agent — scope main and per-type thresholds»
TYPE_LIMITS = {"implementer-sonnet": (100000, 150000),
               "scripter": (100000, 150000)}
AGENT_PREFIXES = ("implementer", "scripter")
PLAN_DIR = "/.claude/plans/"
SAFE_SUBAGENTS = ("scribe", "auditor")


def parse_args(argv):
    global WARN_AT, BLOCK_AT, SCOPE, ANY_TYPE, PER_TYPE
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--warn" and i + 1 < len(argv):
            WARN_AT = int(argv[i + 1]); i += 2
        elif a == "--deny" and i + 1 < len(argv):
            BLOCK_AT = int(argv[i + 1]); i += 2
        elif a == "--scope" and i + 1 < len(argv):
            SCOPE = argv[i + 1]; i += 2
        elif a == "--any-type":
            ANY_TYPE = True; i += 1
        elif a == "--praguri-tip":
            PER_TYPE = True; i += 1
        else:
            i += 1


def marker_once(safe, suffix):
    """True the first time it is called for this key+suffix."""
    path = os.path.join(MARKER_DIR, "%s.%s" % (safe, suffix))
    try:
        os.makedirs(MARKER_DIR, exist_ok=True)
        if os.path.exists(path):
            return False
        open(path, "w").close()
    except OSError:
        return False
    return True


def log(who, kind, ctx, decision):
    try:
        os.makedirs(MARKER_DIR, exist_ok=True)
        with open(os.path.join(MARKER_DIR, "context-agent.jsonl"), "a") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                 "agent_id": who, "agent_type": kind,
                                 "ctx": ctx, "decision": decision}) + "\n")
    except OSError:
        pass


def last_context(path):
    """input + cache_read + cache_creation on the last assistant line; 0 if none."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > 512 * 1024:
                fh.seek(size - 512 * 1024)
            data = fh.read()
    except OSError:
        return 0
    for raw in reversed(data.split(b"\n")):
        if b'"usage"' not in raw or b'"assistant"' not in raw:
            continue
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        u = msg.get("usage")
        if not isinstance(u, dict):
            continue
        return ((u.get("input_tokens") or 0)
                + (u.get("cache_read_input_tokens") or 0)
                + (u.get("cache_creation_input_tokens") or 0))
    return 0


VERIF = re.compile(r"astro check|npm run build|npm test|vitest|pytest"
                   r"|verifica-[\w-]+\.mjs|verify-")


def prior_verifications(path, cur_id):
    prior = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"Bash"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                msg = obj.get("message")
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    if b.get("name") != "Bash" or (cur_id and b.get("id") == cur_id):
                        continue
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    c = inp.get("command")
                    if isinstance(c, str) and VERIF.search(c):
                        prior += 1
    except OSError:
        return None
    return prior


def run():
    parse_args(ARGV)
    d = json.loads(RAW)
    tool = d.get("tool_name")
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    agent_id = d.get("agent_id")
    agent_type = d.get("agent_type") or ""
    tp = d.get("transcript_path") or ""
    session_id = d.get("session_id") or ""

    def emit(who, kind, ctx, decision, **kw):
        log(who, kind, ctx, decision)
        kw["hookEventName"] = "PreToolUse"
        print(json.dumps({"hookSpecificOutput": kw}))
        sys.exit(0)

    if SCOPE == "main":
        if agent_id or not tp or not os.path.exists(tp):
            return
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id) or "main")
        ctx = last_context(tp)
        if ctx >= BLOCK_AT:
            reason = None
            if tool == "Read":
                reason = ("Context >=%dk: stop reading; close the task and run /handoff "
                          "(Bash stays free)." % (BLOCK_AT // 1000))
            elif tool == "Agent":
                st = ti.get("subagent_type") or ""
                if not str(st).startswith(SAFE_SUBAGENTS):
                    reason = ("Context >=%dk: scribe/auditor only; close the task and "
                              "run /handoff." % (BLOCK_AT // 1000))
            elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                fp = str(ti.get("file_path") or ti.get("notebook_path") or "")
                if PLAN_DIR not in fp:
                    reason = ("Context >=%dk: write only into %s; close the task and "
                              "run /handoff." % (BLOCK_AT // 1000, PLAN_DIR))
            if reason:
                emit("main", "main", ctx, "deny", permissionDecision="deny",
                     permissionDecisionReason=reason)
        if ctx >= WARN_AT and marker_once(safe, "main%dk" % (WARN_AT // 1000)):
            emit("main", "main", ctx, "warn",
                 additionalContext=("Context >=%dk: close the task, run /handoff."
                                    % (WARN_AT // 1000)))
        return

    # ---- scope agent
    if not agent_id:
        return
    if not ANY_TYPE and not agent_type.startswith(AGENT_PREFIXES):
        return
    if not tp or not session_id:
        return
    # 🔴 in a sub-agent transcript_path is the MAIN transcript — DECIZII «v1.4.1 — 30.08.2026»
    agent_tp = os.path.join(os.path.dirname(tp), session_id, "subagents",
                            "agent-%s.jsonl" % agent_id)
    if not os.path.exists(agent_tp):
        return
    warn_at, block_at = WARN_AT, BLOCK_AT
    if PER_TYPE and agent_type in TYPE_LIMITS:
        warn_at, block_at = TYPE_LIMITS[agent_type]

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(agent_id))
    ctx = last_context(agent_tp)
    if marker_once(safe, "seen"):
        log(agent_id, agent_type, ctx, "seen")

    # ---- a) context budget
    if ctx >= block_at and tool != "Bash":
        emit(agent_id, agent_type, ctx, "deny", permissionDecision="deny",
             permissionDecisionReason=("Context >=%dk: only Bash for verification is allowed; "
                                       "write the final report now." % (block_at // 1000)))
    if ctx >= warn_at and marker_once(safe, "%dk" % (warn_at // 1000)):
        emit(agent_id, agent_type, ctx, "warn",
             additionalContext=("Context >=%dk: finish the item in progress, run the verification, "
                                "write the final report. Do not start a new item; report the rest "
                                "as not done." % (warn_at // 1000)))

    # ---- b) verification counter
    if tool != "Bash":
        return
    cmd = ti.get("command")
    if not isinstance(cmd, str) or not VERIF.search(cmd):
        return
    prior = prior_verifications(agent_tp, d.get("tool_use_id"))
    if prior is None:
        return
    if prior + 1 >= 3 and marker_once(safe, "verif3"):
        emit(agent_id, agent_type, ctx, "verif3",
             additionalContext=("3rd verification run; the brief allows one at the end and one "
                                "after fixes — continue only if you made a fix since then."))


try:
    run()
except SystemExit:
    raise
except Exception:
    pass
sys.exit(0)
PY
