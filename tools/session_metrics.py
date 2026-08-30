#!/usr/bin/env python3
"""Offline token-usage analyzer for Claude Code transcripts.

Input: session .jsonl files (~/.claude/projects/<slug>/<uuid>.jsonl) or directories.
Output: --json (machine-readable) and/or --md (summary + aggregate table). Stdlib only.
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys

# only Agent/SendMessage results in main; agents' Read/Bash output is text, not an event
MAX_TURNS_RE = re.compile(
    r"(reached|hit|exceeded|stopped by|stopped at)[^.\n]{0,30}max[ _-]?turns"
    r"|max[ _-]?turns[^.\n]{0,10}(reached|exceeded|limit hit)"
    r"|maximum number of turns", re.I)

# a Bash command that pulls file content into the context; the separator class keeps
# `... && sed -n` and `... | head` in, `sed -i` and `grep` without -n out
READ_CMD_RE = re.compile(r"(?:^|[|;&(\n]\s*)(cat|bat|head|tail|less|sed\s+-n)\b")
GREP_WC_RE = re.compile(r"(?:^|[|;&(\n]\s*)(grep\s+-[A-Za-z]*n|wc)\b")
HEREDOC_RE = re.compile(r"python3?\s+-\s*<<")
GIT_LS_RE = re.compile(r"^(git|ls)\b")
# harness tag on the user message that carries an async agent's result back into main
TASK_NOTIFICATION_RE = re.compile(r"<task-notification>")

BROWSER_TOOL_PREFIX = "mcp__claude-in-chrome__"
BROWSER_THRESHOLD_DEFAULT = 0.5  # share of main tool calls above which the session is not workflow
VERSION_OLDER = "older"

AGENTS_DIR_DEFAULT = "~/.claude/agents"
AS_MODEL_DEFAULT = "claude-fable-5"
ROT_AT_DEFAULT = 0.35            # operator threshold, not an Anthropic figure
WINDOW_DEFAULT = 1_000_000
NO_QUALITY = ("no quality claim — the threshold is the operator's, not Anthropic's")
MAX_TURNS_FM_RE = re.compile(r"^maxTurns:\s*(\d+)\s*$", re.M)

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
SMALL_IMG = ("-mic", "-small")
COST_KEYS = (("input", "input"), ("output", "output"),
             ("cache_read", "cache_read"), ("cache_creation", "cache_write"))

# every threshold that turns a measurement into a flag; mirrors the hooks in hooks/
THRESHOLDS = {
    "big_tool_result_main": 10000,   # chars of a single tool_result in the main context
    "full_read_lines": 300,          # lines returned by a Read without offset/limit
    "long_agent_report": 2000,       # chars of a worker's final message
    "long_brief": 7000,              # chars of Agent.input.prompt
    "max_implementer_runs": 3,       # implementer + implementer-max + implementer-sonnet per session
    "max_explorer_runs": 3,
    "fable_code_lines": 20,          # lines written by Edit/Write in main
    "high_context_end": 150000,      # main context at the last API call
    "cache_churn_pct": 25.0,         # cache_creation / (cache_read + cache_creation), main
    "context_drop_pct": 30.0,        # drop between two consecutive main calls
    "flag_examples": 5,              # per code, per scope: how many are listed one by one
    "main_read_chars": 2000,         # any Bash read in main under this is a targeted lookup
    "narration_avoidable_calls": 2,  # narration calls after a notification or a plain result
    "narration_text_chars": 300,     # under this, an answer is narration, not work
    "batchable_calls": 3,            # consecutive one-Bash API calls that could be one
    "batchable_chars": 2000,         # ...and together return less than this
    "plan_echo_chars": 8000,         # ExitPlanMode result echoed back into main
    "agent_peak_ctx": 200000,        # worker context past the measured degradation band
    "sterile_verify_calls": 6,       # verification runs below which the ratio says nothing
    "sterile_verify_ratio": 0.2,     # share of verifications that led to a fix
}

FLAG_TEXT = {
    "reread": "same file read more than once",
    "big_tool_result_main": "large tool_result landed in the main context",
    "full_read_big_file": "Read without offset/limit on a big file",
    "image_in_main": "full-size image read in the main context",
    "long_agent_report": "worker final report over budget",
    "long_brief": "brief over budget",
    "too_many_runs": "agent run cap exceeded",
    "fable_wrote_code": "main model wrote code instead of delegating",
    "read_tool_results_main": "tool-results/ re-read in the main context",
    "high_context_end": "main context high at the end of the session",
    "cache_churn_main": "cache rewritten too often in main",
    "agent_max_turns": "worker stopped by maxTurns",
    "agent_no_report": "worker ended without a final report",
    "agent_reread_own_write": "worker re-read a file it had just written",
    "main_read_files": "main read files through Bash instead of delegating",
    "narration_turns": "main ended a turn on a note after a result instead of continuing; "
                       "wasted = cache_read / 10 (input-equivalent, the cached context "
                       "re-sent for nothing); launch-structural calls are counted, not taxed",
    "batchable_bash": "consecutive Bash calls that fit in one call",
    "plan_echo": "plan echoed back into main as a tool_result",
    "sterile_verification": "worker re-ran the checker without it catching anything",
    "agent_ctx_high": "worker context past the degradation threshold",
}

# base gravity per code; wasted tokens can only push it up (see severity_of)
SEVERITY_BASE = {
    "fable_wrote_code": "high",
    "read_tool_results_main": "high",
    "image_in_main": "high",
    "agent_max_turns": "high",
    "agent_no_report": "high",
    "too_many_runs": "high",
    "agent_ctx_high": "high",
    "big_tool_result_main": "medium",
    "reread": "medium",
    "main_read_files": "medium",
    "high_context_end": "medium",
    "cache_churn_main": "medium",
    "long_brief": "medium",
    "plan_echo": "medium",
    "sterile_verification": "medium",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# one line per code; {detail} is the session's own evidence, {n} count, {chars} est. wasted
RECOMMENDATION = {
    "reread": "{detail} - read it once; re-check with a line range, not a second full read.",
    "big_tool_result_main": "{detail} - route it through an explorer, or narrow it with "
                            "head/grep before it lands in main.",
    "full_read_big_file": "{detail} - fine for the implementer on its own target; give the "
                          "explorer/auditor line ranges instead.",
    "image_in_main": "{detail} - read the downscaled `-mic` copy, and late in the session.",
    "long_agent_report": "{detail} - soft cap 1.5k, hard cap 2k, fixed format.",
    "long_brief": "{detail} - over 7k the brief belongs in a plan file; the prompt is path "
                  "+ section.",
    "too_many_runs": "{detail} - split the work at plan time, do not re-send the same brief.",
    "fable_wrote_code": "{detail} - delegate it; main writes at most ~20 lines in one file.",
    "read_tool_results_main": "{detail} - ask the explorer for the fact; the result was "
                              "already paid for once.",
    "high_context_end": "{detail} - hand off earlier; a fresh session starts cheap.",
    "cache_churn_main": "{detail} - keep a stable prefix; do not edit early context.",
    "agent_max_turns": "{detail} - the brief was too large; split it instead of re-running.",
    "agent_no_report": "{detail} - brief unclear or the worker died; re-send once with the "
                       "missing piece.",
    "agent_reread_own_write": "{detail} - the write already succeeded; do not read it back.",
    "main_read_files": "{detail} - delegate the reading; an audit is `git diff --stat` "
                       "plus a targeted grep.",
    "narration_turns": "{detail} - after a notification, the one-line note and the next "
                       "tool call go in the same message.",
    "batchable_bash": "{detail} - one Bash call chained with `;` / `&&`.",
    "plan_echo": "{detail} - keep the plan under 8k; briefs go in the plan file, the prompt "
                 "is path + section.",
    "sterile_verification": "{detail} - run the checker once at the end and once after "
                            "fixes, not after every edit.",
    "agent_ctx_high": "{detail} - split the brief at plan time; the hook wraps the agent "
                      "up at 150k.",
}


def severity_of(code, scope, wasted):
    """Escalation moves a code up one step at most; a worker reading its own target does not."""
    sev = SEVERITY_BASE.get(code, "low")
    if code == "full_read_big_file" and scope.split("#")[0] in ("implementer", "implementer-max", "implementer-sonnet"):
        return "low"
    if sev == "high":
        return "high"
    if sev == "medium":
        return "high" if wasted >= 10000 else "medium"
    return "medium" if wasted >= 2000 else "low"


# ---------------------------------------------------------------- agent limits

_TURNS_LIMIT = {}


def turns_limit_for(agent_type, agents_dir):
    """maxTurns from the frontmatter of <agents_dir>/<type>.md; None when unknown."""
    if not agent_type or "/" in agent_type or agent_type.startswith("."):
        return None
    key = (agents_dir, agent_type)
    if key in _TURNS_LIMIT:
        return _TURNS_LIMIT[key]
    limit = None
    path = os.path.join(os.path.expanduser(agents_dir or AGENTS_DIR_DEFAULT),
                        agent_type + ".md")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        head = ""
    if head.startswith("---"):
        end = head.find("\n---", 3)
        m = MAX_TURNS_FM_RE.search(head[:end] if end > 0 else head)
        if m:
            limit = int(m.group(1))
    _TURNS_LIMIT[key] = limit
    return limit


# ---------------------------------------------------------------- pricing

def load_pricing(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    models = raw.get("models", raw)
    return {k: v for k, v in models.items() if isinstance(v, dict)}


def load_versions(path):
    """Workflow versions sorted by start day; a missing/unreadable file means all 'older'."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return []
    items = raw.get("versions") if isinstance(raw, dict) else raw
    out = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and it.get("name") and it.get("from"):
                out.append({"name": str(it["name"]), "from": str(it["from"])})
    out.sort(key=lambda v: v["from"])
    return out


def version_of(started, versions):
    """Last version whose 'from' <= the session's local start; 'older' before the first.
    'from' is a local day (YYYY-MM-DD) or a local minute (YYYY-MM-DDTHH:MM) for a version
    that starts mid-day, so the session that wrote the rules stays in the previous one."""
    day = local_day(started)
    if day == "?":
        return VERSION_OLDER
    minute = local_str(started, "%Y-%m-%dT%H:%M")
    name = VERSION_OLDER
    for v in versions:
        key = minute if "T" in v["from"] else day
        if key >= v["from"]:
            name = v["name"]
        else:
            break
    return name


def version_names(versions):
    return [VERSION_OLDER] + [v["name"] for v in versions]


# ---------------------------------------------------------------- quality rating

SESSION_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-s\d+-(.+)$")


def clean_score(value):
    """1-5 as an int, or None."""
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return score if 1 <= score <= 5 else None


def load_rating(path):
    """pending-rating.json written by /rate; missing or malformed -> None (never fatal)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    score = clean_score(data.get("score"))
    if score is None:
        return None
    return {"score": score, "note": str(data.get("note") or "").strip(),
            "project": str(data.get("project") or "").strip(),
            "ts": str(data.get("ts") or "").strip()}


def session_project(session):
    """The project as it appears in the session name (<day>-sN-<project>), not the slug dir."""
    m = SESSION_NAME_RE.match(session.get("name") or "")
    return m.group(1) if m else ""


def rating_matches(rating, session):
    if not rating["project"] or rating["project"] != session_project(session):
        return False
    started = session.get("started") or ""
    return bool(rating["ts"]) and bool(started) and rating["ts"] > started


def quality_of(rating):
    return {"score": rating["score"], "note": rating["note"], "rated_at": rating["ts"]}


def quality_score(session):
    return clean_score(((session or {}).get("quality") or {}).get("score"))


def rates_for(pricing, model):
    if model in pricing:
        return pricing[model]
    best = None
    for name, rates in pricing.items():
        if name == "default":
            continue
        if model and (model.startswith(name) or name.startswith(model)):
            if best is None or len(name) > len(best[0]):
                best = (name, rates)
    if best:
        return best[1]
    return pricing.get("default", {})


def cost_of(counts, rates):
    total = 0.0
    for ck, rk in COST_KEYS:
        total += counts.get(ck, 0) * float(rates.get(rk, 0.0)) / 1_000_000.0
    return round(total, 4)


# ---------------------------------------------------------------- parsing

def read_lines(path):
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                yield obj


def blocks(msg):
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def text_of(value):
    """Tool_result content (str or list of blocks) as one string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for b in value:
            if isinstance(b, dict):
                t = b.get("text")
                parts.append(t if isinstance(t, str) else json.dumps(b, ensure_ascii=False))
            elif isinstance(b, str):
                parts.append(b)
        return "".join(parts)
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def text_len(value):
    """Character length of a tool_result content (str or list of blocks)."""
    return len(text_of(value))


def zeros():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "messages": 0}


def add_usage(acc, usage):
    acc["input"] += usage.get("input_tokens") or 0
    acc["output"] += usage.get("output_tokens") or 0
    acc["cache_read"] += usage.get("cache_read_input_tokens") or 0
    acc["cache_creation"] += usage.get("cache_creation_input_tokens") or 0
    acc["messages"] += 1


# ---------------------------------------------------------------- time

def iso_dt(ts):
    if not isinstance(ts, str) or len(ts) < 19:
        return None
    try:
        base = datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return base.replace(tzinfo=datetime.timezone.utc)


def span_s(a, b):
    da, db = iso_dt(a), iso_dt(b)
    if da is None or db is None:
        return 0.0
    return max(0.0, (db - da).total_seconds())


def local_str(ts, fmt_="%Y-%m-%d %H:%M"):
    dt = iso_dt(ts)
    if dt is None:
        return "?"
    return dt.astimezone().strftime(fmt_)


def local_day(ts):
    return local_str(ts, "%Y-%m-%d")


def dur(seconds):
    seconds = int(seconds or 0)
    if seconds >= 3600:
        return "%dh %dm" % (seconds // 3600, (seconds % 3600) // 60)
    if seconds >= 60:
        return "%dm %ds" % (seconds // 60, seconds % 60)
    return "%ds" % seconds


def tok(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000.0)
    if n >= 1000:
        return "%.1fk" % (n / 1000.0)
    return str(n)


def short_model(model):
    m = model or "?"
    if m.startswith("claude-"):
        m = m[len("claude-"):]
    if m.endswith("]") and "[" in m:
        m = m[:m.rindex("[")]
    return m


# ---------------------------------------------------------------- session name

_FIRST_TS = {}


def mtime_ts(path):
    try:
        return datetime.datetime.utcfromtimestamp(
            os.path.getmtime(path)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def first_timestamp(path):
    """First valid timestamp of a transcript; mtime as fallback. Cheap: siblings only need this."""
    if path in _FIRST_TS:
        return _FIRST_TS[path]
    ts = None
    for obj in read_lines(path):
        if isinstance(obj.get("timestamp"), str):
            ts = obj["timestamp"]
            break
    _FIRST_TS[path] = ts or mtime_ts(path)
    return _FIRST_TS[path]


def first_meta(path, max_lines=400):
    """(first timestamp, first cwd) from the head of the transcript being analyzed."""
    ts = cwd = None
    seen = 0
    for obj in read_lines(path):
        seen += 1
        if ts is None and isinstance(obj.get("timestamp"), str):
            ts = obj["timestamp"]
        if cwd is None and isinstance(obj.get("cwd"), str) and obj["cwd"]:
            cwd = obj["cwd"]
        if (ts and cwd) or seen >= max_lines:
            break
    if ts is None:
        ts = mtime_ts(path)
    _FIRST_TS[path] = ts
    return ts, cwd


def project_of(cwd, jsonl_path):
    if isinstance(cwd, str) and cwd.strip("/"):
        return os.path.basename(cwd.rstrip("/"))
    slug = os.path.basename(os.path.dirname(jsonl_path))
    home = os.path.expanduser("~").replace("/", "-")
    if slug.startswith(home):
        slug = slug[len(home):]
    return slug.strip("-") or "session"


def session_name(jsonl_path, ts=None, cwd=None):
    """YYYY-MM-DD-sN-<project>; N = rank among sibling sessions started the same local day."""
    if ts is None and cwd is None:
        ts, cwd = first_meta(jsonl_path)
    day = local_day(ts)
    proj = project_of(cwd, jsonl_path)
    base = os.path.basename(jsonl_path)
    rank, sibs = 1, []
    try:
        names = sorted(os.listdir(os.path.dirname(jsonl_path)))
    except OSError:
        names = [base]
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        sib = os.path.join(os.path.dirname(jsonl_path), name)
        sts = ts if name == base else first_timestamp(sib)
        if local_day(sts) == day:
            sibs.append((sts or "", name))
    sibs.sort()
    for i, (_, name) in enumerate(sibs, 1):
        if name == base:
            rank = i
            break
    return "%s-s%d-%s" % (day, rank, proj)


# ---------------------------------------------------------------- sessions

def session_files(jsonl_path):
    """Main transcript plus its subagent transcripts (<uuid>/subagents/*.jsonl)."""
    out = [(jsonl_path, None)]
    stem = jsonl_path[:-len(".jsonl")]
    subdir = os.path.join(stem, "subagents")
    if os.path.isdir(subdir):
        for name in sorted(os.listdir(subdir)):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(subdir, name)
            label = None
            meta_path = path[:-len(".jsonl")] + ".meta.json"
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if isinstance(meta, dict):
                    label = meta.get("agentType") or meta.get("description")
            except (OSError, ValueError):
                pass
            out.append((path, label or name[:-len(".jsonl")]))
    return out


def subagent_meta(path):
    meta_path = path[:-len(".jsonl")] + ".meta.json"
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        if isinstance(meta, dict):
            return meta
    except (OSError, ValueError):
        pass
    return {}


def collect_targets(paths):
    targets = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.endswith(".jsonl") and os.path.isfile(os.path.join(p, name)):
                    targets.append(os.path.join(p, name))
        elif os.path.isfile(p):
            targets.append(p)
        else:
            print("skip (inexistent): %s" % p, file=sys.stderr)
    return targets


def new_doc(path, label):
    return {
        "path": path, "label": label,
        "first_ts": None, "last_ts": None, "last_assistant_ts": None,
        "first_prompt_ts": None, "cwd": None,
        "groups": collections.OrderedDict(),
        "calls": [], "turn_ms": 0, "turns": 0, "slash": [],
        "user_prompts": 0, "sendmessages": 0,
        "results": [], "agent_launches": [], "agent_results": {},
        "reads": collections.Counter(), "read_chars": collections.Counter(),
        "written": set(), "reread_own_write": [],
        "code_writes": [], "max_turns_hit": False, "max_turns_ids": set(),
        "agent_call_ids": set(), "call_stats": {},
        "usage": zeros(), "model_counts": collections.Counter(),
        "final_text": "",
    }


def slash_name(content):
    txt = content if isinstance(content, str) else text_of(content)
    tag = "<command-name>"
    if tag in txt:
        rest = txt.split(tag, 1)[1]
        return rest.split("</command-name>", 1)[0].strip()
    return None


ASYNC_LAUNCH_RE = re.compile(r"Async agent launched|Resuming agent|running in the background|will be notified")


def human_side_kind(obj, msg, agent_call_ids):
    """What the human side sent before an API call: a prompt, a notification, or a result."""
    results = [b for b in blocks(msg) if b.get("type") == "tool_result"]
    if results:
        for b in results:
            # only a launch that returned immediately forces main to end its turn; a
            # synchronous agent (background: false) returns its report like any tool
            if (isinstance(b.get("tool_use_id"), str) and b["tool_use_id"] in agent_call_ids
                    and ASYNC_LAUNCH_RE.search(text_of(b.get("content")) or "")):
                return "agent_result"
        return "tool_result"
    content = msg.get("content")
    txt = content if isinstance(content, str) else text_of(content)
    if TASK_NOTIFICATION_RE.search(txt or ""):
        return "notification"
    return "user"


def parse_file(path, label, tool_names, tool_inputs):
    """One pass over a transcript; usage grouping identical to the original analyze()."""
    doc = new_doc(path, label)
    groups = doc["groups"]
    last_human = "user"
    for obj in read_lines(path):
        ts = obj.get("timestamp")
        if isinstance(ts, str):
            if doc["first_ts"] is None or ts < doc["first_ts"]:
                doc["first_ts"] = ts
            if doc["last_ts"] is None or ts > doc["last_ts"]:
                doc["last_ts"] = ts
        if doc["cwd"] is None and isinstance(obj.get("cwd"), str) and obj["cwd"]:
            doc["cwd"] = obj["cwd"]

        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        kind = obj.get("type")

        if kind == "system":
            sub = obj.get("subtype")
            if sub == "turn_duration":
                doc["turns"] += 1
                doc["turn_ms"] += obj.get("durationMs") or 0
            elif sub == "local_command":
                name = slash_name(obj.get("content"))
                if name:
                    doc["slash"].append(name)

        if kind == "user":
            if not obj.get("isSidechain"):
                last_human = human_side_kind(obj, msg, doc["agent_call_ids"])
            content = msg.get("content")
            if isinstance(content, str) and not obj.get("isMeta"):
                stripped = content.strip()
                if stripped and not stripped.startswith("<"):
                    doc["user_prompts"] += 1
                    if doc["first_prompt_ts"] is None and isinstance(ts, str):
                        doc["first_prompt_ts"] = ts
            tur = obj.get("toolUseResult")
            if isinstance(tur, dict) and tur.get("agentId"):
                for b in blocks(msg):
                    if b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                        doc["agent_results"][b["tool_use_id"]] = tur
                        break

        for b in blocks(msg):
            bt = b.get("type")
            if bt == "tool_use":
                name = b.get("name") or "?"
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if isinstance(b.get("id"), str):
                    tool_names[b["id"]] = name
                    tool_inputs[b["id"]] = inp
                if name == "Read":
                    fp = inp.get("file_path")
                    if isinstance(fp, str) and fp:
                        doc["reads"][fp] += 1
                        if fp in doc["written"]:
                            doc["reread_own_write"].append(fp)
                elif name in ("Write", "Edit"):
                    fp = inp.get("file_path")
                    body = inp.get("content") or inp.get("new_string") or ""
                    if isinstance(fp, str) and fp:
                        doc["written"].add(fp)
                    is_plan = isinstance(fp, str) and "/.claude/plans/" in fp
                    if (isinstance(body, str) and not is_plan
                            and body.count("\n") + 1 > THRESHOLDS["fable_code_lines"]):
                        doc["code_writes"].append({"path": fp or "?",
                                                   "lines": body.count("\n") + 1})
                elif name == "SendMessage":
                    doc["sendmessages"] += 1
                    if isinstance(b.get("id"), str):
                        doc["agent_call_ids"].add(b["id"])
                elif name == "Agent":
                    if isinstance(b.get("id"), str):
                        doc["agent_call_ids"].add(b["id"])
                    doc["agent_launches"].append({
                        "tool_use_id": b.get("id"),
                        "type": inp.get("subagent_type") or "agent",
                        "description": inp.get("description") or "",
                        "brief_chars": len(inp.get("prompt") or ""),
                        "at": ts,
                    })
            elif bt == "tool_result":
                body = text_of(b.get("content"))
                tuid = b.get("tool_use_id")
                if (label is None and isinstance(tuid, str)
                        and tuid in doc["agent_call_ids"]
                        and MAX_TURNS_RE.search(body[:4000])):
                    doc["max_turns_hit"] = True
                    doc["max_turns_ids"].add(tuid)
                doc["results"].append({
                    "tool_use_id": b.get("tool_use_id"),
                    "chars": len(body),
                    "lines": body.count("\n") + 1 if body else 0,
                    "at": ts,
                })

        if kind != "assistant":
            continue
        if isinstance(ts, str):
            if doc["last_assistant_ts"] is None or ts > doc["last_assistant_ts"]:
                doc["last_assistant_ts"] = ts
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        mid = msg.get("id") or obj.get("uuid")
        grp = groups.get(mid)
        if grp is None:
            grp = groups[mid] = {
                "usage": dict(usage),
                "model": msg.get("model") or "?",
                "side": bool(obj.get("isSidechain")) or label is not None,
                "agent": obj.get("agentName") or label or "sidechain",
                "texts": [], "tools": [], "tool_ids": [],
                "at": ts,
                "prev_human": last_human,
            }
        else:
            grp["usage"]["output_tokens"] = max(grp["usage"].get("output_tokens") or 0,
                                                usage.get("output_tokens") or 0)
        for b in blocks(msg):
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                grp["texts"].append(b["text"])
            elif b.get("type") == "tool_use":
                grp["tools"].append(b.get("name") or "?")
                bid = b.get("id")
                # a missing id keeps its slot: tool_names[k] must stay tool_ids[k]
                grp["tool_ids"].append(bid if isinstance(bid, str) else None)

    for grp in groups.values():
        usage = grp["usage"]
        add_usage(doc["usage"], usage)
        doc["model_counts"][grp["model"]] += 1
        ctx = ((usage.get("input_tokens") or 0)
               + (usage.get("cache_read_input_tokens") or 0)
               + (usage.get("cache_creation_input_tokens") or 0))
        doc["calls"].append({
            "at": grp["at"],
            "ts": grp["at"],
            "side": grp["side"],
            "model": grp["model"],
            "ctx": ctx,
            "context": ctx,
            "input": usage.get("input_tokens") or 0,
            "cache_read": usage.get("cache_read_input_tokens") or 0,
            "cache_creation": usage.get("cache_creation_input_tokens") or 0,
            "output": usage.get("output_tokens") or 0,
            "has_tool_use": bool(grp["tools"]),
            "prev_human": grp.get("prev_human") or "user",
            "text_chars": sum(len(t) for t in grp["texts"]),
            "tool_names": list(grp["tools"]),
            "tool_ids": list(grp["tool_ids"]),
        })
        if grp["texts"]:
            doc["final_text"] = grp["texts"][-1]
    return doc


# ---------------------------------------------------------------- derived

# a Bash command that runs the brief's checker rather than exploring the code
VERIFY_TOKENS = ("build", "test", "verifica", "playwright", "screenshot", "lint", "tsc",
                 "astro check", "gzip", "wc -c", "npm run", "pnpm", "node scripts/", ".mjs")
FIX_TOOLS = ("Edit", "Write", "NotebookEdit")


def verification_calls(doc, tool_inputs, window=4):
    """(runs of the checker, runs followed by a fix within `window` tool calls)."""
    seq = []
    for c in doc["calls"]:
        for name, tid in zip(c["tool_names"], c["tool_ids"]):
            inp = tool_inputs.get(tid) if tid else None
            seq.append((name, inp if isinstance(inp, dict) else {}))
    hits = []
    for i, (name, inp) in enumerate(seq):
        if name != "Bash":
            continue
        cmd = (inp.get("command") or "").lower()
        if any(t in cmd for t in VERIFY_TOKENS):
            hits.append(i)
    fixed = sum(1 for i in hits
                if any(seq[j][0] in FIX_TOOLS
                       for j in range(i + 1, min(i + 1 + window, len(seq)))))
    return len(hits), fixed


def resolve_results(doc, tool_names, tool_inputs):
    out = []
    for r in doc["results"]:
        tid = r["tool_use_id"]
        row = dict(r)
        row["tool"] = tool_names.get(tid, "?")
        row["input"] = tool_inputs.get(tid, {})
        out.append(row)
    return out


def tool_output_block(rows):
    by_tool = {}
    total = 0
    for r in rows:
        e = by_tool.setdefault(r["tool"], {"n": 0, "chars": 0})
        e["n"] += 1
        e["chars"] += r["chars"]
        total += r["chars"]
    top = sorted(rows, key=lambda r: -r["chars"])[:10]
    return {
        "results": len(rows),
        "total_chars": total,
        "est_tokens": total // 4,
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: -kv[1]["chars"])),
        "top": [{"tool": r["tool"], "chars": r["chars"]} for r in top],
    }


def reread_block(doc):
    out = []
    for path, n in doc["reads"].most_common():
        if n < 2:
            continue
        chars = doc["read_chars"][path] // n if doc["read_chars"][path] else 0
        out.append({"path": path, "reads": n, "chars": chars,
                    "wasted_chars": chars * (n - 1)})
    return out


def flag(code, scope, detail, evidence=None, wasted=0):
    f = {"code": code, "scope": scope, "detail": detail}
    if evidence:
        f["evidence"] = evidence
    if wasted:
        f["est_wasted_tokens"] = int(wasted)
    f["severity"] = severity_of(code, scope, int(wasted))
    return f


def emit_many(flags, code, scope, items, fmt_one, wasted_of):
    """List the biggest offenders one by one, then a single line for the rest."""
    cap = THRESHOLDS["flag_examples"]
    for it in items[:cap]:
        flags.append(flag(code, scope, fmt_one(it), it, wasted_of(it)))
    rest = items[cap:]
    if rest:
        flags.append(flag(code, scope, "%d more like this" % len(rest),
                          None, sum(wasted_of(i) for i in rest)))


def main_call_flags(scope, doc, rows):
    """Flags that need the API-call timeline of main, plus the counters the postmortem uses."""
    flags = []
    calls = [c for c in doc["calls"] if not c["side"]]
    chars_by_id, input_by_id = {}, {}
    for r in rows:
        tid = r.get("tool_use_id")
        if isinstance(tid, str):
            chars_by_id[tid] = r["chars"]
            input_by_id[tid] = r["input"] or {}

    reads = []
    for r in rows:
        if r["tool"] != "Bash":
            continue
        cmd = (r["input"] or {}).get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        hit = bool(READ_CMD_RE.search(cmd))
        if not hit and HEREDOC_RE.search(cmd) and cmd.count("\n") > 5:
            hit = True
        if not hit and GREP_WC_RE.search(cmd):
            hit = True
        # a targeted lookup that comes back small is allowed, whatever the command
        if hit and r["chars"] <= THRESHOLDS["main_read_chars"]:
            hit = False
        if hit:
            reads.append({"cmd": " ".join(cmd.split())[:60], "chars": r["chars"]})
    reads.sort(key=lambda r: -r["chars"])
    emit_many(flags, "main_read_files", scope, reads,
              lambda r: "`%s` returned %s chars" % (r["cmd"], fmt(r["chars"])),
              lambda r: r["chars"] / 4.0)

    # an answer to the user is not narration; after a launch the turn has to end anyway
    narr = [c for c in calls if not c["has_tool_use"]
            and c["text_chars"] < THRESHOLDS["narration_text_chars"]
            and c["prev_human"] != "user"]
    structural = [c for c in narr if c["prev_human"] == "agent_result"]
    avoidable = [c for c in narr if c["prev_human"] != "agent_result"]
    narr_cache = sum(c["cache_read"] for c in narr)
    avoid_cache = sum(c["cache_read"] for c in avoidable)
    if len(avoidable) > THRESHOLDS["narration_avoidable_calls"]:
        flags.append(flag("narration_turns", scope,
                          "%d avoidable narration calls (%s cache_read re-sent) · "
                          "%d structural after agent launches"
                          % (len(avoidable), tok(avoid_cache), len(structural)),
                          {"calls": len(narr), "avoidable": len(avoidable),
                           "structural": len(structural), "cache_read": avoid_cache},
                          int(avoid_cache / 10.0)))

    runs, i = [], 0
    while i < len(calls):
        if calls[i]["tool_names"] != ["Bash"]:
            i += 1
            continue
        j = i
        while j < len(calls) and calls[j]["tool_names"] == ["Bash"]:
            j += 1
        run = calls[i:j]
        if len(run) >= THRESHOLDS["batchable_calls"]:
            chars = sum(chars_by_id.get(t, 0) for c in run
                        for t in c["tool_ids"] if t)
            if chars < THRESHOLDS["batchable_chars"]:
                avg_ctx = sum(c["ctx"] for c in run) / float(len(run))
                runs.append({"calls": len(run), "chars": chars, "at": run[0]["at"],
                             "wasted": (len(run) - 1) * avg_ctx / 10.0})
        i = j
    emit_many(flags, "batchable_bash", scope, runs,
              lambda r: "%d Bash calls in a row, %s chars back in total"
                        % (r["calls"], fmt(r["chars"])),
              lambda r: r["wasted"])

    echo = sorted([{"chars": r["chars"]} for r in rows
                   if r["tool"] == "ExitPlanMode"
                   and r["chars"] > THRESHOLDS["plan_echo_chars"]],
                  key=lambda r: -r["chars"])
    emit_many(flags, "plan_echo", scope, echo,
              lambda r: "plan echoed back as a tool_result, %s chars" % fmt(r["chars"]),
              lambda r: r["chars"] / 4.0)

    hands_on = tool_calls = 0
    for c in calls:
        for k, name in enumerate(c["tool_names"]):
            tool_calls += 1
            if name in ("Read", "Edit", "Write"):
                hands_on += 1
            elif name == "Bash":
                tid = c["tool_ids"][k] if k < len(c["tool_ids"]) else None
                cmd = " ".join(((input_by_id.get(tid) or {}).get("command") or "").split())
                if not GIT_LS_RE.match(cmd):
                    hands_on += 1
    stats = {
        "main_api_calls": len(calls),
        "main_tool_calls": tool_calls,
        "hands_on_calls": hands_on,
        "hands_on_ratio": round(hands_on / float(tool_calls or 1), 3),
        "narration_calls": len(narr),
        "narration_avoidable": len(avoidable),
        "narration_structural": len(structural),
        "narration_cache_read": narr_cache,
        "narration_avoidable_cache_read": avoid_cache,
        "main_read_calls": len(reads),
        "main_read_chars": sum(r["chars"] for r in reads),
        "main_read_examples": [r["cmd"] for r in reads[:2]],
        "batchable_runs": len(runs),
        "batchable_bash_calls": sum(r["calls"] for r in runs),
        "plan_echo_chars": sum(r["chars"] for r in echo),
        "images_in_main": sum(n for p, n in doc["reads"].items()
                              if p.lower().endswith(IMG_EXT)),
        "code_write_files": len(set(w["path"] for w in doc["code_writes"])),
        "code_write_lines": sum(w["lines"] for w in doc["code_writes"]),
    }
    return flags, stats


def scope_flags(scope, doc, rows, is_main):
    flags = []
    for r in reread_block(doc):
        flags.append(flag("reread", scope,
                          "%s read %d×" % (os.path.basename(r["path"]), r["reads"]),
                          {"path": r["path"], "reads": r["reads"]},
                          r["wasted_chars"] / 4.0))
    # ExitPlanMode is counted once, by plan_echo
    big = sorted([r for r in rows if r["chars"] > THRESHOLDS["big_tool_result_main"]
                  and r["tool"] != "ExitPlanMode"],
                 key=lambda r: -r["chars"])
    if is_main:
        emit_many(flags, "big_tool_result_main", scope, big,
                  lambda r: "%s result %s chars" % (r["tool"], fmt(r["chars"])),
                  lambda r: r["chars"] / 4.0)
    full = []
    for r in rows:
        if r["tool"] != "Read" or r["lines"] <= THRESHOLDS["full_read_lines"]:
            continue
        inp = r["input"] or {}
        if inp.get("offset") or inp.get("limit"):
            continue
        full.append({"path": inp.get("file_path") or "?", "lines": r["lines"],
                     "chars": r["chars"]})
    full.sort(key=lambda r: -r["lines"])
    emit_many(flags, "full_read_big_file", scope, full,
              lambda r: "%s read whole (%d lines)" % (os.path.basename(r["path"]), r["lines"]),
              lambda r: r["chars"] / 4.0)
    if is_main:
        imgs = []
        for path, n in sorted(doc["reads"].items()):
            base = os.path.basename(path).lower()
            if base.endswith(IMG_EXT) and not any(s in base for s in SMALL_IMG):
                imgs.append({"path": path, "reads": n})
        emit_many(flags, "image_in_main", scope, imgs,
                  lambda r: "%s read %d× at full size" % (os.path.basename(r["path"]), r["reads"]),
                  lambda r: 0)
        tr = [{"path": p, "reads": n} for p, n in sorted(doc["reads"].items())
              if "tool-results/" in p]
        emit_many(flags, "read_tool_results_main", scope, tr,
                  lambda r: "%s (already-seen agent output)" % os.path.basename(r["path"]),
                  lambda r: 0)
        emit_many(flags, "fable_wrote_code", scope,
                  sorted(doc["code_writes"], key=lambda w: -w["lines"]),
                  lambda w: "%s written in main (%d lines)" % (os.path.basename(w["path"]), w["lines"]),
                  lambda w: 0)
        call_flags, doc["call_stats"] = main_call_flags(scope, doc, rows)
        flags.extend(call_flags)
    else:
        seen = []
        for path in doc["reread_own_write"]:
            if path not in seen:
                seen.append(path)
        emit_many(flags, "agent_reread_own_write", scope,
                  [{"path": p} for p in seen],
                  lambda r: "%s re-read after writing it" % os.path.basename(r["path"]),
                  lambda r: 0)
    return flags


def recommendations(flags):
    """One line per code present, worst first; the session's own evidence inside the text."""
    by_code = collections.OrderedDict()
    for f in flags:
        e = by_code.setdefault(f["code"], {"code": f["code"], "n": 0, "wasted": 0,
                                           "severity": "low", "detail": "", "rank": None})
        e["n"] += 1
        e["wasted"] += f.get("est_wasted_tokens", 0)
        # the line speaks for the worst occurrence, so severity and evidence stay in step
        rank = (SEVERITY_ORDER[f.get("severity", "low")],
                0 if f.get("evidence") else 1, -f.get("est_wasted_tokens", 0))
        if e["rank"] is None or rank < e["rank"]:
            e["rank"] = rank
            e["severity"] = f.get("severity", "low")
            e["detail"] = f["detail"] if f["scope"] == "main" \
                else "%s: %s" % (f["scope"], f["detail"])
    out = []
    for e in by_code.values():
        e.pop("rank", None)
        tpl = RECOMMENDATION.get(e["code"], "{detail}")
        e["text"] = (tpl.replace("{detail}", e["detail"])
                     .replace("{n}", str(e["n"]))
                     .replace("{chars}", tok(e["wasted"])))
        out.append(e)
    out.sort(key=lambda e: (SEVERITY_ORDER[e["severity"]], -e["wasted"]))
    return out


def postmortem_block(main_doc, workers, flags, main_counts, by_type):
    pm = dict(main_doc["call_stats"])
    wasted = sum(f.get("est_wasted_tokens", 0) for f in flags)
    # cache_read is a tenth of the input price, so the volume is weighted the same way
    main_input = (main_counts["input"] + main_counts["cache_creation"]
                  + main_counts["cache_read"] / 10.0)
    sev = collections.Counter(f.get("severity", "low") for f in flags)
    mix = collections.OrderedDict(sorted(by_type.items()))
    if main_doc["sendmessages"]:
        mix["SendMessage"] = main_doc["sendmessages"]
    pm["delegations"] = len(main_doc["agent_launches"]) + main_doc["sendmessages"]
    pm["delegation_mix"] = dict(mix)
    pm["delegation_mix_text"] = ", ".join("%s %d" % kv for kv in mix.items())
    pm["agent_report_chars_in_main"] = sum(w["final_report_chars"] for w in workers)
    pm["wasted_total"] = wasted
    pm["wasted_pct_of_main_input"] = round(100.0 * wasted / (main_input or 1), 1)
    pm["severity_counts"] = {k: sev.get(k, 0) for k in ("high", "medium", "low")}
    pm["recommendations"] = recommendations(flags)
    return pm


def counterfactual_block(main_doc, worker_docs, pricing, as_model, rot_at, window,
                         actual_usd):
    """Cost of the same calls replayed in one context on one model. Not a quality claim."""
    rates = rates_for(pricing, as_model)
    r_in = float(rates.get("input", 0.0))
    r_out = float(rates.get("output", 0.0))
    r_cr = float(rates.get("cache_read", 0.0))
    r_cw = float(rates.get("cache_write", 0.0))
    main_calls = sorted([c for c in main_doc["calls"] if not c["side"] and c["at"]],
                        key=lambda c: c["at"])
    runs = []
    for scope, doc in worker_docs:
        calls = sorted([c for c in doc["calls"] if c["at"]], key=lambda c: c["at"])
        if not calls:
            continue
        # system prompt + CLAUDE.md + agent definition: paid once per run, never in one context
        boot = calls[0]["input"] + calls[0]["cache_creation"]
        runs.append({"scope": scope, "calls": calls, "boot": boot,
                     "launch": calls[0]["at"], "net": max(calls[-1]["ctx"] - boot, 0)})
    runs.sort(key=lambda r: r["launch"])
    for r in runs:
        before = [c for c in main_calls if c["at"] < r["launch"]]
        r["main_at_launch"] = before[-1]["ctx"] if before else 0
        r["stacked"] = sum(o["net"] for o in runs if o["launch"] < r["launch"])

    floor = 0.0
    for c in main_calls:
        floor += (c["output"] * r_out + c["input"] * r_in
                  + c["cache_read"] * r_cr + c["cache_creation"] * r_cw) / 1e6
    boot_removed = 0
    for r in runs:
        boot_removed += r["boot"]
        for i, c in enumerate(r["calls"]):
            inp = 0 if i == 0 else c["input"]
            ccr = 0 if i == 0 else c["cache_creation"]
            crd = c["cache_read"] if i == 0 else max(c["cache_read"] - r["boot"], 0)
            floor += (c["output"] * r_out + inp * r_in + crd * r_cr + ccr * r_cw) / 1e6

    timeline = []
    for c in main_calls:
        timeline.append((c["at"], c, None, 0))
    for r in runs:
        for i, c in enumerate(r["calls"]):
            timeline.append((c["at"], c, r, i))
    timeline.sort(key=lambda e: e[0])
    threshold = int(rot_at * window)
    realistic = 0.0
    peak_cf = out_above = out_total = 0
    crossed_at = None
    t0 = timeline[0][0] if timeline else None
    for ts, c, run, i in timeline:
        if run is None:
            ctx_cf = c["ctx"] + sum(r["net"] for r in runs if r["launch"] < ts)
            cc_net = c["cache_creation"]
        else:
            ctx_cf = c["ctx"] - run["boot"] + run["main_at_launch"] + run["stacked"]
            cc_net = (max(c["cache_creation"] - run["boot"], 0) if i == 0
                      else c["cache_creation"])
        ctx_cf = max(int(ctx_cf), 0)
        realistic += (c["output"] * r_out + max(ctx_cf - cc_net, 0) * r_cr
                      + cc_net * r_cw) / 1e6
        peak_cf = max(peak_cf, ctx_cf)
        out_total += c["output"]
        if ctx_cf >= threshold:
            out_above += c["output"]
            if crossed_at is None:
                crossed_at = ts
    overflow = max(peak_cf - window, 0)
    boot_avg = boot_removed // (len(runs) or 1)
    return {
        "model": as_model,
        "actual_usd": round(actual_usd, 4),
        "floor_usd": round(floor, 4),
        "realistic_usd": round(realistic, 4),
        "ratio_floor": round(floor / (actual_usd or 1), 2),
        "ratio_realistic": round(realistic / (actual_usd or 1), 2),
        "bootstrap_tokens_removed": boot_removed,
        "worker_runs": len(runs),
        "peak_context_cf": peak_cf,
        "main_peak_actual": max([c["ctx"] for c in main_calls] or [0]),
        "threshold_tokens": threshold,
        "rot_at": rot_at,
        "window": window,
        "crossed_at_s": round(span_s(t0, crossed_at), 1) if crossed_at else None,
        "output_above_threshold_pct": round(100.0 * out_above / (out_total or 1), 1),
        "overflow_tokens": overflow,
        "forced_compactions": -(-overflow // window) if overflow else 0,
        "assumptions": [
            "same calls and outputs",
            "worker bootstrap removed (~%s \u00d7 %d runs)" % (tok(boot_avg), len(runs)),
            "worker content persists in the single context",
            "all context cached (1h TTL)",
        ],
    }


def concurrency(workers):
    events = []
    for w in workers:
        a, b = iso_dt(w["started"]), iso_dt(w["ended"])
        if a is None or b is None:
            continue
        events.append((a, 1))
        events.append((b, -1))
    events.sort(key=lambda e: (e[0], e[1]))
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    overlaps = []
    for i in range(len(workers)):
        for j in range(i + 1, len(workers)):
            a1, a2 = iso_dt(workers[i]["started"]), iso_dt(workers[i]["ended"])
            b1, b2 = iso_dt(workers[j]["started"]), iso_dt(workers[j]["ended"])
            if None in (a1, a2, b1, b2):
                continue
            lo, hi = max(a1, b1), min(a2, b2)
            if hi > lo:
                overlaps.append({"a": workers[i]["scope"], "b": workers[j]["scope"],
                                 "overlap_s": round((hi - lo).total_seconds(), 1)})
    overlaps.sort(key=lambda o: -o["overlap_s"])
    return max(peak, 0), overlaps


def analyze(jsonl_path, pricing, ctx_warn=None, agents_dir=None,
            as_model=None, rot_at=ROT_AT_DEFAULT, window=WINDOW_DEFAULT,
            versions=None, browser_threshold=BROWSER_THRESHOLD_DEFAULT):
    if versions is None:
        versions = []
    if ctx_warn is None:
        ctx_warn = THRESHOLDS["high_context_end"]
    if agents_dir is None:
        agents_dir = AGENTS_DIR_DEFAULT
    if as_model is None:
        as_model = AS_MODEL_DEFAULT
    tool_names, tool_inputs = {}, {}
    files = session_files(jsonl_path)
    docs = [(path, label, parse_file(path, label, tool_names, tool_inputs))
            for path, label in files]
    main_doc = docs[0][2]
    sub_docs = docs[1:]

    per_model = collections.defaultdict(zeros)
    main, side = zeros(), zeros()
    agents = {}
    agent_usage = collections.defaultdict(zeros)
    agent_models = collections.defaultdict(collections.Counter)
    agent_runs = collections.Counter()
    tool_results = []
    reads = collections.Counter()
    first_ts = last_ts = None

    for path, label, doc in docs:
        if doc["first_ts"] and (first_ts is None or doc["first_ts"] < first_ts):
            first_ts = doc["first_ts"]
        if doc["last_ts"] and (last_ts is None or doc["last_ts"] > last_ts):
            last_ts = doc["last_ts"]
        reads.update(doc["reads"])
        for r in doc["results"]:
            tool_results.append((r["chars"], r["tool_use_id"]))
        if label is not None:
            agent_runs[label] += 1
        for grp in doc["groups"].values():
            usage = grp["usage"]
            add_usage(per_model[grp["model"]], usage)
            add_usage(side if grp["side"] else main, usage)
            if not grp["side"]:
                continue
            entry = agents.setdefault(
                grp["agent"],
                {"assistant_messages": 0, "output_tokens": 0, "final_text_chars": 0})
            entry["assistant_messages"] += 1
            entry["output_tokens"] += usage.get("output_tokens") or 0
            if grp["texts"]:
                entry["final_text_chars"] = len(grp["texts"][-1])
            add_usage(agent_usage[grp["agent"]], usage)
            agent_models[grp["agent"]][grp["model"]] += 1

    # Read result sizes: match each Read tool_use to its result, per transcript
    for path, label, doc in docs:
        for r in doc["results"]:
            tid = r["tool_use_id"]
            if tool_names.get(tid) != "Read":
                continue
            fp = (tool_inputs.get(tid) or {}).get("file_path")
            if isinstance(fp, str) and fp:
                doc["read_chars"][fp] += r["chars"]

    totals = zeros()
    models_out = {}
    for model, counts in sorted(per_model.items()):
        rates = rates_for(pricing, model)
        row = dict(counts)
        row["cost_usd"] = cost_of(counts, rates)
        models_out[model] = row
        for k in ("input", "output", "cache_read", "cache_creation", "messages"):
            totals[k] += counts[k]
    totals["cost_usd"] = round(sum(m["cost_usd"] for m in models_out.values()), 4)

    tool_results.sort(key=lambda x: -x[0])
    top_tools = [{"tool": tool_names.get(tid, "?"), "chars": n, "tool_use_id": tid}
                 for n, tid in tool_results[:10]]

    rereads = [{"path": p, "reads": n} for p, n in reads.most_common() if n >= 2]
    images = []
    for p, n in sorted(reads.items()):
        if p.lower().endswith(IMG_EXT):
            images.append({"path": p, "reads": n,
                           "is_mic": "-mic" in os.path.basename(p).lower()})

    for name, entry in agents.items():
        counts = agent_usage[name]
        model = agent_models[name].most_common(1)[0][0] if agent_models[name] else "?"
        entry["model"] = model
        entry["cost_usd"] = cost_of(counts, rates_for(pricing, model))
        entry["runs"] = agent_runs.get(name, 1)
        entry["turns_limit"] = turns_limit_for(name, agents_dir)

    # ------------------------------------------------ workers (main -> subagent files)
    by_agent_id, by_tool_use = {}, {}
    for path, label, doc in sub_docs:
        base = os.path.basename(path)[:-len(".jsonl")]
        aid = base[len("agent-"):] if base.startswith("agent-") else base
        meta = subagent_meta(path)
        by_agent_id[aid] = (path, label, doc, meta)
        if meta.get("toolUseId"):
            by_tool_use[meta["toolUseId"]] = aid
    used = set()
    workers = []
    seq = collections.Counter()

    def add_worker(wtype, description, brief_chars, launch_model, entry, launch_id=None):
        seq[wtype] += 1
        scope = "%s#%d" % (wtype, seq[wtype])
        path = label = doc = None
        aid = None
        if entry:
            path, label, doc, meta = entry
            aid = os.path.basename(path)[:-len(".jsonl")]
            if aid.startswith("agent-"):
                aid = aid[len("agent-"):]
        model = launch_model
        rows = []
        if doc is not None:
            if not model:
                mc = doc["model_counts"].most_common(1)
                model = mc[0][0] if mc else "?"
            rows = resolve_results(doc, tool_names, tool_inputs)
        limit = turns_limit_for(wtype, agents_dir)
        wctx = [c["ctx"] for c in doc["calls"]] if doc else []
        vcalls, vfixed = verification_calls(doc, tool_inputs) if doc else (0, 0)
        api_calls = len(doc["calls"]) if doc else 0
        report_chars = len(doc["final_text"]) if doc else 0
        # a run killed by maxTurns never gets to write its report; saturation alone is not it
        saturated = bool(limit and api_calls >= limit and report_chars == 0)
        w = {
            "n": len(workers) + 1, "scope": scope, "type": wtype,
            "description": description, "agent_id": aid, "model": model or "?",
            "started": doc["first_ts"] if doc else None,
            "ended": doc["last_ts"] if doc else None,
            "duration_s": round(span_s(doc["first_ts"], doc["last_ts"]), 1) if doc else 0.0,
            "api_calls": api_calls,
            "turns_limit": limit,
            "output_tokens": doc["usage"]["output"] if doc else 0,
            "cost_usd": cost_of(doc["usage"], rates_for(pricing, model)) if doc else 0.0,
            "brief_chars": brief_chars,
            "final_report_chars": report_chars,
            "tool_calls": len(rows),
            "reads": sum(doc["reads"].values()) if doc else 0,
            "verify_calls": vcalls,
            "verify_with_fix": vfixed,
            "peak_ctx": max(wctx) if wctx else 0,
            "ctx_at_end": wctx[-1] if wctx else 0,
            "max_turns_hit": bool(launch_id and launch_id in main_doc["max_turns_ids"])
                              or saturated,
            "transcript": path,
        }
        workers.append(w)
        return w, doc, rows

    worker_scopes = []
    for launch in main_doc["agent_launches"]:
        res = main_doc["agent_results"].get(launch["tool_use_id"]) or {}
        aid = res.get("agentId") or by_tool_use.get(launch["tool_use_id"])
        entry = by_agent_id.get(aid) if aid else None
        if entry:
            used.add(aid)
        w, doc, rows = add_worker(launch["type"], launch["description"],
                                  launch["brief_chars"], res.get("resolvedModel"), entry,
                                  launch["tool_use_id"])
        if doc is not None:
            worker_scopes.append((w["scope"], doc, rows))
    for aid, entry in sorted(by_agent_id.items()):
        if aid in used:
            continue
        path, label, doc, meta = entry
        w, doc2, rows = add_worker(meta.get("agentType") or label or "agent",
                                   meta.get("description") or "", 0, None, entry)
        worker_scopes.append((w["scope"], doc2, rows))

    # ------------------------------------------------ timing / iterations / context
    main_rows = resolve_results(main_doc, tool_names, tool_inputs)
    # sidechain groups can live in the main transcript; context is about the main thread only
    main_calls = [c for c in main_doc["calls"] if not c["side"]]
    start = main_doc["first_prompt_ts"] or main_doc["first_ts"]
    # a session can open with a slash command or a pasted block; those are not "prompts"
    # but the model was already working -> wall would come out shorter than active
    if main_calls and main_calls[0]["at"] and (
            not start or main_calls[0]["at"] < start):
        start = main_calls[0]["at"]
    end = main_doc["last_assistant_ts"] or main_doc["last_ts"]
    wall_s = round(span_s(start, end), 1)
    active_s = round(main_doc["turn_ms"] / 1000.0, 1)
    timing = {
        "wall_s": wall_s, "active_s": active_s,
        "idle_s": round(max(0.0, wall_s - active_s), 1),
        "first_prompt": start, "last_assistant": end,
    }
    by_type = collections.Counter(w["type"] for w in workers)
    iterations = {
        "user_prompts": main_doc["user_prompts"],
        "turns": main_doc["turns"],
        "slash_commands": len(main_doc["slash"]),
        "slash_names": main_doc["slash"],
        "agent_runs_by_type": dict(sorted(by_type.items())),
        "implementer_runs": by_type.get("implementer", 0) + by_type.get("implementer-max", 0) + by_type.get("implementer-sonnet", 0),
        "sendmessage_continuations": main_doc["sendmessages"],
    }
    calls = main_calls
    ctxs = [c["ctx"] for c in calls]
    main_model = main_doc["model_counts"].most_common(1)[0][0] if main_doc["model_counts"] else "?"
    drops = []
    for i in range(1, len(calls)):
        a, b = calls[i - 1]["ctx"], calls[i]["ctx"]
        if a > 0 and b < a * (1.0 - THRESHOLDS["context_drop_pct"] / 100.0):
            drops.append({"at": calls[i]["at"], "from": a, "to": b})
    cache_denom = main["cache_read"] + main["cache_creation"]
    context = {
        "main_model": main_model,
        "main_end_tokens": ctxs[-1] if ctxs else 0,
        "main_peak_tokens": max(ctxs) if ctxs else 0,
        "main_api_calls": len(calls),
        "main_output_tokens": main["output"],
        "main_output_pct": round(100.0 * main["output"] / (totals["output"] or 1), 1),
        "cache_write_pct": round(100.0 * main["cache_creation"] / (cache_denom or 1), 1),
        "drops": drops,
        "drops_note": "deduced from context shrinking between two calls; no compaction marker exists",
    }
    main_tool_calls = browser_calls = 0
    for c in main_calls:
        for name in c["tool_names"]:
            main_tool_calls += 1
            if isinstance(name, str) and name.startswith(BROWSER_TOOL_PREFIX):
                browser_calls += 1
    browser_share = round(browser_calls / float(main_tool_calls), 4) if main_tool_calls else 0.0

    max_concurrent, overlaps = concurrency([w for w in workers if w["started"] and w["ended"]])
    parallel = {
        "max_concurrent": max_concurrent,
        "overlaps": overlaps[:10],
        "total_agent_time_s": round(sum(w["duration_s"] for w in workers), 1),
        "wall_s": wall_s,
    }
    agent_rows = []
    for _, doc, rows in worker_scopes:
        agent_rows.extend(rows)
    tool_output = {"main": tool_output_block(main_rows),
                   "agents": tool_output_block(agent_rows)}
    rereads_detail = {"main": reread_block(main_doc),
                      "agents": {}}
    for scope, doc, _rows in worker_scopes:
        rr = reread_block(doc)
        if rr:
            rereads_detail["agents"][scope] = rr

    # ------------------------------------------------ flags
    flags = scope_flags("main", main_doc, main_rows, True)
    for scope, doc, rows in worker_scopes:
        flags.extend(scope_flags(scope, doc, rows, False))
    for w in workers:
        if w["final_report_chars"] > THRESHOLDS["long_agent_report"]:
            flags.append(flag("long_agent_report", w["scope"],
                              "final report %s chars" % fmt(w["final_report_chars"]),
                              {"chars": w["final_report_chars"]},
                              (w["final_report_chars"] - THRESHOLDS["long_agent_report"]) / 4.0))
        if w["brief_chars"] > THRESHOLDS["long_brief"]:
            flags.append(flag("long_brief", w["scope"],
                              "brief %s chars" % fmt(w["brief_chars"]),
                              {"chars": w["brief_chars"]},
                              (w["brief_chars"] - THRESHOLDS["long_brief"]) / 4.0))
        if w["max_turns_hit"]:
            flags.append(flag("agent_max_turns", w["scope"],
                              "stopped by maxTurns - brief too large", None, 0))
        if w["peak_ctx"] >= THRESHOLDS["agent_peak_ctx"]:
            flags.append(flag("agent_ctx_high", w["scope"],
                              "peak context %s (end %s)" % (tok(w["peak_ctx"]),
                                                            tok(w["ctx_at_end"])),
                              {"peak_ctx": w["peak_ctx"], "ctx_at_end": w["ctx_at_end"]}, 0))
        if (w["type"].startswith("implementer")
                and w["verify_calls"] >= THRESHOLDS["sterile_verify_calls"]
                and w["verify_with_fix"] / float(w["verify_calls"])
                < THRESHOLDS["sterile_verify_ratio"]):
            flags.append(flag("sterile_verification", w["scope"],
                              "%d verification runs, %d led to a fix"
                              % (w["verify_calls"], w["verify_with_fix"]),
                              {"verify_calls": w["verify_calls"],
                               "verify_with_fix": w["verify_with_fix"]}, 0))
        if w["transcript"] and w["final_report_chars"] == 0 and not w["max_turns_hit"]:
            flags.append(flag("agent_no_report", w["scope"],
                              "ended without a final report", None, 0))
    if iterations["implementer_runs"] > THRESHOLDS["max_implementer_runs"]:
        flags.append(flag("too_many_runs", "main",
                          "implementer ran %d× (cap %d)"
                          % (iterations["implementer_runs"], THRESHOLDS["max_implementer_runs"]),
                          {"runs": iterations["implementer_runs"]}, 0))
    if by_type.get("explorer", 0) > THRESHOLDS["max_explorer_runs"]:
        flags.append(flag("too_many_runs", "main",
                          "explorer ran %d× (cap %d)"
                          % (by_type["explorer"], THRESHOLDS["max_explorer_runs"]),
                          {"runs": by_type["explorer"]}, 0))
    if context["main_end_tokens"] > ctx_warn:
        flags.append(flag("high_context_end", "main",
                          "context at end %s (warn %s)"
                          % (tok(context["main_end_tokens"]), tok(ctx_warn)),
                          {"tokens": context["main_end_tokens"]}, 0))
    if context["cache_write_pct"] > THRESHOLDS["cache_churn_pct"] and cache_denom:
        flags.append(flag("cache_churn_main", "main",
                          "cache rewritten on %.1f%% of the context reads"
                          % context["cache_write_pct"],
                          {"pct": context["cache_write_pct"]}, 0))

    postmortem = postmortem_block(main_doc, workers, flags, main, by_type)
    cf = counterfactual_block(main_doc, [(sc, d) for sc, d, _r in worker_scopes],
                              pricing, as_model, rot_at, window, totals["cost_usd"])

    ts0, cwd0 = main_doc["first_ts"], main_doc["cwd"]
    if ts0 is None and cwd0 is None:
        ts0, cwd0 = first_meta(jsonl_path)
    out_total = totals["output"] or 1
    return {
        "session": os.path.basename(jsonl_path)[:-len(".jsonl")],
        "name": session_name(jsonl_path, ts0, cwd0),
        "project": os.path.basename(os.path.dirname(jsonl_path)),
        "path": jsonl_path,
        "started": first_ts,
        "ended": last_ts,
        "version": version_of(first_ts, versions),
        "main_tool_calls": main_tool_calls,
        "browser_calls": browser_calls,
        "browser_share": browser_share,
        "browser_session": browser_share >= browser_threshold and browser_calls > 0,
        "totals": totals,
        "models": models_out,
        "main": main,
        "sidechains": side,
        "sidechain_output_pct": round(100.0 * side["output"] / out_total, 1),
        "agents": dict(sorted(agents.items(), key=lambda kv: -kv[1]["output_tokens"])),
        "top_tool_results": top_tools,
        "reread_files": rereads,
        "images": images,
        "timing": timing,
        "iterations": iterations,
        "context": context,
        "workers": workers,
        "parallel": parallel,
        "tool_output": tool_output,
        "rereads": rereads_detail,
        "flags": flags,
        "postmortem": postmortem,
        "counterfactual": cf,
    }


# ---------------------------------------------------------------- markdown

def fmt(n):
    return "{:,}".format(n).replace(",", ".")


def flags_by_scope(session, scope):
    return [f for f in session["flags"] if f["scope"] == scope]


def postmortem_lines(s):
    pm = s.get("postmortem") or {}
    if not pm:
        return []
    sev = pm["severity_counts"]
    if not s["flags"]:
        return ["## Postmortem — clean session: 0 issues", ""]
    out = ["## Postmortem — %d issues (%d high · %d medium · %d low) · ~%s tokens est. "
           "wasted (%.1f%% of main input volume)"
           % (len(s["flags"]), sev["high"], sev["medium"], sev["low"],
              tok(pm["wasted_total"]), pm["wasted_pct_of_main_input"])]
    parts = []
    if pm.get("code_write_lines"):
        parts.append("Edit/Write %d files, %d lines (over the %d-line rule)"
                     % (pm["code_write_files"], pm["code_write_lines"],
                        THRESHOLDS["fable_code_lines"]))
    if pm.get("main_read_calls"):
        ex = ", ".join("`%s`" % c for c in pm.get("main_read_examples") or [])
        parts.append("Bash reads %d calls, %s chars%s"
                     % (pm["main_read_calls"], tok(pm["main_read_chars"]),
                        " (%s)" % ex if ex else ""))
    parts.append("hands-on ratio %d/%d calls (%d%%) vs %d delegations"
                 % (pm["hands_on_calls"], pm["main_tool_calls"],
                    round(100 * pm["hands_on_ratio"]), pm["delegations"]))
    out.append("Delegable work in main: " + " · ".join(parts))
    ctx = s["context"]
    if "narration_avoidable" in pm:
        narr = ("narration-only calls %d (%d avoidable · %d structural, ~%s cache_read "
                "≈ %s input-equiv.)"
                % (pm.get("narration_calls", 0), pm["narration_avoidable"],
                   pm.get("narration_structural", 0),
                   tok(pm.get("narration_avoidable_cache_read", 0)),
                   tok(pm.get("narration_avoidable_cache_read", 0) // 10)))
    else:  # record analyzed before the avoidable/structural split: keep its old figures
        narr = ("narration-only calls %d (~%s cache_read ≈ %s input-equiv.; old format)"
                % (pm.get("narration_calls", 0), tok(pm.get("narration_cache_read", 0)),
                   tok(pm.get("narration_cache_read", 0) // 10)))
    out.append("Context: main end %s (peak %s) · biggest inputs: plan echo %s chars · "
               "Bash %s · agent reports %s · images %d · %s"
               % (tok(ctx["main_end_tokens"]), tok(ctx["main_peak_tokens"]),
                  tok(pm.get("plan_echo_chars", 0)), tok(pm.get("main_read_chars", 0)),
                  tok(pm.get("agent_report_chars_in_main", 0)),
                  pm.get("images_in_main", 0), narr))
    out.append("Turns: %d API calls in main · %d narration-only · %d batchable Bash runs "
               "(%d calls) · %d delegations (%s)"
               % (pm.get("main_api_calls", 0), pm.get("narration_calls", 0),
                  pm.get("batchable_runs", 0), pm.get("batchable_bash_calls", 0),
                  pm["delegations"], pm.get("delegation_mix_text") or "none"))
    recs = pm.get("recommendations") or []
    if recs:
        out.append("Recommendations:")
        for e in recs[:10]:
            out.append("- [%s] %s: %s" % (e["severity"], e["code"], e["text"]))
        if recs[10:]:
            out.append("- + %d more (%s)" % (len(recs[10:]), recs[10]["severity"]))
    out.append("")
    return out


def counterfactual_lines(s):
    cf = s.get("counterfactual") or {}
    if not cf:
        return []
    mix = " \u00b7 ".join("%s %.2f" % (short_model(m), r["cost_usd"])
                          for m, r in sorted(s["models"].items(),
                                             key=lambda kv: -kv[1]["cost_usd"]))
    win = cf["window"] or 1
    crossed = ("+%s" % dur(cf["crossed_at_s"])) if cf["crossed_at_s"] is not None else "never"
    out = ["## Fable-only estimate (same work, one context, %s rates)" % cf["model"]]
    out.append("actual $%.2f (%s) \u2192 Fable-only floor $%.2f \u00b7 realistic $%.2f "
               "\u2192 \u00d7%.1f\u2013\u00d7%.1f"
               % (cf["actual_usd"], mix, cf["floor_usd"], cf["realistic_usd"],
                  cf["ratio_floor"], cf["ratio_realistic"]))
    out.append("context exposure (operator threshold %d%% of %s = %s): actual main peak %s "
               "(%.0f%%) \u00b7 single-context peak %s (%.0f%%) \u00b7 crossed at %s \u00b7 "
               "%.0f%% of output tokens above threshold \u00b7 forced compactions: %d"
               % (round(cf["rot_at"] * 100), tok(win), tok(cf["threshold_tokens"]),
                  tok(cf["main_peak_actual"]), 100.0 * cf["main_peak_actual"] / win,
                  tok(cf["peak_context_cf"]), 100.0 * cf["peak_context_cf"] / win,
                  crossed, cf["output_above_threshold_pct"], cf["forced_compactions"]))
    out.append("assumptions: " + "; ".join(cf["assumptions"]) + "; " + NO_QUALITY + ".")
    out.append("")
    return out


def session_report(s):
    out = []
    t = s["totals"]
    tm, ctx, it = s["timing"], s["context"], s["iterations"]
    out.append("# %s   (%s · %s → %s local)"
               % (s["name"], s["session"][:8], local_str(tm["first_prompt"] or s["started"]),
                  local_str(tm["last_assistant"] or s["ended"], "%H:%M")))
    head = ("Wall %s · active %s · %d prompts · %d turns · %d slash cmds · est. $%.2f"
            % (dur(tm["wall_s"]), dur(tm["active_s"]), it["user_prompts"], it["turns"],
               it["slash_commands"], t["cost_usd"]))
    head += " · version %s · browser %d%% (%d/%d main calls)" % (
        s.get("version") or VERSION_OLDER, round(100 * (s.get("browser_share") or 0.0)),
        s.get("browser_calls", 0), s.get("main_tool_calls", 0))
    if s.get("browser_session"):
        head += " · BROWSER SESSION (excluded from trends)"
    q_score = quality_score(s)
    if q_score:
        head += " · quality %d/5" % q_score
    out.append(head)
    q_note = ((s.get("quality") or {}).get("note") or "").strip()
    if q_score and q_note:
        out.append("Quality note: %s" % q_note)
    out.append("Main (%s): context at end %s (peak %s) · output %s tokens (%.1f%% of total) · %d API calls"
               % (short_model(ctx["main_model"]), tok(ctx["main_end_tokens"]),
                  tok(ctx["main_peak_tokens"]), tok(ctx["main_output_tokens"]),
                  ctx["main_output_pct"], ctx["main_api_calls"]))
    if s["workers"]:
        mix = " · ".join("%s %d" % (k, v)
                              for k, v in sorted(it["agent_runs_by_type"].items()))
        par = s["parallel"]
        if par["max_concurrent"] > 1 and par["overlaps"]:
            o = par["overlaps"][0]
            ptxt = "max %d concurrent (%s ∥ %s, %s)" % (
                par["max_concurrent"], o["a"], o["b"], dur(o["overlap_s"]))
        else:
            ptxt = "none"
        out.append("Workers: %d — %s · parallel: %s"
                   % (len(s["workers"]), mix, ptxt))
    else:
        out.append("Workers: none")
    out.append("By model: " + " · ".join(
        "%s %s out / $%.2f" % (short_model(m), tok(r["output"]), r["cost_usd"])
        for m, r in sorted(s["models"].items(), key=lambda kv: -kv[1]["cost_usd"])))
    out.append("")

    wasted = sum(f.get("est_wasted_tokens", 0) for f in s["flags"])
    out.append("## Inefficiencies (%d%s)"
               % (len(s["flags"]), ", ~%s tokens est. wasted" % tok(wasted) if wasted else ""))
    if s["flags"]:
        for f in s["flags"]:
            out.append("- [%s] %s: %s" % (f["code"], f["scope"], f["detail"]))
    else:
        out.append("- none over the thresholds")
    out.append("")
    out.extend(postmortem_lines(s))
    out.extend(counterfactual_lines(s))

    if s["workers"]:
        out.append("## Workers")
        out.append("")
        out.append("| # | type | model | start | dur | calls/limit | peak ctx | verify | "
                   "out tok | $ | brief | report | flags |")
        out.append("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for w in s["workers"]:
            codes = sorted(set(f["code"] for f in flags_by_scope(s, w["scope"])))
            calls = "%d/%s" % (w["api_calls"], w.get("turns_limit") or "?")
            out.append("| %d | %s | %s | %s | %s | %s | %s | %d/%d | %s | %.2f | %s | %s "
                       "| %s |"
                       % (w["n"], w["type"], short_model(w["model"]),
                          local_str(w["started"], "%H:%M"), dur(w["duration_s"]),
                          calls, tok(w.get("peak_ctx", 0)),
                          w.get("verify_with_fix", 0), w.get("verify_calls", 0),
                          tok(w["output_tokens"]), w["cost_usd"],
                          fmt(w["brief_chars"]), fmt(w["final_report_chars"]),
                          ", ".join(codes) or "-"))
        out.append("")

    for scope in ("main", "agents"):
        b = s["tool_output"][scope]
        if not b["results"]:
            continue
        top = " · ".join("%s %s" % (k, tok(v["chars"]))
                              for k, v in list(b["by_tool"].items())[:4])
        out.append("## Tool output — %s: %s chars (~%s tok) in %d results; %s"
                   % (scope, fmt(b["total_chars"]), tok(b["est_tokens"]), b["results"], top))
    out.append("")

    out.append("## Models")
    out.append("")
    out.append("| model | in | out | cache_read | cache_write | $ |")
    out.append("|---|---:|---:|---:|---:|---:|")
    for m, r in s["models"].items():
        out.append("| %s | %s | %s | %s | %s | %.2f |"
                   % (m, fmt(r["input"]), fmt(r["output"]), fmt(r["cache_read"]),
                      fmt(r["cache_creation"]), r["cost_usd"]))
    out.append("")

    rr = s["rereads"]
    if rr["main"] or rr["agents"]:
        out.append("## Re-reads")
        out.append("")
        for r in rr["main"]:
            out.append("- main: %d× %s (~%s tok wasted)"
                       % (r["reads"], r["path"], tok(r["wasted_chars"] // 4)))
        for scope, rows in sorted(rr["agents"].items()):
            for r in rows:
                out.append("- %s: %d× %s (~%s tok wasted)"
                           % (scope, r["reads"], r["path"], tok(r["wasted_chars"] // 4)))
        out.append("")
    if s["context"]["drops"]:
        out.append("Context drops (deduced, no compaction marker in the transcript): "
                   + " · ".join("%s %s→%s" % (local_str(d["at"], "%H:%M"),
                                                        tok(d["from"]), tok(d["to"]))
                                     for d in s["context"]["drops"][:5]))
        out.append("")
    if s["images"]:
        out.append("Images read: " + " · ".join(
            "%d× %s%s" % (im["reads"], os.path.basename(im["path"]),
                               " [downscaled]" if im["is_mic"] else "")
            for im in s["images"]))
        out.append("")
    return out


def aggregate_table(sessions):
    out = ["## Aggregate", ""]
    out.append("| session | project | wall | prompts | workers | ctx end | flags | in | out | "
               "cache_read | cache_write | % out sidechain | $ |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    agg = zeros()
    agg_cost = 0.0
    agg_side = 0
    for s in sessions:
        t = s["totals"]
        out.append("| %s | %s | %s | %d | %d | %s | %d | %s | %s | %s | %s | %.1f%% | %.2f |"
                   % (s.get("name") or s["session"][:8], s["project"],
                      dur(s["timing"]["wall_s"]), s["iterations"]["user_prompts"],
                      len(s["workers"]), tok(s["context"]["main_end_tokens"]),
                      len(s["flags"]),
                      fmt(t["input"]), fmt(t["output"]),
                      fmt(t["cache_read"]), fmt(t["cache_creation"]),
                      s["sidechain_output_pct"], t["cost_usd"]))
        for k in agg:
            agg[k] += t[k]
        agg_cost += t["cost_usd"]
        agg_side += s["sidechains"]["output"]
    pct = 100.0 * agg_side / (agg["output"] or 1)
    out.append("| **TOTAL** | %d sessions | %s | %d | %d | | %d | %s | %s | %s | %s | %.1f%% | %.2f |"
               % (len(sessions), dur(sum(s["timing"]["wall_s"] for s in sessions)),
                  sum(s["iterations"]["user_prompts"] for s in sessions),
                  sum(len(s["workers"]) for s in sessions),
                  sum(len(s["flags"]) for s in sessions),
                  fmt(agg["input"]), fmt(agg["output"]),
                  fmt(agg["cache_read"]), fmt(agg["cache_creation"]), pct, agg_cost))
    out.append("")
    return out


def markdown(sessions, aggregate=True):
    out = []
    for s in sessions:
        out.extend(session_report(s))
    if aggregate:
        out.extend(aggregate_table(sessions))
    return "\n".join(out)


# ---------------------------------------------------------------- trends

SESSION_KEYS = ("totals", "context", "started", "flags", "workers")


def load_session_dir(directory):
    """Session records written by --out-dir; anything trends_md cannot read is old format."""
    sessions, skipped = [], 0
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            skipped += 1
            continue
        for rec in (data if isinstance(data, list) else [data]):
            if isinstance(rec, dict) and all(k in rec for k in SESSION_KEYS):
                rec.setdefault("postmortem", {})
                rec.setdefault("counterfactual", {})
                sessions.append(rec)
            else:
                skipped += 1
    return sessions, skipped


def advice_of(code):
    tpl = RECOMMENDATION.get(code, "")
    return tpl.split(" - ", 1)[1] if " - " in tpl else tpl or "-"


def code_rows(sessions):
    rows = {}
    for s in sessions:
        for f in s.get("flags", []):
            e = rows.setdefault(f["code"], {"code": f["code"], "sessions": set(),
                                            "n": 0, "wasted": 0, "severity": "low"})
            e["sessions"].add(s.get("name") or s.get("session"))
            e["n"] += 1
            e["wasted"] += f.get("est_wasted_tokens", 0)
            if SEVERITY_ORDER[f.get("severity", "low")] < SEVERITY_ORDER[e["severity"]]:
                e["severity"] = f.get("severity", "low")
    return sorted(rows.values(), key=lambda e: (-len(e["sessions"]), -e["wasted"]))


# waste codes grouped into families; a code missing here lands in "other"
WASTE_FAMILIES = {
    "main_read_files": "reads",
    "reread": "reads",
    "full_read_big_file": "reads",
    "big_tool_result_main": "reads",
    "read_tool_results_main": "reads",
    "image_in_main": "reads",
    "long_agent_report": "agent overhead",
    "agent_reread_own_write": "agent overhead",
    "agent_ctx_high": "agent overhead",
    "sterile_verification": "agent overhead",
    "agent_max_turns": "agent overhead",
    "agent_no_report": "agent overhead",
    "narration_turns": "orchestration turns",
    "plan_echo": "orchestration turns",
    "long_brief": "orchestration turns",
    "batchable_bash": "orchestration turns",
    "cache_churn_main": "orchestration turns",
    "fable_wrote_code": "discipline",
    "too_many_runs": "discipline",
    "high_context_end": "discipline",
}
FAMILY_ORDER = ("reads", "agent overhead", "orchestration turns", "discipline", "other")


def usd(x):
    return "$%s" % format(float(x or 0.0), ",.2f")


def family_of(code):
    return WASTE_FAMILIES.get(code, "other")


def main_input_of(s):
    """Same weighting as postmortem_block: cache reads cost a tenth of fresh input."""
    m = s.get("main") or {}
    return (m.get("input", 0) + m.get("cache_creation", 0) + m.get("cache_read", 0) / 10.0)


def family_rows(sessions):
    """One row per waste family present, biggest first."""
    fam = {}
    for s in sessions:
        for f in s.get("flags", []):
            name = family_of(f["code"])
            e = fam.setdefault(name, {"family": name, "wasted": 0, "sessions": set(),
                                      "codes": {}})
            e["wasted"] += f.get("est_wasted_tokens", 0)
            e["sessions"].add(s.get("name") or s.get("session"))
            e["codes"][f["code"]] = e["codes"].get(f["code"], 0) + f.get("est_wasted_tokens", 0)
    out = list(fam.values())
    for e in out:
        e["top_code"] = max(e["codes"].items(), key=lambda kv: kv[1])[0] if e["codes"] else "-"
    out.sort(key=lambda e: (-e["wasted"], FAMILY_ORDER.index(e["family"])
                            if e["family"] in FAMILY_ORDER else 99))
    return out


def group_range(sessions):
    days = sorted(local_day(s.get("started")) for s in sessions if s.get("started"))
    return (days[0] if days else "?", days[-1] if days else "?")


def version_stats(sessions):
    """Per-session figures for one version group; the Versions table and the Δ line share them."""
    n = len(sessions)
    d = float(n or 1)
    cfs = [s.get("counterfactual") or {} for s in sessions]
    pms = [s.get("postmortem") or {} for s in sessions]
    ctxs = [s.get("context") or {} for s in sessions]
    sevs = [p.get("severity_counts") or {} for p in pms]
    rr = [c["ratio_realistic"] for c in cfs if c.get("ratio_realistic")]
    hands = sum(p.get("hands_on_calls", 0) for p in pms)
    calls = sum(p.get("main_tool_calls", 0) for p in pms)
    actual = sum((s.get("totals") or {}).get("cost_usd", 0.0) for s in sessions)
    real = sum(c.get("realistic_usd", 0.0) for c in cfs)
    floor = sum(c.get("floor_usd", 0.0) for c in cfs)
    wasted = sum(p.get("wasted_total", 0) for p in pms)
    main_in = sum(main_input_of(s) for s in sessions)
    scores = [q for q in (quality_score(s) for s in sessions) if q]
    return {
        "n": n,
        "rated": len(scores),
        "q_mean": (sum(scores) / float(len(scores))) if scores else None,
        "actual": actual,
        "actual_per": actual / d,
        "real": real,
        "real_per": real / d,
        "floor": floor,
        "saved": real - actual,
        "saved_pct": 100.0 * (real - actual) / (real or 1),
        "saved_floor": floor - actual,
        "n_cf": sum(1 for c in cfs if c.get("realistic_usd")),
        "ratio": sum(rr) / (len(rr) or 1),
        "out_pct": sum(c.get("main_output_pct", 0.0) for c in ctxs) / d,
        "hands": hands,
        "calls": calls,
        "hands_pct": 100.0 * hands / (calls or 1),
        "issues_per": sum(len(s.get("flags") or []) for s in sessions) / d,
        "high_per": sum(x.get("high", 0) for x in sevs) / d,
        "med_per": sum(x.get("medium", 0) for x in sevs) / d,
        "low_per": sum(x.get("low", 0) for x in sevs) / d,
        "wasted": wasted,
        "wasted_per": wasted / d,
        "main_input": main_in,
        "wasted_pct": 100.0 * wasted / (main_in or 1),
        "n_pm": sum(1 for p in pms if p.get("wasted_total") is not None),
        "peak_ctx": sum(c.get("main_peak_tokens", 0) for c in ctxs) / d,
    }


# (label, key, unit): "pts" for fields that are already percentages
DELTA_FIELDS = (("$/session", "actual_per", "rel"), ("saved %", "saved_pct", "pts"),
                ("wasted/session", "wasted_per", "rel"), ("wasted %", "wasted_pct", "pts"),
                ("issues/session", "issues_per", "rel"), ("main output %", "out_pct", "pts"),
                ("hands-on %", "hands_pct", "pts"))


def delta_cell(base, cur, key, unit):
    a, b = base.get(key), cur.get(key)
    if a is None or b is None:
        return "—"
    if unit == "pts":
        return "%+.1f pts" % (b - a)
    return "n/a" if not a else "%+.0f%%" % (100.0 * (b - a) / a)


def delta_line(base_name, base, cur):
    parts = ["%s %s" % (label, delta_cell(base, cur, key, unit))
             for label, key, unit in DELTA_FIELDS]
    if base.get("q_mean") is not None and cur.get("q_mean") is not None:
        parts.append("quality %+.1f" % (cur["q_mean"] - base["q_mean"]))
    return "- **vs %s:** %s" % (base_name, " · ".join(parts))


def versions_table(order, groups, cum):
    out = ["## Versions", ""]
    out.append("| version | sessions | $ actual | $/session | $ Fable realistic | saved $ "
               "| saved % | saved cumulative | wasted tok/session | wasted % "
               "| issues/session (H/M/L) | main output % | hands-on | peak ctx | quality |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in order:
        v = version_stats(groups.get(name) or [])
        if not v["n"]:
            out.append("| %s | 0 |%s" % (name, " — |" * 13))
            continue
        out.append("| %s | %d | %s | %s | %s | %s | %.1f%% | %s | %s | %.1f%% "
                   "| %.1f (%.1f/%.1f/%.1f) | %.1f%% | %d/%d (%.0f%%) | %s | %s · %d/%d |"
                   % (name, v["n"], usd(v["actual"]), usd(v["actual_per"]), usd(v["real"]),
                      usd(v["saved"]), v["saved_pct"], usd(cum.get(name, 0.0)),
                      tok(v["wasted_per"]), v["wasted_pct"],
                      v["issues_per"], v["high_per"], v["med_per"], v["low_per"],
                      v["out_pct"], v["hands"], v["calls"], v["hands_pct"],
                      tok(v["peak_ctx"]),
                      "—" if v["q_mean"] is None else "%.1f" % v["q_mean"],
                      v["rated"], v["n"]))
    out.append("")
    return out


def deltas_table(order, groups):
    """Every non-older version with sessions, compared to the previous one and to older."""
    live = [name for name in order if groups.get(name)]
    older = version_stats(groups.get(VERSION_OLDER) or [])
    out = ["### Deltas", ""]
    out.append("| version | vs | " + " | ".join(l for l, _, _ in DELTA_FIELDS) + " |")
    out.append("|---|---|" + "---:|" * len(DELTA_FIELDS))
    rows = 0
    for i, name in enumerate(live):
        if name == VERSION_OLDER:
            continue
        cur = version_stats(groups[name])
        pairs = []
        if i > 0:
            pairs.append((live[i - 1], version_stats(groups[live[i - 1]])))
        if older["n"] and (i == 0 or live[i - 1] != VERSION_OLDER):
            pairs.append((VERSION_OLDER, older))
        for base_name, base in pairs:
            out.append("| %s | %s | %s |"
                       % (name, base_name,
                          " | ".join(delta_cell(base, cur, k, u) for _, k, u in DELTA_FIELDS)))
            rows += 1
    if not rows:
        out.append("| — | — |" + " — |" * len(DELTA_FIELDS))
    out.append("")
    return out


def corpus_block(kept, skipped_note):
    v = version_stats(kept)
    lo, hi = group_range(kept)
    out = ["## Corpus", ""]
    out.append("- **Spend:** %s actual across %d sessions (%s/session)"
               % (usd(v["actual"]), v["n"], usd(v["actual_per"])))
    out.append("- **Fable-only realistic:** %s (floor %s) → **saved %s (%.1f%%)**"
               % (usd(v["real"]), usd(v["floor"]), usd(v["saved"]), v["saved_pct"]))
    out.append("- **Est. wasted:** ~%s tokens = %.1f%% of main input volume"
               % (tok(v["wasted"]), v["wasted_pct"]))
    out.append("- **Quality:** %s mean · %d/%d rated"
               % ("—" if v["q_mean"] is None else "%.1f" % v["q_mean"],
                  v["rated"], v["n"]))
    out.append("- **Span:** %s → %s · %d/%d sessions with a counterfactual%s"
               % (lo, hi, v["n_cf"], v["n"], skipped_note))
    out.append("")
    return out


def version_block(name, sessions, groups, prev_name, cum):
    """The whole per-version section: at a glance, waste families, flag tables, sessions."""
    n = len(sessions)
    lo, hi = group_range(sessions)
    v = version_stats(sessions)
    out = ["## %s — %d sessions (%s → %s)" % (name, n, lo, hi), ""]
    out.append("**At a glance**")
    out.append("")
    out.append("- **Spend:** %s · %s/session" % (usd(v["actual"]), usd(v["actual_per"])))
    out.append("- **Fable-only realistic:** %s (floor %s) → **saved %s (%.1f%%)**; "
               "cumulative through %s: %s"
               % (usd(v["real"]), usd(v["floor"]), usd(v["saved"]), v["saved_pct"],
                  name, usd(cum.get(name, 0.0))))
    out.append("- **Waste:** ~%s tokens = %.1f%% of main input volume · %.1f issues/session "
               "(%.1f H / %.1f M / %.1f L)"
               % (tok(v["wasted"]), v["wasted_pct"], v["issues_per"],
                  v["high_per"], v["med_per"], v["low_per"]))
    if prev_name:
        out.append(delta_line(prev_name, version_stats(groups[prev_name]), v))
    if name != VERSION_OLDER and prev_name != VERSION_OLDER and groups.get(VERSION_OLDER):
        out.append(delta_line(VERSION_OLDER, version_stats(groups[VERSION_OLDER]), v))
    out.append("- **Shape:** main output %.1f%% · hands-on %.0f%% · peak ctx %s "
               "· quality %s (%d/%d rated)"
               % (v["out_pct"], v["hands_pct"], tok(v["peak_ctx"]),
                  "—" if v["q_mean"] is None else "%.1f" % v["q_mean"],
                  v["rated"], v["n"]))
    out.append("")

    out.append("**Waste by category**")
    out.append("")
    out.append("| family | est. wasted | % of waste | % of main input | sessions | top code |")
    out.append("|---|---:|---:|---:|---:|---|")
    fams = family_rows(sessions)
    for f in fams:
        out.append("| %s | %s | %.1f%% | %.1f%% | %d/%d | %s |"
                   % (f["family"], tok(f["wasted"]),
                      100.0 * f["wasted"] / (v["wasted"] or 1),
                      100.0 * f["wasted"] / (v["main_input"] or 1),
                      len(f["sessions"]), n, f["top_code"]))
    if not fams:
        out.append("| none | 0 | 0.0%% | 0.0%% | 0/%d | - |" % n)
    out.append("")

    rows = code_rows(sessions)
    for title, sel in (("Recurring inefficiencies** (≥2 sessions)",
                        [r for r in rows if len(r["sessions"]) >= 2]),
                       ("One-off**", [r for r in rows if len(r["sessions"]) < 2])):
        out.append("**%s" % title)
        out.append("")
        if not sel:
            out.append("none")
            out.append("")
            continue
        out.append("| code | family | severity | sessions | occurrences | est. wasted "
                   "| % of waste | recommendation |")
        out.append("|---|---|---|---:|---:|---:|---:|---|")
        for r in sel:
            out.append("| %s | %s | %s | %d/%d | %d | %s | %.1f%% | %s |"
                       % (r["code"], family_of(r["code"]), r["severity"],
                          len(r["sessions"]), n, r["n"], tok(r["wasted"]),
                          100.0 * r["wasted"] / (v["wasted"] or 1), advice_of(r["code"])))
        out.append("")

    out.append("**Sessions**")
    out.append("")
    out.append("| session | $ actual | $ fable-only realistic | saved $ | main output % | "
               "hands-on ratio | issues (H/M/L) | wasted tok | wasted % | peak ctx | q |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    recent = sorted(sessions, key=lambda s: s.get("started") or "", reverse=True)[:15]
    for s in recent:
        pm = s.get("postmortem") or {}
        cf = s.get("counterfactual") or {}
        sev = pm.get("severity_counts") or {}
        ctx = s.get("context") or {}
        q = quality_score(s)
        act = (s.get("totals") or {}).get("cost_usd", 0.0)
        out.append("| %s | %.2f | %.2f | %.2f | %.1f%% | %d/%d | %d/%d/%d | %s | %.1f%% | %s | %s |"
                   % (s.get("name") or s.get("session") or "?",
                      act, cf.get("realistic_usd", 0.0),
                      cf.get("realistic_usd", 0.0) - act,
                      ctx.get("main_output_pct", 0.0),
                      pm.get("hands_on_calls", 0), pm.get("main_tool_calls", 0),
                      sev.get("high", 0), sev.get("medium", 0), sev.get("low", 0),
                      tok(pm.get("wasted_total", 0)),
                      pm.get("wasted_pct_of_main_input", 0.0),
                      tok(ctx.get("main_peak_tokens", 0)), q if q else "—"))
    out.append("")
    return out


def is_empty_session(s):
    """A tab opened for /usage only: no API call in main and nothing billed."""
    ctx = s.get("context") or {}
    calls = ctx.get("main_api_calls")
    if calls is None:
        calls = (s.get("postmortem") or {}).get("main_api_calls", 0)
    return not calls and not (s.get("totals") or {}).get("cost_usd", 0.0)


def excluded_table(excluded, threshold):
    out = ["## Excluded (browser ≥%d%% of main tool calls · empty sessions)"
           % round(threshold * 100), ""]
    if not excluded:
        out.append("none")
        out.append("")
        return out
    out.append("| session | version | reason | browser share | browser/main calls |")
    out.append("|---|---|---|---:|---:|")
    for s in sorted(excluded, key=lambda s: s.get("started") or "", reverse=True):
        out.append("| %s | %s | %s | %.0f%% | %d/%d |"
                   % (s.get("name") or s.get("session") or "?", s.get("version") or VERSION_OLDER,
                      s["exclude_reason"], 100.0 * s["browser_share"],
                      s.get("browser_calls", 0), s.get("main_tool_calls", 0)))
    out.append("")
    return out


def trends_md(sessions, skipped, versions=None, threshold=BROWSER_THRESHOLD_DEFAULT):
    versions = versions or []
    kept, excluded = [], []
    for s in sessions:
        # version and browser flag are recomputed here: editing versions.json regroups old JSONs
        s["version"] = version_of(s.get("started"), versions)
        try:
            share = float(s.get("browser_share") or 0.0)
        except (TypeError, ValueError):
            share = 0.0
        s["browser_share"] = share
        # old-format JSON has no browser_share -> 0.0, never excluded
        s["browser_session"] = share > 0.0 and share >= threshold
        if s["browser_session"]:
            s["exclude_reason"] = "browser %.0f%%" % (100.0 * share)
        elif is_empty_session(s):
            s["exclude_reason"] = "empty"
        else:
            s["exclude_reason"] = None
        (excluded if s["exclude_reason"] else kept).append(s)

    order = version_names(versions)
    groups = collections.OrderedDict((name, []) for name in order)
    for s in kept:
        groups.setdefault(s["version"], []).append(s)
    for name in groups:
        if name not in order:
            order.append(name)

    # cumulative savings run in version order, so the last live version holds the corpus total
    cum, running = {}, 0.0
    for name in order:
        if groups.get(name):
            running += version_stats(groups[name])["saved"]
        cum[name] = running

    lo, hi = group_range(kept)
    n_browser = sum(1 for s in excluded if s["browser_session"])
    skipped_note = " · %d skipped (old format)" % skipped if skipped else ""
    out = ["# TRENDS — %d sessions kept (%s → %s) · excluded %d "
           "(browser %d · empty %d)"
           % (len(kept), lo, hi, len(excluded), n_browser, len(excluded) - n_browser)]
    out.append("")
    out.extend(corpus_block(kept, skipped_note))
    out.extend(versions_table(order, groups, cum))
    out.extend(deltas_table(order, groups))
    live = [name for name in order if groups.get(name)]
    for i, name in enumerate(live):
        out.append("---")
        out.append("")
        out.extend(version_block(name, groups[name], groups,
                                 live[i - 1] if i else None, cum))
    out.append("---")
    out.append("")
    out.extend(excluded_table(excluded, threshold))
    return "\n".join(out)


# ---------------------------------------------------------------- rename

def rename_dir(directory, force=False):
    """<uuid>.json (+ .md) -> <name>.json, using the transcript path stored in the JSON."""
    done = 0
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".json"):
            continue
        src = os.path.join(directory, entry)
        try:
            with open(src, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            print("skip %s: unreadable (%s)" % (entry, exc), file=sys.stderr)
            continue
        rec = data[0] if isinstance(data, list) and data else data
        path = rec.get("path") if isinstance(rec, dict) else None
        if not path or not os.path.isfile(path):
            print("skip %s: transcript missing (%s)" % (entry, path), file=sys.stderr)
            continue
        name = session_name(path)
        if name + ".json" == entry:
            continue
        stem = entry[:-len(".json")]
        pairs = [(os.path.join(directory, stem + ext), os.path.join(directory, name + ext))
                 for ext in (".json", ".md")]
        # a half-rename would orphan the .md next to it -> either both move or neither
        clash = [n for o, n in pairs if os.path.isfile(o) and os.path.exists(n)]
        if clash and not force:
            print("skip %s: %s exists" % (entry, ", ".join(os.path.basename(c) for c in clash)),
                  file=sys.stderr)
            continue
        for old, new in pairs:
            if not os.path.isfile(old):
                continue
            os.rename(old, new)
            print("%s -> %s" % (os.path.basename(old), os.path.basename(new)))
            if old.endswith(".json"):
                done += 1
    return done


# ---------------------------------------------------------------- cli

def read_record(path):
    """The one session record stored in <name>.json by --out-dir, or None."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    rec = data[0] if isinstance(data, list) and data else data
    return rec if isinstance(rec, dict) else None


def write_record(out_dir, name, rec):
    """Rewrite <name>.json and, if present, <name>.md from one session record."""
    with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps([rec], indent=2, ensure_ascii=False) + "\n")
    md_path = os.path.join(out_dir, name + ".md")
    if os.path.isfile(md_path):
        try:
            text = markdown([rec], aggregate=False) + "\n"
        except (KeyError, TypeError, ValueError):
            text = None
        if text:
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(text)


def refresh_versions(directory, versions):
    """Editing versions.json moves boundaries: put the recomputed version back into each
    session's .json/.md so the files agree with TRENDS.md. Returns how many changed."""
    changed = 0
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json"):
            continue
        rec = read_record(os.path.join(directory, fname))
        if rec is None or "started" not in rec:
            continue
        new = version_of(rec.get("started"), versions)
        if rec.get("version") != new:
            rec["version"] = new
            write_record(directory, fname[:-5], rec)
            changed += 1
    return changed


def write_trends(directory, versions, threshold):
    if not os.path.isdir(directory):
        print("nu e director: %s" % directory, file=sys.stderr)
        return 2
    refreshed = refresh_versions(directory, versions)
    if refreshed:
        print("versiune actualizata in %d sesiuni" % refreshed, file=sys.stderr)
    sessions, skipped = load_session_dir(directory)
    if not sessions:
        print("niciun raport de sesiune in %s" % directory, file=sys.stderr)
        return 1
    text = trends_md(sessions, skipped, versions, threshold) + "\n"
    tmp = os.path.join(directory, "TRENDS.md.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, os.path.join(directory, "TRENDS.md"))
    print("TRENDS.md: %d sessions, %d skipped" % (len(sessions), skipped), file=sys.stderr)
    return 0


def rate_session(out_dir, name, score, note, versions, threshold):
    """--rate: write quality into <name>.json, refresh its .md, then rebuild TRENDS.md."""
    path = os.path.join(out_dir, name + ".json")
    rec = read_record(path)
    if rec is None:
        print("nu gasesc sesiunea: %s" % path, file=sys.stderr)
        return 1
    rec["quality"] = {"score": score, "note": note,
                      "rated_at": datetime.datetime.now(datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ")}
    write_record(out_dir, name, rec)
    print("%s: quality %d/5" % (name, score), file=sys.stderr)
    return write_trends(out_dir, versions, threshold)


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir_default = os.path.normpath(os.path.join(here, os.pardir, "metrics-local"))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help=".jsonl session files or directories")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--md", action="store_true", help="Markdown output")
    ap.add_argument("--out", help="write everything to one file instead of stdout")
    ap.add_argument("--out-dir", dest="out_dir",
                    help="write <name>.json / <name>.md per session in this directory")
    ap.add_argument("--rename", metavar="DIR",
                    help="rename <uuid>.json/.md in DIR to <name>.json/.md and exit")
    ap.add_argument("--force", action="store_true",
                    help="with --rename: overwrite an existing target name")
    ap.add_argument("--ctx-warn", dest="ctx_warn", type=int,
                    default=THRESHOLDS["high_context_end"],
                    help="flag the session when the main context ends above this (tokens)")
    ap.add_argument("--agents-dir", dest="agents_dir", default=AGENTS_DIR_DEFAULT,
                    help="where <agent-type>.md lives; its maxTurns: gives the worker limit "
                         "(default %s)" % AGENTS_DIR_DEFAULT)
    ap.add_argument("--as-model", dest="as_model", default=AS_MODEL_DEFAULT,
                    help="model whose rates price the single-context estimate "
                         "(default %s)" % AS_MODEL_DEFAULT)
    ap.add_argument("--rot-at", dest="rot_at", type=float, default=ROT_AT_DEFAULT,
                    help="operator threshold as a fraction of the window (default %s)"
                         % ROT_AT_DEFAULT)
    ap.add_argument("--window", type=int, default=WINDOW_DEFAULT,
                    help="context window used by the estimate (default %d)" % WINDOW_DEFAULT)
    ap.add_argument("--trends", metavar="DIR",
                    help="rewrite DIR/TRENDS.md from the session .json files in DIR and exit")
    ap.add_argument("--rating-file", dest="rating_file", metavar="PATH",
                    help="pending-rating.json written by /rate; attached as 'quality' to the "
                         "analyzed session when project and timestamp match, then deleted")
    ap.add_argument("--rate", nargs=2, metavar=("NAME", "SCORE"),
                    help="score a session already in --out-dir (default %s): NAME is the "
                         "file stem, SCORE an int 1-5; rewrites its .json/.md and TRENDS.md"
                         % out_dir_default)
    ap.add_argument("--note", default="", help="with --rate: one-line note stored next to "
                                               "the score")
    ap.add_argument("--pricing", default=os.path.join(here, "pricing.json"))
    ap.add_argument("--versions", default=os.path.join(here, "versions.json"),
                    help="workflow versions (name + start day) used to group sessions "
                         "in TRENDS.md; missing file means every session is '%s'" % VERSION_OLDER)
    ap.add_argument("--browser-threshold", dest="browser_threshold", type=float,
                    default=BROWSER_THRESHOLD_DEFAULT,
                    help="share of main tool calls on %s* above which the session is "
                         "excluded from the trends (default %s)"
                         % (BROWSER_TOOL_PREFIX, BROWSER_THRESHOLD_DEFAULT))
    args = ap.parse_args(argv)
    versions = load_versions(args.versions)

    if args.rename:
        if not os.path.isdir(args.rename):
            print("nu e director: %s" % args.rename, file=sys.stderr)
            return 2
        rename_dir(args.rename, args.force)
        return 0

    if args.trends:
        return write_trends(args.trends, versions, args.browser_threshold)

    if args.rate:
        name, raw = args.rate
        score = clean_score(raw)
        if score is None:
            print("scor invalid: %s (se cere un intreg 1-5)" % raw, file=sys.stderr)
            return 1
        return rate_session(args.out_dir or out_dir_default, name, score,
                            args.note.strip(), versions, args.browser_threshold)

    if not args.paths:
        ap.error("dai cel putin un .jsonl / director, sau --rename DIR")
    if not args.json and not args.md:
        args.md = True

    try:
        pricing = load_pricing(args.pricing)
    except (OSError, ValueError) as exc:
        print("pricing ilizibil (%s): %s" % (args.pricing, exc), file=sys.stderr)
        return 2

    targets = collect_targets(args.paths)
    if not targets:
        print("niciun .jsonl gasit", file=sys.stderr)
        return 1

    sessions = [analyze(p, pricing, args.ctx_warn, args.agents_dir,
                        args.as_model, args.rot_at, args.window,
                        versions, args.browser_threshold) for p in targets]
    sessions.sort(key=lambda s: -s["totals"]["output"])

    rating = load_rating(args.rating_file) if args.rating_file else None

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        used_rating = False
        for s in sessions:
            json_path = os.path.join(args.out_dir, s["name"] + ".json")
            if rating and not used_rating and rating_matches(rating, s):
                s["quality"] = quality_of(rating)
                used_rating = True
            if "quality" not in s:
                # regeneration must not drop a score written earlier
                old = (read_record(json_path) or {}).get("quality")
                if old:
                    s["quality"] = old
            if args.json:
                with open(json_path, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps([s], indent=2, ensure_ascii=False) + "\n")
            if args.md:
                with open(os.path.join(args.out_dir, s["name"] + ".md"),
                          "w", encoding="utf-8") as fh:
                    fh.write(markdown([s], aggregate=False) + "\n")
        # the score survives only in the .json; without it the pending file must stay
        if used_rating and args.json:
            try:
                os.remove(args.rating_file)
            except OSError:
                pass
        return 0

    chunks = []
    if args.json:
        chunks.append(json.dumps(sessions, indent=2, ensure_ascii=False))
    if args.md:
        chunks.append(markdown(sessions))
    text = "\n\n".join(chunks)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
