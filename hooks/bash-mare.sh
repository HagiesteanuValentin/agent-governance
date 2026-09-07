#!/bin/bash
# 🔴 BIG_LINES/BODY_LINES thresholds — RECIPES «Scripts»
BIG_LINES=300
BODY_LINES=20
LOG_DIR=/tmp/claude-hooks
mkdir -p "$LOG_DIR" 2>/dev/null
payload=$(mktemp "$LOG_DIR/bash-mare-XXXXXX" 2>/dev/null || mktemp) || exit 0
cat > "$payload"
python3 - "$payload" "$BIG_LINES" "$BODY_LINES" "$(dirname "$0")" <<'PY'
import atexit, json, os, re, shlex, subprocess, sys, time

try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as _fh:
        d = json.loads(_fh.read())
    if not isinstance(d, dict):
        sys.exit(0)
except Exception:
    sys.exit(0)
finally:
    try:
        os.remove(sys.argv[1])
    except OSError:
        pass

BIG_LINES = int(sys.argv[2])
BODY_LINES = int(sys.argv[3])


BATCH_MAX = 3
BATCH_CHARS = 200
BATCH_IDLE = 90
# 🔴 under 3 s = parallel tool_use calls from the same message — PATTERNS «Bash batching»
BATCH_GAP = 3
_NUDGE = [False]


def _emit_nudge():
    if _NUDGE[0]:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "3 small Bash calls in a row — independent commands "
                                 "go into a single call or the same message; "
                                 "the analyzer flags batchable_bash"}}))


def deny(reason):
    _NUDGE[0] = False
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def sterile_runs(atp, want, cur_id):
    """identical Bash runs in the agent transcript after the last Edit/Write."""
    runs = 0
    if not atp or not os.path.exists(atp):
        return 0
    with open(atp, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"tool_use"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name = b.get("name")
                if name in ("Edit", "Write", "MultiEdit"):
                    runs = 0
                    continue
                if name != "Bash" or (cur_id and b.get("id") == cur_id):
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                c = inp.get("command")
                if isinstance(c, str) and norm(c) == want:
                    runs += 1
    return runs


def batch_nudge(sid, cmd):
    # 🔴 "small" is judged on the command, not on the output — PATTERNS «Bash batching»
    if not sid:
        return
    state = os.path.join("/tmp/claude-hooks", "bash-batch-%s" % re.sub(r"[^\w.-]", "_", sid))
    now = time.time()
    count, last = 0, 0.0
    try:
        with open(state, encoding="utf-8") as fh:
            parts = fh.read().split()
        count, last = int(parts[0]), float(parts[1])
    except (OSError, ValueError, IndexError):
        count, last = 0, 0.0

    def save(n):
        try:
            with open(state, "w", encoding="utf-8") as fh:
                fh.write("%d %f" % (n, now))
        except OSError:
            pass

    small = "<<" not in cmd and len(cmd) < BATCH_CHARS
    if not small:
        save(0)
        return
    if now - last > BATCH_IDLE:
        count = 0
    if last and now - last < BATCH_GAP:
        return
    count += 1
    if count >= BATCH_MAX:
        _NUDGE[0] = True
        count = 0
    save(count)


try:
    tp = d.get("transcript_path") or ""
    agent_id = d.get("agent_id") or ""
    if agent_id or "subagent" in tp:
        sid = d.get("session_id") or ""
        ati = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
        acmd = ati.get("command")
        if not (agent_id and sid and tp) or not isinstance(acmd, str) or not acmd.strip():
            sys.exit(0)
        # 🔴 in a sub-agent, transcript_path is the MAIN transcript — DECIZII «v1.4.1 — 30.08.2026»
        atp = os.path.join(os.path.dirname(tp), sid, "subagents",
                           "agent-%s.jsonl" % agent_id)
        try:
            runs = sterile_runs(atp, norm(acmd), d.get("tool_use_id"))
        except OSError:
            sys.exit(0)
        if runs >= 2:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "3rd identical run with no fix in between; "
                                     "either fix it or report it as unclear/risky"}}))
        sys.exit(0)
    # 🔴 model guard, main only — PATTERNS «The model inside hooks»
    _m = subprocess.run(["bash", os.path.join(sys.argv[4], "main-model.sh"), tp],
                        capture_output=True, text=True).stdout.strip().lower()
    if not ("fable" in _m or "mythos" in _m or _m in ("", "unknown")):
        sys.exit(0)
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    cmd = ti.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        sys.exit(0)
    cwd = d.get("cwd") or os.getcwd()
    atexit.register(_emit_nudge)
    # 🔴 the counter runs before the RANGE early exit — PATTERNS «Bash batching»
    batch_nudge(d.get("session_id") or "", cmd)

    def nlines(path):
        if not isinstance(path, str) or not path:
            return 0
        p = os.path.expanduser(path)
        if not os.path.isabs(p):
            p = os.path.join(cwd, p)
        try:
            if not os.path.isfile(p):
                return 0
            with open(p, "rb") as fh:
                return sum(1 for _ in fh)
        except OSError:
            return 0

    # ---- a) heredoc that writes a project file
    HD = re.search(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?", cmd)
    if HD:
        delim = HD.group(1)
        rest = cmd[HD.end():].split("\n")[1:]
        body = []
        for line in rest:
            if line.strip() == delim:
                break
            body.append(line)
        header = cmd[:HD.start()]
        target = ""
        m = re.search(r">>?\s*([^\s;|&<>]+)", header)
        if m:
            target = m.group(1)
        else:
            m = re.search(r"\btee\b\s+(?:-a\s+)?([^\s;|&<>-][^\s;|&<>]*)", header)
            if m:
                target = m.group(1)
            else:
                m = re.search(r"open\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"'][wa]", "\n".join(body))
                if m:
                    target = m.group(1)
        if target:
            t = os.path.expanduser(target)
            if not os.path.isabs(t):
                t = os.path.join(cwd, t)
            inside = os.path.realpath(t).startswith(os.path.realpath(cwd) + os.sep)
            if inside and len(body) > BODY_LINES:
                deny(">20 lines from main → scribe/implementer; briefs come from the plan "
                     "via sed -n (%d lines here)" % len(body))

    # ---- b) reading a big file whole
    RANGE = re.compile(r"sed\s+-n[^|;&]*?\d+\s*,\s*\$?\d*\s*p"
                       r"|\b(head|tail)\s+(-[nc]\s*)?[+-]?\d+")
    if RANGE.search(cmd):
        sys.exit(0)
    READERS = ("cat", "bat", "less", "more", "head", "tail", "sed", "awk", "perl")

    def has_flag(toks, letters):
        return any(t.startswith("-") and not t.startswith("--")
                   and any(c in t[1:] for c in letters) for t in toks[1:])

    def segments(s):
        """split on ; | && || and redirects, but not inside quotes"""
        out, buf, q = [], [], ""
        for ch in s:
            if q:
                buf.append(ch)
                if ch == q:
                    q = ""
            elif ch in "'\"":
                q = ch
                buf.append(ch)
            elif ch in ";|&\n":
                out.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        out.append("".join(buf))
        return out

    for seg in segments(cmd.split("<<")[0]):
        seg = re.sub(r"[0-9]*[<>]+\s*\S+", " ", seg)  # a redirect target is not a read
        try:
            toks = shlex.split(seg)
        except ValueError:
            continue
        while toks and re.match(r"^\w+=", toks[0]):
            toks.pop(0)
        if not toks:
            continue
        name = os.path.basename(toks[0])
        args = []
        if name in READERS:
            # in-place edit / follow are not reads; the program argument is not a path
            if has_flag(toks, "i"):
                continue
            if name == "sed" and not has_flag(toks, "n"):
                continue
            if name == "tail" and has_flag(toks, "fF"):
                continue
            if name == "perl" and not has_flag(toks, "np"):
                continue
            args = [t for t in toks[1:] if not t.startswith("-")]
            if name in ("sed", "awk", "perl") and args and not has_flag(toks, "fe"):
                prog, args = args[0], args[1:]
                if name == "awk" and re.search(r"\bNR\b|\bFNR\b", prog):
                    continue
            elif name in ("awk", "perl") and has_flag(toks, "e"):
                if name == "awk" and any(re.search(r"\bNR\b", t) for t in toks[1:]):
                    continue
                args = [t for t in args[1:]] if args else []
        elif name in ("python", "python3") and "-c" in toks:
            i = toks.index("-c")
            code = toks[i + 1] if i + 1 < len(toks) else ""
            if "open(" in code:
                args = re.findall(r"open\(\s*[\"']([^\"']+)[\"']", code)
        for a in args:
            n = nlines(a)
            if n > BIG_LINES:
                deny(">300 lines in main → explorer (or a range): %s has %d lines" % (a, n))
except Exception:
    sys.exit(0)
PY
exit 0
