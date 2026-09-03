#!/bin/bash
# PreToolUse on Edit|Write|MultiEdit, main AND every sub-agent: flags comment lines the call
# would ADD. Sub-agent + block/long line = deny; main and the ratio criterion stay
# additionalContext, plus a JSONL line per signal for /handoff. Rule: a new comment is one
# pointer line (constraint - PATTERNS/DECIZII section), the explanation lives in the docs.
BLOCK_LINES=2
RATIO=0.25
MIN_ADDED=5
LONG_LINE=160
LOG_DIR=/tmp/claude-hooks
# stdin goes to a temp file, never to argv: a Write payload over ~128 KB would blow execve
mkdir -p "$LOG_DIR" 2>/dev/null
payload=$(mktemp "$LOG_DIR/payload-XXXXXX" 2>/dev/null || mktemp) || exit 0
cat > "$payload"
python3 - "$payload" "$BLOCK_LINES" "$RATIO" "$MIN_ADDED" "$LONG_LINE" "$LOG_DIR" <<'PY'
import collections, json, os, re, subprocess, sys, time

try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as _fh:
        d = json.loads(_fh.read())
    if not isinstance(d, dict):
        sys.exit(0)
except Exception:
    sys.exit(0)
finally:
    try:
        os.unlink(sys.argv[1])
    except OSError:
        pass

BLOCK_LINES = int(sys.argv[2])
RATIO = float(sys.argv[3])
MIN_ADDED = int(sys.argv[4])
LONG_LINE = int(sys.argv[5])
LOG_DIR = sys.argv[6]

CODE_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".astro", ".css", ".scss",
            ".html", ".py", ".sh", ".fish", ".yml", ".yaml", ".toml"}
HASH_EXT = {".py", ".sh", ".fish", ".yml", ".yaml", ".toml"}
SLASH_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".astro", ".css", ".scss"}
HTML_EXT = {".html", ".astro"}
LICENSE_RE = re.compile(r"SPDX-License-Identifier|Copyright")


def main():
    tool = d.get("tool_name") or ""
    if tool not in ("Edit", "Write", "MultiEdit"):
        return
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    path = ti.get("file_path")
    if not isinstance(path, str) or not path:
        return
    ext = os.path.splitext(path)[1].lower()
    if ext not in CODE_EXT:
        return
    if "/.claude/plans/" in path or "/docs/" in path or path.startswith("docs/"):
        return

    if tool == "Edit":
        new = ti.get("new_string") or ""
        old = ti.get("old_string") or ""
    elif tool == "MultiEdit":
        edits = ti.get("edits") if isinstance(ti.get("edits"), list) else []
        # 🔴 edits joined by a blank line, so two 1-line pointers are not read as a block — docs/PATTERNS.md «comentarii-cod pe MultiEdit»
        new = "\n\n".join(e.get("new_string") or "" for e in edits if isinstance(e, dict))
        old = "\n\n".join(e.get("old_string") or "" for e in edits if isinstance(e, dict))
    else:
        new = ti.get("content") or ""
        old = head_version(path)
    if not isinstance(new, str) or not new.strip():
        return
    if not isinstance(old, str):
        old = ""

    stats = compare(new, old, ext)
    if stats is None:
        return
    signal(path, tool, stats)


def head_version(path):
    """Committed content of a tracked file, so a Write that rewrites it does not count as new."""
    dirname = os.path.dirname(path) or "."
    base = os.path.basename(path)
    try:
        subprocess.run(["git", "-C", dirname, "ls-files", "--error-unmatch", base],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5, check=True)
        p = subprocess.run(["git", "-C", dirname, "show", "HEAD:./" + base],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=5, check=True)
        return p.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def comment_flags(text, ext):
    """One bool per line: is this line a comment line? Multi-line /* */ and <!-- --> tracked."""
    lines = text.split("\n")
    slash = ext in SLASH_EXT
    html = ext in HTML_EXT
    hashy = ext in HASH_EXT
    out = []
    in_block = False
    in_html = False
    for i, raw in enumerate(lines):
        s = raw.strip()
        if in_block:
            out.append(True)
            if "*/" in s:
                in_block = False
            continue
        if in_html:
            out.append(True)
            if "-->" in s:
                in_html = False
            continue
        is_c = False
        if i < 5 and LICENSE_RE.search(s):
            out.append(False)
            continue
        if slash and s.startswith("//"):
            is_c = True
        elif slash and (s.startswith("/*") or s.startswith("{/*")):
            is_c = True
            body = s[3:] if s.startswith("{/*") else s[2:]
            if "*/" not in body:
                in_block = True
        elif html and s.startswith("<!--"):
            is_c = True
            if "-->" not in s[4:]:
                in_html = True
        elif hashy and s.startswith("#") and not s.startswith("#!"):
            is_c = True
        out.append(is_c)
    return lines, out


def compare(new, old, ext):
    new_lines, new_c = comment_flags(new, ext)
    old_lines, old_c = comment_flags(old, ext)

    old_all = collections.Counter(s.strip() for s in old_lines if s.strip())
    old_com = collections.Counter(old_lines[i].strip()
                                  for i, c in enumerate(old_c) if c and old_lines[i].strip())

    # a comment moved inside the same edit is not new: subtract the old multiset
    pool = collections.Counter(old_com)
    added_idx = []
    for i, c in enumerate(new_c):
        s = new_lines[i].strip()
        if not c or not s:
            continue
        if pool[s] > 0:
            pool[s] -= 1
            continue
        added_idx.append(i)
    if not added_idx:
        return None

    pool_all = collections.Counter(old_all)
    lines_added = 0
    for s in (x.strip() for x in new_lines):
        if not s:
            continue
        if pool_all[s] > 0:
            pool_all[s] -= 1
            continue
        lines_added += 1

    added_set = set(added_idx)
    max_block, run, block_start, best_start = 0, 0, None, added_idx[0]
    for i in range(len(new_lines)):
        if i in added_set:
            if run == 0:
                block_start = i
            run += 1
            if run > max_block:
                max_block, best_start = run, block_start
        else:
            run = 0
    comment_added = len(added_idx)
    long_line = 0
    long_idx = None
    for i in added_idx:
        n = len(new_lines[i].rstrip())
        if n > LONG_LINE and n > long_line:
            long_line, long_idx = n, i
    chars = sum(len(new_lines[i].strip()) for i in added_idx)

    ratio_hit = (lines_added >= MIN_ADDED
                 and comment_added / float(lines_added) > RATIO)
    if not (max_block >= BLOCK_LINES or long_line or ratio_hit):
        return None
    idx = best_start if max_block >= BLOCK_LINES else (
        long_idx if long_idx is not None else added_idx[0])
    return {"lines_added": lines_added, "comment_added": comment_added,
            "max_block": max_block, "long_line": long_line, "chars": chars,
            "snippet": new_lines[idx].strip()[:120]}


RULE = ("Rule: one line, a pointer (\U0001f534 constraint - PATTERNS «section»); "
        "the explanation goes to PATTERNS/DECIZII, not in code. Shorten it before the report.")


def signal(path, tool, st):
    base = os.path.basename(path)
    if st["max_block"] >= BLOCK_LINES:
        head = ("Comment block of %d lines in %s: \"%s\"."
                % (st["max_block"], base, st["snippet"]))
    elif st["long_line"]:
        head = ("Comment line of %d chars in %s: \"%s\"."
                % (st["long_line"], base, st["snippet"]))
    else:
        head = ("%d of %d added lines are comments in %s: \"%s\"."
                % (st["comment_added"], st["lines_added"], base, st["snippet"]))
    log(path, tool, st)
    hard = st["max_block"] >= BLOCK_LINES or st["long_line"]
    if is_agent() and hard:
        out = {"hookEventName": "PreToolUse", "permissionDecision": "deny",
               "permissionDecisionReason": head + " " + RULE}
    else:
        out = {"hookEventName": "PreToolUse", "additionalContext": head + " " + RULE}
    print(json.dumps({"hookSpecificOutput": out}))


def is_agent():
    if d.get("agent_id"):
        return True
    tp = d.get("transcript_path")
    return isinstance(tp, str) and "subagent" in tp


def log(path, tool, st):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(d.get("session_id") or "nosession"))
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "cwd": d.get("cwd") or "",
               "agent_type": d.get("agent_type") or "main", "tool": tool, "file": path,
               "lines_added": st["lines_added"], "comment_added": st["comment_added"],
               "max_block": st["max_block"], "long_line": st["long_line"],
               "snippet": st["snippet"]}
        with open(os.path.join(LOG_DIR, "comentarii-%s.jsonl" % sid), "a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


try:
    main()
except Exception:
    pass
sys.exit(0)
PY
rm -f "$payload" 2>/dev/null
exit 0
