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
FILE_TOKEN_RE = re.compile(r"[\w./~$-]+\.[A-Za-z0-9]+")
REPORT_DIR_RE = re.compile(r"docs/(?:refine|polish)/")


def only_report_paths(cmd):
    """A Bash read whose every file argument is a refine/polish report main asked for."""
    paths = FILE_TOKEN_RE.findall(cmd)
    return bool(paths) and all(REPORT_DIR_RE.search(p) for p in paths)
# harness tag on the user message that carries an async agent's result back into main
TASK_NOTIFICATION_RE = re.compile(r"<task-notification>")

BROWSER_TOOL_PREFIX = "mcp__claude-in-chrome__"
BROWSER_THRESHOLD_DEFAULT = 0.5  # share of main tool calls above which the session is not workflow
VERSION_OLDER = "older"

AGENTS_DIR_DEFAULT = "~/.claude/agents"
AS_MODEL_DEFAULT = "claude-fable-5-1"
ROT_AT_DEFAULT = 0.35            # operator threshold, not an Anthropic figure
WINDOW_DEFAULT = 1_000_000
NO_QUALITY = ("no quality claim — the threshold is the operator's, not Anthropic's")
MAX_TURNS_FM_RE = re.compile(r"^maxTurns:\s*(\d+)\s*$", re.M)

# 🔴 numbers are not compared across task classes — DECIZII «Clasa de task»
GOVERNANCE_PROJECTS = {"agent-governance"}


def task_class(record_or_project):
    """`governance-rd` for the meta-projects, `product` for the rest; record or project slug."""
    if isinstance(record_or_project, dict):
        if record_or_project.get("task_class"):
            return record_or_project["task_class"]
        project = record_or_project.get("project") or ""
    else:
        project = record_or_project or ""
    project = str(project)
    for name in GOVERNANCE_PROJECTS:
        if project == name or project.endswith("-" + name) or project.endswith("/" + name):
            return "governance-rd"
    return "product"

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
IMAGE_CHARS = 6000
IMG_BIG_BYTES = 200 * 1024
COST_KEYS = (("input", "input"), ("output", "output"),
             ("cache_read", "cache_read"), ("cache_creation", "cache_write"))

# every threshold that turns a measurement into a flag; mirrors the hooks in hooks/
THRESHOLDS = {
    "big_tool_result_main": 10000,   # chars of a single tool_result in the main context
    "full_read_lines": 300,          # lines returned by a Read without offset/limit
    "long_agent_report": 2000,       # chars of a worker's final message
    "long_agent_report_explorer_max": 6000,  # hooks/raport-lung.sh: explorer-max* cap
    "long_brief": 7000,              # chars of Agent.input.prompt
    "max_implementer_runs": 3,       # implementer + implementer-complex + implementer-max + implementer-sonnet + scripter + scripter-complex per session
    "max_live_agents": 6,             # hard cap on concurrently running sub-agents; over it = parallel_over_cap
    "max_explorer_runs": 3,
    "fable_code_lines": 20,          # lines written by Edit/Write in main
    "high_context_end": 150000,      # main context at the last API call
    "cache_churn_pct": 25.0,         # cache_creation / (cache_read + cache_creation), main
    "context_drop_pct": 30.0,        # drop between two consecutive main calls
    "flag_examples": 5,              # per code, per scope: how many are listed one by one
    "main_read_chars": 2000,         # any Bash read in main under this is a targeted lookup
    "narration_avoidable_calls": 2,  # narration calls with no live agent and no question to the user (residual_poll = harness re-notify)
    "narration_text_chars": 300,     # under this, an answer is narration, not work
    "batchable_calls": 3,            # consecutive one-Bash API calls that could be one
    "batchable_chars": 2000,         # ...and together return less than this
    "plan_echo_chars": 8000,         # ExitPlanMode result echoed back into main
    "agent_peak_ctx": 200000,        # worker context past the measured degradation band
    "sterile_verify_calls": 6,       # verification runs below which the ratio says nothing
    "sterile_verify_ratio": 0.2,     # share of verifications that led to a fix
    "comment_block_lines": 2,        # consecutive comment lines added by one Edit/Write
    "comment_long_line": 160,        # chars of a single added comment line
    "comment_ratio": 0.25,           # added comment lines / added lines
    "comment_min_added": 5,
    "late_first_edit_ctx": 100000,   # worker context when it finally writes
    "late_first_edit_reads": 15,     # reading calls before the first write
    "main_read_before_agent": 20000, # chars main read itself before launching any agent
    "edit_via_bash_calls": 2,        # heredoc writes into source files, with no Edit/Write
    "effort_lag_turns": 3,           # main turns after ExitPlanMode still not on low
    "cache_rewrite_pct": 50,         # share of the call's context that is a rewrite
    "cache_rewrite_prev_tokens": 30000,  # cached context that existed on the previous call
    "cache_rewrite_max_gap_s": 3600,     # over an hour the cache expires legitimately
    "agent_resume_gap_s": 300,       # the 5m cache of a sub-agent is gone past this pause
    "agent_resume_read_pct": 20,     # cache_read share on the first call after the pause
    "scripter_min_files": 4,         # a scripter under this is cheaper as an implementer
}

FLAG_TEXT = {
    "reread": ("same file read more than once "
               "(not counted if a Bash command rewrote it between the reads)"),
    "big_tool_result_main": "large tool_result landed in the main context",
    "full_read_big_file": "Read without offset/limit on a big file",
    "image_in_main": "full-size image read in the main context",
    "long_agent_report": "worker final report over budget",
    "long_brief": "brief over budget",
    "too_many_runs": "agent run cap exceeded",
    "parallel_over_cap": "too many sub-agents running at once",
    "comment_bloat": "comment blocks written into the code instead of a pointer line",
    "fable_wrote_code": "main model wrote code instead of delegating",
    "read_tool_results_main": "tool-results/ re-read in the main context",
    "high_context_end": "main context high at the end of the session",
    "cache_churn_main": "cache rewritten too often in main",
    "cache_rewrite_main": "one main call rewrote the cache although the previous call still "
                          "had a live cached context (per call, not per session)",
    "agent_resume_rewrite": "sub-agent resumed after over 5 min: the 5m cache had expired and "
                            "the context was rewritten",
    "scripter_below_threshold": "scripter run under the threshold that makes it cheaper than "
                                "an implementer",
    "agent_max_turns": "worker stopped by maxTurns",
    "agent_no_report": "worker ended without a final report",
    "agent_reread_own_write": "worker re-read a file it had just written",
    "main_read_files": "main read files through Bash instead of delegating",
    "main_read_report": "main read a refine/polish report it had asked for; visible, not taxed",
    "narration_turns": "main ended a turn on a note with nothing running and nothing asked; "
                       "wasted = cache_read / 10 (input-equivalent, the cached context "
                       "re-sent for nothing); a note while an async agent is live, right "
                       "after a launch, a question or the last turn is structural, counted "
                       "but not taxed; residual_poll = harness re-notifying a done agent",
    "batchable_bash": "consecutive Bash calls that fit in one call",
    "plan_echo": "plan echoed back into main as a tool_result",
    "sterile_verification": "worker re-ran the checker without it catching anything",
    "agent_ctx_high": "worker context past the degradation threshold",
    "tool_results_read": "worker read a tool-results/ file instead of re-running a narrower command",
    "late_first_edit": "worker read its way to a decision before writing anything",
    "main_read_before_first_agent": "main gathered the facts itself before the first agent",
    "max_without_sendmessage": "implementer-max launched without a SendMessage first",
    "agent_read_plan_whole": "worker read the whole plan file instead of its brief",
    "edit_via_bash": "worker edited source files through Bash instead of Edit/Write",
    "advisor_mandatory_missed": "two auditor reports with ABATERI in a row and no advisor "
                                "before the next brief",
    "advisor_trigger_b_missed": "plan touches hooks/config/migration and no advisor was "
                                "called before ExitPlanMode (heuristic on the plan text)",
    "effort_lag_high": "the low phase started too many turns after ExitPlanMode",
    "no_low_phase": "v1.7 session with a plan approved and no low turn",
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
    "late_first_edit": "high",
    "main_read_before_first_agent": "high",
    "max_without_sendmessage": "high",
    "advisor_mandatory_missed": "high",
    "no_low_phase": "high",
    "advisor_trigger_b_missed": "medium",
    "effort_lag_high": "medium",
    "agent_read_plan_whole": "medium",
    "edit_via_bash": "medium",
    "big_tool_result_main": "medium",
    "tool_results_read": "medium",
    "reread": "medium",
    "main_read_files": "medium",
    "high_context_end": "medium",
    "cache_churn_main": "medium",
    "cache_rewrite_main": "medium",
    "agent_resume_rewrite": "medium",
    "long_brief": "medium",
    "plan_echo": "medium",
    "sterile_verification": "medium",
    "parallel_over_cap": "medium",
    "comment_bloat": "medium",
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
    "long_agent_report": "{detail} - soft cap 1.5k, hard cap 2k (explorer-max*: 4.5k/6k), "
                         "fixed format.",
    "long_brief": "{detail} - over 7k the brief belongs in a plan file; the prompt is path "
                  "+ section.",
    "too_many_runs": "{detail} - split the work at plan time, do not re-send the same brief.",
    "fable_wrote_code": "{detail} - delegate it; main writes at most ~20 lines in one file.",
    "read_tool_results_main": "{detail} - ask the explorer for the fact; the result was "
                              "already paid for once.",
    "high_context_end": "{detail} - hand off earlier; a fresh session starts cheap.",
    "cache_churn_main": "{detail} - keep a stable prefix; do not edit early context.",
    "cache_rewrite_main": "{detail} - the previous call still had a live cache; check what "
                          "changed in the prefix (config, hooks, an edited early message).",
    "agent_resume_rewrite": "{detail} - a resume after more than 5 minutes costs one context "
                            "rewrite; still cheaper than a fresh agent under 150k.",
    "scripter_below_threshold": "{detail} - a scripter pays off from 8 changes over at least "
                                "4 files; below that an implementer is cheaper.",
    "agent_max_turns": "{detail} - the brief was too large; split it instead of re-running.",
    "agent_no_report": "{detail} - brief unclear or the worker died; re-send once with the "
                       "missing piece.",
    "agent_reread_own_write": "{detail} - the write already succeeded; do not read it back.",
    "main_read_files": "{detail} - delegate the reading; an audit is `git diff --stat` "
                       "plus a targeted grep.",
    "main_read_report": "{detail} - legitimate: main reads the report it asked for; 0 tokens.",
    "narration_turns": "{detail} - text-only calls with no live agent; residual_poll = the harness "
                       "re-sent a notification for an already-notified agent, not a rule miss.",
    "batchable_bash": "{detail} - one Bash call chained with `;` / `&&`.",
    "plan_echo": "{detail} - keep the plan under 8k; briefs go in the plan file, the prompt "
                 "is path + section.",
    "sterile_verification": "{detail} - run the checker once at the end and once after "
                            "fixes, not after every edit.",
    "agent_ctx_high": "{detail} - split the brief at plan time; the hook wraps the agent "
                      "up at 150k.",
    "parallel_over_cap": "{detail} - launch at most 6 agents at once; parallel beyond that "
                         "only multiplies reports and audits landing in main together.",
    "tool_results_read": "{detail} - Bash output too large; re-run the command on a "
                         "narrower range instead of reading the saved file.",
    "late_first_edit": "{detail} - decision reading belongs in a dossier written by an "
                       "explorer; the implementer gets line ranges.",
    "main_read_before_first_agent": "{detail} - facts before the first agent belong to an "
                                    "explorer; main reads `git diff --stat`, reports and at "
                                    "most one dossier.",
    "max_without_sendmessage": "{detail} - a non-conform audit goes first to the live "
                               "implementer via SendMessage; implementer-max needs a written "
                               "reason (logic + failed SendMessage / dead context / declared "
                               "debugging).",
    "agent_read_plan_whole": "{detail} - the agent gets its own brief file "
                             "(scratchpad/brief-N.md), not the whole plan.",
    "edit_via_bash": "{detail} - code edits go through Edit/Write; Bash heredocs bypass the "
                     "comment hook and the verify counter.",
    "comment_bloat": "{detail} - a new comment is one pointer line; the explanation "
                      "belongs in PATTERNS/DECIZII, not in the code.",
}


def report_limit_for(agent_type):
    # 🔴 explorer-max* = 6000, restul 2000 — docs/RECIPES.md «SubagentStop hook test»
    if isinstance(agent_type, str) and agent_type.startswith("explorer-max"):
        return THRESHOLDS["long_agent_report_explorer_max"]
    return THRESHOLDS["long_agent_report"]


def severity_of(code, scope, wasted):
    """Escalation moves a code up one step at most; a worker reading its own target does not."""
    sev = SEVERITY_BASE.get(code, "low")
    if code == "full_read_big_file" and scope.split("#")[0] in ("implementer", "implementer-complex", "implementer-max", "implementer-sonnet", "scripter", "scripter-complex"):
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

SESSION_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(?:s\d+|\d{4}|\d{6})-(.+)$")


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
    try:
        mistakes = int(data.get("mistakes"))
    except (TypeError, ValueError):
        mistakes = None
    return {"score": score, "note": str(data.get("note") or "").strip(),
            "project": str(data.get("project") or "").strip(),
            "ts": str(data.get("ts") or "").strip(),
            "advisor_score": clean_score(data.get("advisor_score")),
            "mistakes": mistakes}


def session_project(session):
    """The project as it appears in the session name (<day>-HHMM-<project>), not the slug dir."""
    m = SESSION_NAME_RE.match(session.get("name") or "")
    return m.group(1) if m else ""


def rating_matches(rating, session):
    if not rating["project"] or rating["project"] != session_project(session):
        return False
    started = session.get("started") or ""
    return bool(rating["ts"]) and bool(started) and rating["ts"] > started


def quality_of(rating):
    return {"score": rating["score"], "note": rating["note"], "rated_at": rating["ts"],
            "advisor_score": rating.get("advisor_score"),
            "mistakes": rating.get("mistakes")}


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
    # 🔴 cache_creation is the total; the 5m portion is retaxed at cache_write_5m — DECIZII «v1.8 — prețuri Fable 5.1»
    n5m = counts.get("cache_creation_5m", 0)
    if n5m:
        r_1h = float(rates.get("cache_write", 0.0))
        r_5m = float(rates.get("cache_write_5m", r_1h))
        total += n5m * (r_5m - r_1h) / 1_000_000.0
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


def is_image_block(b):
    if not isinstance(b, dict):
        return False
    if b.get("type") == "image":
        return True
    src = b.get("source")
    return isinstance(src, dict) and src.get("type") == "base64"


def result_chars(value):
    """Cost-weighted length of a tool_result: an image block counts IMAGE_CHARS, not its base64."""
    # 🔴 image = IMAGE_CHARS — PATTERNS «Image blocks in the analyzer»
    if not isinstance(value, list):
        return len(text_of(value))
    total = 0
    for b in value:
        if is_image_block(b):
            total += IMAGE_CHARS
        else:
            total += len(text_of([b]))
    return total


def zeros():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
            "cache_creation_5m": 0, "messages": 0}


def cc_5m(usage):
    cc = usage.get("cache_creation")
    return (cc.get("ephemeral_5m_input_tokens") or 0) if isinstance(cc, dict) else 0


def add_usage(acc, usage):
    acc["input"] += usage.get("input_tokens") or 0
    acc["output"] += usage.get("output_tokens") or 0
    acc["cache_read"] += usage.get("cache_read_input_tokens") or 0
    acc["cache_creation"] += usage.get("cache_creation_input_tokens") or 0
    acc["cache_creation_5m"] += cc_5m(usage)
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


def mtime_ts(path):
    try:
        return datetime.datetime.utcfromtimestamp(
            os.path.getmtime(path)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


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
    return ts, cwd


def project_of(cwd, jsonl_path):
    if isinstance(cwd, str) and cwd.strip("/"):
        return os.path.basename(cwd.rstrip("/"))
    slug = os.path.basename(os.path.dirname(jsonl_path))
    home = os.path.expanduser("~").replace("/", "-")
    if slug.startswith(home):
        slug = slug[len(home):]
    return slug.strip("-") or "session"


def session_id_of(jsonl_path):
    return os.path.basename(jsonl_path)[:-len(".jsonl")]


FORK_HOOK_NAME = "SessionStart:fork"
FORK_TAIL_BYTES = 262144


def _continued_in(path):
    """Id of the session this transcript was forked into, from its last continued-in line."""
    child = None
    for obj in read_lines(path):
        if obj.get("type") == "continued-in" and isinstance(obj.get("continuedInSessionId"), str):
            child = obj["continuedInSessionId"]
    return child


def _fork_parent(path):
    """Sibling transcript whose tail says it continued into this one."""
    directory = os.path.dirname(path) or "."
    needle = '"continuedInSessionId":"%s"' % session_id_of(path)
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".jsonl") or entry == os.path.basename(path):
            continue
        cand = os.path.join(directory, entry)
        try:
            with open(cand, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - FORK_TAIL_BYTES))
                tail = fh.read().decode("utf-8", "replace")
        except OSError:
            continue
        if needle in tail:
            return cand
    return None


def chain_origin(jsonl_path):
    """The transcript that owns the record: walk continued-in backwards from a fork."""
    path, seen = jsonl_path, {jsonl_path}
    while True:
        parent = _fork_parent(path)
        if not parent or parent in seen:
            return path
        seen.add(parent)
        path = parent


def fork_chain(jsonl_path):
    """[origin, fork, fork, ...] linked by continued-in; only files that exist."""
    chain, seen = [jsonl_path], {session_id_of(jsonl_path)}
    directory = os.path.dirname(jsonl_path) or "."
    while True:
        child = _continued_in(chain[-1])
        if not child or child in seen:
            return chain
        path = os.path.join(directory, child + ".jsonl")
        if not os.path.isfile(path):
            return chain
        seen.add(child)
        chain.append(path)


def _fork_start(path):
    """Line index of the SessionStart:fork hook; None when the fork carries no marker."""
    for i, obj in enumerate(read_lines(path)):
        att = obj.get("attachment")
        if isinstance(att, dict) and att.get("hookName") == FORK_HOOK_NAME:
            return i
    return None


def read_chain_lines(chain):
    """Origin in full, then each fork from its fork marker on: the head is a copy of the origin."""
    last_ts = None
    for i, path in enumerate(chain):
        # 🔴 without a cutoff, the fork's first ~100 messages get counted twice — PATTERNS «Resumed sessions»
        start = None if i == 0 else _fork_start(path)
        for j, obj in enumerate(read_lines(path)):
            if i and start is None:
                ts = obj.get("timestamp")
                if not (isinstance(ts, str) and last_ts and ts > last_ts):
                    continue
            elif start is not None and j < start:
                continue
            ts = obj.get("timestamp")
            if isinstance(ts, str) and (last_ts is None or ts > last_ts):
                last_ts = ts
            yield obj


def session_name(jsonl_path, ts=None, cwd=None, out_dir=None):
    """YYYY-MM-DD-HHMM-<project>, local start time; HHMMSS if that minute is another session."""
    # 🔴 the name does not depend on sibling files — PATTERNS «Session names»
    if ts is None and cwd is None:
        ts, cwd = first_meta(jsonl_path)
    day = local_day(ts)
    proj = project_of(cwd, jsonl_path)
    name = "%s-%s-%s" % (day, local_str(ts, "%H%M"), proj)
    if out_dir:
        taken = read_record(os.path.join(out_dir, name + ".json"))
        if taken and taken.get("session") not in (None, session_id_of(jsonl_path)):
            name = "%s-%s-%s" % (day, local_str(ts, "%H%M%S"), proj)
    return name


# ---------------------------------------------------------------- sessions

def session_files(jsonl_path, chain=None):
    """Main transcript plus the subagent transcripts of every link in its fork chain."""
    out = [(jsonl_path, None)]
    best = collections.OrderedDict()
    for main_path in (chain or [jsonl_path]):
        subdir = os.path.join(main_path[:-len(".jsonl")], "subagents")
        if not os.path.isdir(subdir):
            continue
        for name in sorted(os.listdir(subdir)):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(subdir, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            # 🔴 the same agent appears in both the origin dir and the fork's — PATTERNS «Resumed sessions»
            if name in best and best[name][1] >= size:
                continue
            best[name] = (path, size)
    for name, (path, _size) in best.items():
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
            found = [os.path.join(p, name) for name in sorted(os.listdir(p))
                     if name.endswith(".jsonl") and os.path.isfile(os.path.join(p, name))]
            # 🔴 `<uuid>/` holds only subagents; the session is the sibling `<uuid>.jsonl` — PATTERNS «Session folder vs session file»
            if not found and os.path.isfile(p.rstrip("/\\") + ".jsonl"):
                found = [p.rstrip("/\\") + ".jsonl"]
            targets.extend(found)
        elif os.path.isfile(p):
            targets.append(p)
        else:
            print("skip (inexistent): %s" % p, file=sys.stderr)
    return targets


COMMENT_CODE_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".astro", ".css", ".scss",
                    ".html", ".py", ".sh", ".fish", ".yml", ".yaml", ".toml"}
COMMENT_HASH_EXT = {".py", ".sh", ".fish", ".yml", ".yaml", ".toml"}
COMMENT_SLASH_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".astro", ".css", ".scss"}
COMMENT_HTML_EXT = {".html", ".astro"}
LICENSE_RE = re.compile(r"SPDX-License-Identifier|Copyright")


def comment_flags(text, ext):
    """mirror of hooks/comentarii-cod.sh - one bool per line: is it a comment line?"""
    lines = text.split("\n")
    slash, html = ext in COMMENT_SLASH_EXT, ext in COMMENT_HTML_EXT
    hashy = ext in COMMENT_HASH_EXT
    out, in_block, in_html = [], False, False
    for i, raw in enumerate(lines):
        st = raw.strip()
        if in_block:
            out.append(True)
            in_block = "*/" not in st
            continue
        if in_html:
            out.append(True)
            in_html = "-->" not in st
            continue
        if i < 5 and LICENSE_RE.search(st):
            out.append(False)
            continue
        is_c = False
        if slash and st.startswith("//"):
            is_c = True
        elif slash and (st.startswith("/*") or st.startswith("{/*")):
            is_c = True
            in_block = "*/" not in (st[3:] if st.startswith("{/*") else st[2:])
        elif html and st.startswith("<!--"):
            is_c = True
            in_html = "-->" not in st[4:]
        elif hashy and st.startswith("#") and not st.startswith("#!"):
            is_c = True
        out.append(is_c)
    return lines, out


def comment_bloat(path, new, old):
    """mirror of hooks/comentarii-cod.sh - None, or the stats of the comments this call added."""
    p = path or ""
    ext = os.path.splitext(p)[1].lower()
    if (ext not in COMMENT_CODE_EXT or "/.claude/plans/" in p
            or "/docs/" in p or p.startswith("docs/")):
        return None
    new_lines, new_c = comment_flags(new or "", ext)
    old_lines, old_c = comment_flags(old or "", ext)
    pool = collections.Counter(old_lines[i].strip() for i, c in enumerate(old_c)
                               if c and old_lines[i].strip())
    added = []
    for i, c in enumerate(new_c):
        st = new_lines[i].strip()
        if not c or not st:
            continue
        if pool[st] > 0:
            pool[st] -= 1
            continue
        added.append(i)
    if not added:
        return None
    pool_all = collections.Counter(x.strip() for x in old_lines if x.strip())
    lines_added = 0
    for st in (x.strip() for x in new_lines):
        if not st:
            continue
        if pool_all[st] > 0:
            pool_all[st] -= 1
            continue
        lines_added += 1
    aset, max_block, run = set(added), 0, 0
    for i in range(len(new_lines)):
        run = run + 1 if i in aset else 0
        max_block = max(max_block, run)
    long_line = max([len(new_lines[i].rstrip()) for i in added] + [0])
    ratio_hit = (lines_added >= THRESHOLDS["comment_min_added"]
                 and len(added) / float(lines_added) > THRESHOLDS["comment_ratio"])
    if not (max_block >= THRESHOLDS["comment_block_lines"]
            or long_line > THRESHOLDS["comment_long_line"] or ratio_hit):
        return None
    return {"path": path or "?", "max_block": max_block,
            "comment_added": len(added), "lines_added": lines_added,
            "chars": sum(len(new_lines[i].strip()) for i in added)}


EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
FILES_CHANGED_RE = re.compile(r"(\d+) files? changed")


def new_doc(path, label):
    return {
        "path": path, "label": label,
        "edit_calls": 0, "files_changed": None,
        "resumed_from": None, "inherited_msgs": 0, "own_msgs": 0,
        "first_ts": None, "last_ts": None, "last_assistant_ts": None,
        "first_prompt_ts": None, "cwd": None,
        "groups": collections.OrderedDict(),
        "calls": [], "turn_ms": 0, "turns": 0, "slash": [],
        "user_prompts": 0, "sendmessages": 0, "sendmessage_ts": [],
        "sendmessage_calls": [], "agent_ids": {}, "plan_edits": [],
        "results": [], "agent_launches": [], "agent_results": {},
        "reads": collections.Counter(), "read_chars": collections.Counter(),
        "read_events": [],
        "written": set(), "reread_own_write": [],
        "code_writes": [], "comment_writes": [],
        "max_turns_hit": False, "max_turns_ids": set(),
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
AGENT_ID_RE = re.compile(r"agentId:\s*([A-Za-z0-9_-]+)")
TASK_ID_RE = re.compile(r"<task-id>\s*([A-Za-z0-9_-]+)\s*</task-id>")


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


_PARENT_UUIDS = {}


def parent_uuids(path, sid):
    """Uuids from `<dir(path)>/<sid>.jsonl`; empty set if the parent is missing."""
    parent = os.path.join(os.path.dirname(os.path.abspath(path)), sid + ".jsonl")
    ids = _PARENT_UUIDS.get(parent)
    if ids is None:
        ids = set()
        try:
            with open(parent, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"uuid"' not in line:
                        continue
                    try:
                        u = json.loads(line).get("uuid")
                    except ValueError:
                        continue
                    if isinstance(u, str):
                        ids.add(u)
        except OSError:
            pass
        _PARENT_UUIDS[parent] = ids
    return ids


def parse_file(path, label, tool_names, tool_inputs, chain=None):
    """One pass over a transcript; usage grouping identical to the original analyze()."""
    doc = new_doc(path, label)
    groups = doc["groups"]
    chain = chain or [path]
    own_ids = {session_id_of(p) for p in chain}
    last_human = "user"
    # 🔴 a turn with a live async agent is structural, not waste — DECIZII «Narration turns: avoidable»
    live_agents, notified, revived = set(), collections.Counter(), set()
    pending_residual = False
    for obj in read_chain_lines(chain):
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
                raw = msg.get("content")
                raw = raw if isinstance(raw, str) else text_of(raw)
                pending_residual = False
                for tid in TASK_ID_RE.findall(raw or ""):
                    if notified[tid] and tid not in revived:
                        pending_residual = True
                    notified[tid] += 1
                    revived.discard(tid)
                    live_agents.discard(tid)
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
                        doc["agent_ids"][b["tool_use_id"]] = tur["agentId"]
                        break

        for b in blocks(msg):
            bt = b.get("type")
            if bt == "tool_use":
                name = b.get("name") or "?"
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if isinstance(b.get("id"), str):
                    tool_names[b["id"]] = name
                    tool_inputs[b["id"]] = inp
                if name in EDIT_TOOLS:
                    doc["edit_calls"] += 1
                if name == "Read":
                    fp = inp.get("file_path")
                    if isinstance(fp, str) and fp:
                        doc["reads"][fp] += 1
                        doc["read_events"].append(
                            ("read", fp, slice_of(inp)[0], slice_of(inp)[1]))
                        if fp in doc["written"]:
                            doc["reread_own_write"].append(fp)
                elif name == "Bash":
                    # 🔴 Bash lands in the same stream as the reads — PATTERNS «Reread after regeneration»
                    cmd = inp.get("command")
                    if isinstance(cmd, str) and cmd:
                        doc["read_events"].append(("bash", cmd, None, None))
                elif name in ("Write", "Edit"):
                    fp = inp.get("file_path")
                    body = inp.get("content") or inp.get("new_string") or ""
                    # 🔴 hook uses git show HEAD:, analyzer has no HEAD - Write counted only for unseen paths
                    seen_before = name == "Write" and (fp in doc["reads"] or fp in doc["written"])
                    if isinstance(fp, str) and fp:
                        doc["written"].add(fp)
                    if isinstance(fp, str) and isinstance(body, str) and not seen_before:
                        cb = comment_bloat(fp, body, inp.get("old_string") or "")
                        if cb:
                            doc["comment_writes"].append(cb)
                    is_plan = isinstance(fp, str) and "/.claude/plans/" in fp
                    if is_plan and isinstance(ts, str):
                        doc["plan_edits"].append(ts)
                    if (isinstance(body, str) and not is_plan
                            and body.count("\n") + 1 > THRESHOLDS["fable_code_lines"]):
                        doc["code_writes"].append({"path": fp or "?",
                                                   "lines": body.count("\n") + 1})
                elif name == "TaskStop":
                    live_agents.discard(inp.get("task_id"))
                elif name == "SendMessage":
                    to = inp.get("to")
                    if isinstance(to, str) and to:
                        live_agents.add(to)
                        revived.add(to)
                    doc["sendmessages"] += 1
                    if isinstance(ts, str):
                        doc["sendmessage_ts"].append(ts)
                    doc["sendmessage_calls"].append({"id": b.get("id"), "to": to, "at": ts})
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
                        "debugging": "debugging" in (inp.get("prompt") or "").lower(),
                        "at": ts,
                    })
            elif bt == "tool_result":
                body = text_of(b.get("content"))
                tuid = b.get("tool_use_id")
                for m in FILES_CHANGED_RE.finditer(body or ""):
                    n_files = int(m.group(1))
                    if doc["files_changed"] is None or n_files > doc["files_changed"]:
                        doc["files_changed"] = n_files
                if (isinstance(tuid, str) and tuid in doc["agent_call_ids"]
                        and not obj.get("isSidechain")
                        and ASYNC_LAUNCH_RE.search(body)):
                    aid = AGENT_ID_RE.search(body)
                    if aid:
                        live_agents.add(aid.group(1))
                        doc["agent_ids"].setdefault(tuid, aid.group(1))
                if (label is None and isinstance(tuid, str)
                        and tuid in doc["agent_call_ids"]
                        and MAX_TURNS_RE.search(body[:4000])):
                    doc["max_turns_hit"] = True
                    doc["max_turns_ids"].add(tuid)
                doc["results"].append({
                    "tool_use_id": b.get("tool_use_id"),
                    "chars": result_chars(b.get("content")),
                    "lines": body.count("\n") + 1 if body else 0,
                    "at": ts,
                })

        if kind != "assistant":
            continue
        if isinstance(ts, str):
            if doc["last_assistant_ts"] is None or ts > doc["last_assistant_ts"]:
                doc["last_assistant_ts"] = ts
        inherited = False
        if label is None:
            sid = obj.get("session_id") or obj.get("sessionId")
            # 🔴 inherited = foreign session_id AND uuid copied from the parent — PATTERNS «sessionId vs session_id in jsonl»
            if (isinstance(sid, str) and sid not in own_ids
                    and obj.get("uuid") in parent_uuids(path, sid)):
                inherited = True
                doc["inherited_msgs"] += 1
                if doc["resumed_from"] is None:
                    doc["resumed_from"] = sid
            else:
                doc["own_msgs"] += 1
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
                "agents_live": bool(live_agents),
                "residual_poll": pending_residual,
                "inherited": inherited,
                "effort": obj.get("effort"),
                "thinking": ((usage.get("output_tokens_details") or {}).get("thinking_tokens")
                             if isinstance(usage.get("output_tokens_details"), dict) else 0),
            }
            pending_residual = False
        else:
            grp["usage"]["output_tokens"] = max(grp["usage"].get("output_tokens") or 0,
                                                usage.get("output_tokens") or 0)
            det = usage.get("output_tokens_details")
            if isinstance(det, dict):
                grp["thinking"] = max(grp.get("thinking") or 0,
                                      det.get("thinking_tokens") or 0)
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
        if not grp.get("inherited"):
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
            "cache_creation_5m": cc_5m(usage),
            "output": usage.get("output_tokens") or 0,
            "effort": grp.get("effort"),
            "thinking": grp.get("thinking") or 0,
            "inherited": bool(grp.get("inherited")),
            "has_tool_use": bool(grp["tools"]),
            "prev_human": grp.get("prev_human") or "user",
            "agents_live": bool(grp.get("agents_live")),
            "residual_poll": bool(grp.get("residual_poll")),
            "asks_user": "".join(grp["texts"]).strip().endswith("?"),
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


PLANS_DIR = "/.claude/plans/"
BASH_WRITE_RE = re.compile(r"<<|python3?\s+-(?:\s|$)")
SRC_EXT = r"(?:js|ts|mjs|astro|css|py|sh)"
REDIRECT_RE = re.compile(r"(?:>>?|tee\s+(?:-a\s+)?)\s*['\"]?([^\s'\";|&]+\.%s)\b" % SRC_EXT)
PY_WRITE_RE = re.compile(r"open\([^)]*['\"][wa]|\.write\(|write_text\(")
SRC_PATH_RE = re.compile(r"[\w./~$-]*\.%s\b" % SRC_EXT)
# 🔴 a helper written into the scratchpad is not a source edit — DECIZII «v1.5 — 30.08.2026»
TMP_PATH_RE = re.compile(r"^/tmp/|scratchpad|/dosar/")


def bash_writes_source(cmd):
    """Bash call that writes a project source file (heredoc / python3 - ), not a temp helper."""
    if not BASH_WRITE_RE.search(cmd):
        return False
    targets = REDIRECT_RE.findall(cmd)
    if PY_WRITE_RE.search(cmd):
        targets += SRC_PATH_RE.findall(cmd)
    return any(t and not TMP_PATH_RE.search(t) for t in targets)


LATE_READ_CMD_RE = re.compile(r"\b(sed|cat|grep|head|tail|awk)\b")
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def first_edit_block(doc, tool_inputs, chars_by_id):
    """Where the worker first wrote: call index, context there, reading done before."""
    idx = reads = chars = 0
    for c in doc["calls"]:
        for name, tid in zip(c["tool_names"], c["tool_ids"]):
            idx += 1
            if name in WRITE_TOOLS:
                return {"call": idx, "ctx": c["ctx"], "read_calls": reads,
                        "read_chars": chars}
            inp = tool_inputs.get(tid) or {}
            if name == "Read" or (name == "Bash"
                                  and LATE_READ_CMD_RE.search(inp.get("command") or "")):
                reads += 1
                chars += chars_by_id.get(tid, 0)
    return None


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


def slice_of(inp):
    off, lim = inp.get("offset"), inp.get("limit")
    off = int(off) if isinstance(off, (int, float)) else None
    lim = int(lim) if isinstance(lim, (int, float)) else None
    return off, lim


READONLY_CMDS = ("cat", "grep", "rg", "ls", "wc", "head", "tail", "diff", "git",
                 "stat", "identify", "file", "find")


SKIP_CMDS = ("cd", "pushd", "popd", "set", "export", "true", "sudo", "time")
SEP_RE = re.compile(r";|&&|\|\||\||\n")


def first_cmd(segment):
    # 🔴 cd/env prefixes hide the real command — PATTERNS «Reread after regeneration»
    tokens = segment.strip().split()
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens.pop(0)
    return os.path.basename(tokens[0]) if tokens else ""


def readonly_cmd(command):
    for seg in SEP_RE.split(command):
        name = first_cmd(seg)
        if name and name not in SKIP_CMDS:
            return name in READONLY_CMDS
    return True


def cmd_touches(command, path):
    base = os.path.basename(path)
    if not base:
        return False
    return re.search(r"(?<![\w.-])%s(?![\w.-])" % re.escape(base), command) is not None


def regenerated(command, paths):
    # 🔴 only the segment that names the file decides, not the whole line — PATTERNS «Reread after regeneration»
    out = []
    for path in paths:
        for seg in SEP_RE.split(command):
            if cmd_touches(seg, path) and not readonly_cmd(seg):
                out.append(path)
                break
    return out


def read_counts(doc):
    """Reads per path, restarting the count when a Bash command regenerates the file."""
    running, best = collections.Counter(), collections.Counter()
    for ev in doc["read_events"]:
        if ev[0] == "bash":
            for path in regenerated(ev[1], list(running)):
                running[path] = 0
            continue
        running[ev[1]] += 1
        best[ev[1]] = max(best[ev[1]], running[ev[1]])
    return best


def reread_block(doc):
    # 🔴 distinct slices of one file are not a reread — DECIZII «v1.4.1 — 30.08.2026»
    redundant = collections.Counter()
    seen, sliced, full = set(), set(), set()
    for ev in doc["read_events"]:
        if ev[0] == "bash":
            for path in regenerated(ev[1], full | sliced):
                full.discard(path)
                sliced.discard(path)
                seen = {k for k in seen if k[1] != path}
            continue
        key, path, off, lim = ev, ev[1], ev[2], ev[3]
        whole = off is None and lim is None
        # 🔴 whole read after slices, or any slice after a whole read — hooks/read-mare.sh:96-100
        if key in seen or (whole and path in sliced) or (not whole and path in full):
            redundant[path] += 1
        else:
            seen.add(key)
        if whole:
            full.add(path)
        else:
            sliced.add(path)
    out = []
    for path, n in redundant.most_common():
        total = doc["read_chars"][path]
        chars = total // (doc["reads"][path] or 1) if total else 0
        out.append({"path": path, "reads": n + 1, "chars": chars,
                    "wasted_chars": chars * n})
    return out


# matches the Romanian wording of agent reports in the author's transcripts
FIX_MARK_RE = re.compile(r"(-fix|\bfix\b|repara[țt]ii|\bre-run\b|\bretrimitere\b|\bre-)", re.I)


def brief_key(desc):
    """Same brief re-sent: everything from the first fix marker on is not a new brief."""
    s = (desc or "").strip()
    m = re.match(r"(?i)^re-\s*(?:run|send|trimit\w*)?\s*", s)
    if m:
        s = s[m.end():]
    m = FIX_MARK_RE.search(s)
    if m:
        s = s[:m.start()]
    return " ".join(s.lower().split()).strip(" -–—:")


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


# 🔴 doar mutatorii reali, ca nume de comandă — PATTERNS «Hook counts lines, analyzer counts chars»
BATCH_MUTATING_RE = re.compile(
    r"(?:^|[;&|]|\$\()\s*(?:sed +-i|rm|mv|cp|mkdir|touch|chmod|tee)\b"
    r"|\bgit +(?:add|commit|push|checkout|stash|reset|rebase|merge)\b"
    r"|(?<![0-9&])>(?!&)\s*(?!/dev/null)\S")


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

    reads, reports = [], []
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
            item = {"cmd": " ".join(cmd.split())[:60], "chars": r["chars"]}
            # 🔴 advisor plans and refine reports are read legitimately, 0 tokens — DECIZII «waste: citiri legitime exceptate»
            (reports if only_report_paths(cmd) else reads).append(item)
    reads.sort(key=lambda r: -r["chars"])
    reports.sort(key=lambda r: -r["chars"])
    emit_many(flags, "main_read_files", scope, reads,
              lambda r: "`%s` returned %s chars" % (r["cmd"], fmt(r["chars"])),
              lambda r: r["chars"] / 4.0)
    emit_many(flags, "main_read_report", scope, reports,
              lambda r: "`%s` returned %s chars" % (r["cmd"], fmt(r["chars"])),
              lambda r: 0)

    launch_ts = [l["at"] for l in doc["agent_launches"] if isinstance(l.get("at"), str)]
    first_launch = min(launch_ts) if launch_ts else "9"  # 🔴 no Agent at all = every read counts — DECIZII «v1.5 — 30.08.2026»
    before = [r for r in rows if r["tool"] in ("Bash", "Read")
              and isinstance(r.get("at"), str) and r["at"] < first_launch]
    pre_chars = sum(r["chars"] for r in before)
    if pre_chars > THRESHOLDS["main_read_before_agent"]:
        flags.append(flag("main_read_before_first_agent", scope,
                          "%s chars of Bash/Read results in main before the first agent "
                          "(%d results)" % (fmt(pre_chars), len(before)),
                          {"chars": pre_chars, "results": len(before)},
                          pre_chars / 4.0))

    # an answer to the user is not narration; after a launch the turn has to end anyway
    narr = [c for c in calls if not c["has_tool_use"]
            and c["text_chars"] < THRESHOLDS["narration_text_chars"]
            and c["prev_human"] != "user"]
    last_call = calls[-1] if calls else None

    def inherent(c):
        # 🔴 only a note with nothing running is waste — DECIZII «Narration turns: avoidable»
        return (not c.get("residual_poll")
                and (c["prev_human"] == "agent_result" or c.get("agents_live")
                     or c.get("asks_user") or c is last_call))

    structural = [c for c in narr if inherent(c)]
    avoidable = [c for c in narr if not inherent(c)]
    residual = [c for c in avoidable if c.get("residual_poll")]
    narr_cache = sum(c["cache_read"] for c in narr)
    avoid_cache = sum(c["cache_read"] for c in avoidable)
    if len(avoidable) > THRESHOLDS["narration_avoidable_calls"]:
        flags.append(flag("narration_turns", scope,
                          "%d avoidable narration calls (%s cache_read re-sent, "
                          "%d of them residual_poll) · %d structural (agent live, "
                          "launch, question or last turn)"
                          % (len(avoidable), tok(avoid_cache), len(residual),
                             len(structural)),
                          {"calls": len(narr), "avoidable": len(avoidable),
                           "residual_poll": len(residual),
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
        # 🔴 a mutating command makes the chain dependent — DECIZII «v1.8.1 — batchable exclude lanțuri dependente»
        mutating = any(BATCH_MUTATING_RE.search(
                       (input_by_id.get(t) or {}).get("command") or "")
                       for c in run for t in c["tool_ids"] if t)
        if len(run) >= THRESHOLDS["batchable_calls"] and not mutating:
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
        "narration_residual_poll": len(residual),
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
            if not base.endswith(IMG_EXT):
                continue
            # 🔴 size decides, not the -mic name — PATTERNS «Image blocks in the analyzer»
            try:
                size = os.path.getsize(os.path.expanduser(path))
            except OSError:
                continue
            if size > IMG_BIG_BYTES:
                imgs.append({"path": path, "reads": n, "bytes": size})
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
        trs = [{"path": (r["input"] or {}).get("file_path") or "?",
                "lines": r["lines"], "chars": r["chars"]}
               for r in rows
               if r["tool"] == "Read"
               and "/tool-results/" in ((r["input"] or {}).get("file_path") or "")]
        trs.sort(key=lambda r: -r["chars"])
        emit_many(flags, "tool_results_read", scope, trs,
                  lambda r: "%s read %s (%d lines)" % (scope, os.path.basename(r["path"]),
                                                       r["lines"]),
                  lambda r: r["chars"] / 4.0)
        seen = []
        for path in doc["reread_own_write"]:
            if path not in seen:
                seen.append(path)
        emit_many(flags, "agent_reread_own_write", scope,
                  [{"path": p} for p in seen],
                  lambda r: "%s re-read after writing it" % os.path.basename(r["path"]),
                  lambda r: 0)
        plans = []
        # 🔴 advisor plans and refine reports are read legitimately, 0 tokens — DECIZII «waste: citiri legitime exceptate»
        for r in rows if scope.split("#")[0] != "advisor" else []:
            inp = r["input"] or {}
            fp = inp.get("file_path") or ""
            if (r["tool"] == "Read" and PLANS_DIR in fp and fp.endswith(".md")
                    and not inp.get("offset") and not inp.get("limit")):
                plans.append({"path": fp, "chars": r["chars"]})
        plans.sort(key=lambda r: -r["chars"])
        emit_many(flags, "agent_read_plan_whole", scope, plans,
                  lambda r: "%s read whole (%s chars)"
                            % (os.path.basename(r["path"]), fmt(r["chars"])),
                  lambda r: r["chars"] / 4.0)
        if not doc["written"]:
            heredocs = [r for r in rows if r["tool"] == "Bash"
                        and bash_writes_source((r["input"] or {}).get("command") or "")]
            if len(heredocs) >= THRESHOLDS["edit_via_bash_calls"]:
                flags.append(flag("edit_via_bash", scope,
                                  "%d Bash writes into source files, 0 Edit/Write"
                                  % len(heredocs), {"calls": len(heredocs)}, 0))
    cw = doc["comment_writes"]
    if cw:
        files = sorted(set(os.path.basename(w["path"]) for w in cw))
        shown = ", ".join(files[:THRESHOLDS["flag_examples"]])
        if len(files) > THRESHOLDS["flag_examples"]:
            shown += ", +%d more" % (len(files) - THRESHOLDS["flag_examples"])
        flags.append(flag("comment_bloat", scope,
                          "%d edits added comment blocks (max %d lines) in %s"
                          % (len(cw), max(w["max_block"] for w in cw), shown),
                          {"edits": len(cw), "files": files,
                           "comment_lines": sum(w["comment_added"] for w in cw)},
                          sum(w["chars"] for w in cw) / 4.0))
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
    # 🔴 without input volume in main the percentage does not exist (it is not 0) — PATTERNS «Percentages with a missing denominator»
    pm["wasted_pct_of_main_input"] = (round(100.0 * wasted / main_input, 1)
                                      if main_input > 0 else None)
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
    r_cw5 = float(rates.get("cache_write_5m", r_cw))

    def cw_cost(call, tokens):
        # 🔴 the 5m portion is taxed at r_cw5, proportional to the call — DECIZII «v1.8 — prețuri Fable 5.1»
        total = call.get("cache_creation") or 0
        if not total or not tokens:
            return 0.0
        share5 = min(call.get("cache_creation_5m", 0), total) * tokens / total
        return share5 * r_cw5 + (tokens - share5) * r_cw
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
                  + c["cache_read"] * r_cr + cw_cost(c, c["cache_creation"])) / 1e6
    boot_removed = 0
    for r in runs:
        boot_removed += r["boot"]
        for i, c in enumerate(r["calls"]):
            inp = 0 if i == 0 else c["input"]
            ccr = 0 if i == 0 else c["cache_creation"]
            crd = c["cache_read"] if i == 0 else max(c["cache_read"] - r["boot"], 0)
            floor += (c["output"] * r_out + inp * r_in + crd * r_cr
                      + cw_cost(c, ccr)) / 1e6

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
                      + cw_cost(c, cc_net)) / 1e6
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


# ---------------------------------------------------------------- v1.7 (effort phases)

EFFORT_KEYS = ("high", "medium", "low", "unknown")
EFFORT_BASELINE_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "effort-baseline.json")
BASELINE_MODEL = "claude-fable-5-1"
ADVISOR_TYPE = "advisor"
VERDICT_RE = re.compile(r"VERDICT\s*[:\-]\s*(.+)")
ABATERI_RE = re.compile(r"ABATERI\s*\((\d+)\)")
TRIGGER_B_RE = re.compile(r"hooks/|settings\.json|migr", re.I)
ADVISOR_REASON_RE = re.compile(r"^\s*advisor\s*:\s*(.+)$", re.M | re.I)
# matches the Romanian wording of agent reports in the author's transcripts
ADVISOR_HEADER_RE = re.compile(r"^\s*(?:VERDICT|CHANGES|SCHIMB\w*|RISK|RISC|EDGE|MARGIN\w*|"
                               r"IMPROVEMENTS|[IÎ]MBUN\w*|NEED|NEVOI\w*)\s*:", re.I)
CHANGES_RE = re.compile(r"^\s*(?:CHANGES|SCHIMB\w*)\s*:", re.I)
# matches the Romanian wording of agent reports in the author's transcripts
IMPROVE_RE = re.compile(r"^\s*(?:IMPROVEMENTS|[IÎ]MBUN\w*)\s*:", re.I)
V17_VERSION_PREFIX = "v1.7"


def median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def load_effort_baseline(path):
    """Corpus medians for the high turns; missing or malformed -> no counterfactual."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("median_output_tokens") is None:
        return None
    return data


def build_effort_baseline(directory, out_path, model=BASELINE_MODEL, effort="high"):
    """Median output/thinking over the level-1 transcripts' main turns run at one effort."""
    if not os.path.isdir(directory):
        print("not a directory: %s" % directory, file=sys.stderr)
        return 2
    outs, thinks, line_outs = [], [], []
    # 🔴 a resumed session copies the parent's turns: dedupe across the whole corpus, not per file — PATTERNS «Resumed sessions»
    seen = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        for obj in read_lines(os.path.join(directory, name)):
            if obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            if obj.get("effort") != effort:
                continue
            msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            if msg.get("model") != model:
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            det = usage.get("output_tokens_details")
            det = det if isinstance(det, dict) else {}
            key = msg.get("id") or obj.get("uuid")
            line_outs.append(usage.get("output_tokens") or 0)
            prev = seen.get(key) or (0, 0)
            seen[key] = (max(prev[0], usage.get("output_tokens") or 0),
                         max(prev[1], det.get("thinking_tokens") or 0))
    for o, t in seen.values():
        outs.append(o)
        thinks.append(t)
    # 🔴 a turn = one message.id, not one assistant line — PATTERNS «Effort baseline: turns, not lines»
    data = {
        "model": model, "effort": effort, "n": len(outs),
        "median_output_tokens": median(outs), "median_thinking_tokens": median(thinks),
        "n_assistant_lines": len(line_outs),
        "median_output_tokens_per_line": median(line_outs),
        "built_at": datetime.datetime.now(datetime.timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_dir": directory,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("effort-baseline: n=%d, median output %s, median thinking %s -> %s"
          % (data["n"], data["median_output_tokens"], data["median_thinking_tokens"], out_path),
          file=sys.stderr)
    return 0


def effort_of(call):
    e = call.get("effort")
    return e if e in ("high", "medium", "low") else "unknown"


def turn_cost(call, pricing):
    # 🔴 inherited turns were billed to the parent session — PATTERNS «Resumed sessions»
    if call.get("inherited"):
        return 0.0
    return cost_of({"input": call["input"], "output": call["output"],
                    "cache_read": call["cache_read"],
                    "cache_creation": call["cache_creation"],
                    "cache_creation_5m": call.get("cache_creation_5m", 0)},
                   rates_for(pricing, call["model"]))


EMPTY_ITEM_RE = re.compile(r"^(?:niciuna|niciun\w*|nimic|none|n/?a|-{1,3}|—|\.)$", re.I)
# an item starts with a bullet or a number; a section with no marker at all falls back to lines
ITEM_START_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s*)")


def advisor_section_count(text, header_re):
    """Items under one header of the advisor's fixed format, up to the next header."""
    tail_item, lines, started = 0, [], False
    for raw in (text or "").splitlines():
        if header_re.match(raw):
            started = True
            tail = raw.split(":", 1)[1].strip() if ":" in raw else ""
            if tail and not EMPTY_ITEM_RE.match(tail):
                tail_item = 1
            continue
        if not started:
            continue
        if ADVISOR_HEADER_RE.match(raw):
            break
        line = raw.strip()
        if line and not EMPTY_ITEM_RE.match(line):
            lines.append(line)
    marked = [l for l in lines if ITEM_START_RE.match(l)]
    return tail_item + (len(marked) if marked else len(lines))


def v17_block(main_doc, workers, docs_by_scope, tool_inputs, pricing, version,
              flags, total_cost_usd):
    """The v1.7 numbers: effort phases, plan lag, advisor, low phase. (block, new flags)."""
    new_flags = []
    all_main = [c for c in main_doc["calls"] if not c["side"]]
    # 🔴 inherited turns were billed to the parent session — PATTERNS «Resumed sessions»
    turns = [c for c in all_main if not c.get("inherited")]
    inherited_turns = len(all_main) - len(turns)
    if not turns:
        return None, new_flags
    is_v17 = str(version or "").startswith(V17_VERSION_PREFIX)

    counts, out_tok, think_tok, tcalls = (collections.Counter() for _ in range(4))
    cost = collections.defaultdict(float)
    runs = []
    pos_of_tool, exit_pos, enter_pos = {}, [], []
    for i, c in enumerate(turns):
        e = effort_of(c)
        counts[e] += 1
        out_tok[e] += c["output"]
        think_tok[e] += c.get("thinking") or 0
        tcalls[e] += len(c["tool_names"])
        cost[e] += turn_cost(c, pricing)
        if runs and runs[-1]["effort"] == e:
            runs[-1]["turns"] += 1
            runs[-1]["to"] = i
            runs[-1]["tool_calls"] += len(c["tool_names"])
        else:
            runs.append({"effort": e, "turns": 1, "from": i, "to": i,
                         "tool_calls": len(c["tool_names"])})
        for name, tid in zip(c["tool_names"], c["tool_ids"]):
            if tid:
                pos_of_tool[tid] = i
            if name == "ExitPlanMode":
                exit_pos.append((i, tid))
            elif name == "EnterPlanMode":
                enter_pos.append(i)

    low_pos = [i for i, c in enumerate(turns) if effort_of(c) == "low"]
    lags = []
    for i, _tid in exit_pos:
        after = [j for j in low_pos if j > i]
        lags.append(after[0] - i - 1 if after else None)
    approved = exit_pos[0][0] if exit_pos else None
    mismatch = None
    if is_v17 and approved is not None:
        mismatch = sum(1 for j, c in enumerate(turns)
                       if (j > approved and effort_of(c) != "low")
                       or (j < approved and effort_of(c) != "medium"))

    # ---- advisor
    launches = main_doc["agent_launches"]
    adv_launches = [l for l in launches if l["type"] == ADVISOR_TYPE]
    adv_ids = set()
    for l in adv_launches:
        aid = main_doc["agent_ids"].get(l["tool_use_id"])
        if aid:
            adv_ids.add(aid)
    adv_sm = [sm for sm in main_doc["sendmessage_calls"] if sm.get("to") in adv_ids]
    adv_workers = [w for w in workers if w["type"] == ADVISOR_TYPE]
    adv_text = "\n".join((docs_by_scope.get(w["scope"]) or {}).get("final_text") or ""
                         for w in adv_workers)
    vm = VERDICT_RE.search(adv_text)
    # 🔴 the first report, not the last: round 2 would swallow the edits between reports — DECIZII «v1.7 — advisor + efort pe faze»
    adv_ends = [w["ended"] for w in adv_workers if w.get("ended")]
    adv_end = min(adv_ends) if adv_ends else None
    reason = None
    for grp in main_doc["groups"].values():
        if grp.get("side") or reason:
            continue
        for t in grp.get("texts") or []:
            rm = ADVISOR_REASON_RE.search(t or "")
            if rm:
                reason = rm.group(1).strip()[:200]
                break
    advisor = {
        "calls": len(adv_launches),
        "sendmessages": len(adv_sm),
        "cost_usd": round(sum(w["cost_usd"] for w in adv_workers), 4),
        "share_pct": round(100.0 * sum(w["cost_usd"] for w in adv_workers)
                           / (total_cost_usd or 1.0), 1),
        "reason_line": reason,
        "verdict": vm.group(1).strip()[:60] if vm else None,
        "n_schimbari": advisor_section_count(adv_text, CHANGES_RE),
        "n_imbunatatiri": advisor_section_count(adv_text, IMPROVE_RE),
        "n_scope_plus": sum(1 for ln in adv_text.splitlines() if "scope+" in ln.lower()),
        "plan_edits_after": sum(1 for t in main_doc["plan_edits"]
                                if adv_end and isinstance(t, str) and t > adv_end),
        "rounds": len(adv_launches) + len(adv_sm),
        "score": None,
    }

    # ---- low phase
    low_start = turns[low_pos[0]]["at"] if low_pos else None
    worker_at = {w["scope"]: (w.get("launched_at") or w.get("started")) for w in workers}
    low_flags = []
    if low_start:
        for f in flags:
            ev = f.get("evidence")
            at = ev.get("at") if isinstance(ev, dict) else None
            at = at or worker_at.get(f["scope"])
            if isinstance(at, str) and at >= low_start:
                low_flags.append(f["code"])
    seen_briefs, reruns = set(), 0
    for w in workers:
        if not (w["type"].startswith("implementer") or w["type"].startswith("scripter")):
            continue
        key = brief_key(w["description"]) or w["scope"]
        at = w.get("launched_at") or w.get("started")
        if key in seen_briefs and low_start and isinstance(at, str) and at >= low_start:
            reruns += 1
        seen_briefs.add(key)
    audits = [(w, (docs_by_scope.get(w["scope"]) or {}).get("final_text") or "")
              for w in workers if w["type"] == "auditor"]
    abateri_total, audit_ok = 0, 0
    for _w, txt in audits:
        found = [int(x) for x in ABATERI_RE.findall(txt)]
        abateri_total += sum(found)
        if not sum(found) and re.search(r"\bOK\b", txt):
            audit_ok += 1
    low_phase = {
        "flags": sorted(collections.Counter(low_flags).items()),
        "sendmessage_resends": sum(1 for sm in main_doc["sendmessage_calls"]
                                   if low_start and isinstance(sm.get("at"), str)
                                   and sm["at"] >= low_start),
        "reruns": reruns,
        "audit_abateri_total": abateri_total,
        "audit_ok": audit_ok,
        "mistakes": None,
    }

    # ---- flags of the version itself
    adv_events = sorted([w.get("launched_at") or w.get("started") for w in adv_workers
                         if (w.get("launched_at") or w.get("started"))]
                        + [sm["at"] for sm in adv_sm if isinstance(sm.get("at"), str)])
    impl_events = sorted([w.get("launched_at") or w.get("started") for w in workers
                          if (w["type"].startswith("implementer")
                              or w["type"].startswith("scripter"))
                          and (w.get("launched_at") or w.get("started"))]
                         + [sm["at"] for sm in main_doc["sendmessage_calls"]
                            if isinstance(sm.get("at"), str)])
    bad_audits = sorted(w["ended"] for w, txt in audits
                        if w.get("ended") and sum(int(x) for x in ABATERI_RE.findall(txt)))
    # 🔴 the advisor only exists since v1.7 — DECIZII «v1.7 — advisor + efort pe faze»
    for a, b in (zip(bad_audits, bad_audits[1:]) if is_v17 else ()):
        nxt = [t for t in impl_events if t > b]
        if not nxt:
            continue
        if not any(b <= t <= nxt[0] for t in adv_events):
            new_flags.append(flag("advisor_mandatory_missed", "main",
                                  "two auditor reports with ABATERI (%s, %s) and no advisor "
                                  "before the next brief" % (local_str(a, "%H:%M"),
                                                             local_str(b, "%H:%M")),
                                  {"at": b}, 0))
            break
    adv_turns = sorted(pos_of_tool.get(l["tool_use_id"]) for l in adv_launches
                       if pos_of_tool.get(l["tool_use_id"]) is not None)
    for i, tid in (exit_pos if is_v17 else ()):
        plan_txt = (tool_inputs.get(tid) or {}).get("plan") or ""
        if not TRIGGER_B_RE.search(plan_txt):
            continue
        if any(p <= i for p in adv_turns):
            continue
        new_flags.append(flag("advisor_trigger_b_missed", "main",
                              "plan mentions hooks/settings/migration and no advisor was "
                              "called before ExitPlanMode (heuristic on the plan text)",
                              {"at": turns[i]["at"], "turn": i}, 0))
        break
    for k, lag in enumerate(lags):
        if lag is not None and lag > THRESHOLDS["effort_lag_turns"]:
            new_flags.append(flag("effort_lag_high", "main",
                                  "%d main turns after ExitPlanMode #%d before the first low "
                                  "turn (warn %d)"
                                  % (lag, k + 1, THRESHOLDS["effort_lag_turns"]),
                                  {"lag": lag}, 0))
            break
    if is_v17 and exit_pos and not low_pos:
        new_flags.append(flag("no_low_phase", "main",
                              "v1.7 session with ExitPlanMode and no low turn at all",
                              None, 0))

    # ---- the plan echoed back as a tool_result, re-sent on every later turn
    echo = None
    if exit_pos:
        pos, tid = exit_pos[0]
        res_chars = {r["tool_use_id"]: r["chars"] for r in main_doc["results"]}
        chars = res_chars.get(tid, 0)
        model = collections.Counter(c["model"] for c in turns).most_common(1)[0][0]
        rate = float(rates_for(pricing, model).get("cache_read", 0.0)) / 1_000_000.0
        tokens_est = chars // 4
        turns_after = len(turns) - 1 - pos
        echo = {"chars": chars, "tokens_est": tokens_est, "turns_after": turns_after,
                "cost_est_usd": round(tokens_est * turns_after * rate, 6)}

    block = {
        "is_v17": is_v17,
        "inherited_turns": inherited_turns,
        "effort_turns": {k: counts.get(k, 0) for k in EFFORT_KEYS},
        "effort_cost_usd": {k: round(cost.get(k, 0.0), 4) for k in EFFORT_KEYS},
        "effort_output_tokens": {k: out_tok.get(k, 0) for k in EFFORT_KEYS},
        "effort_thinking_tokens": {k: think_tok.get(k, 0) for k in EFFORT_KEYS},
        "effort_tool_calls": {k: tcalls.get(k, 0) for k in EFFORT_KEYS},
        "effort_runs": runs,
        "plan": {"exit_plan_count": len(exit_pos), "enter_plan_count": len(enter_pos),
                 "lag_turns_to_low": lags, "mismatch_turns": mismatch, "echo": echo},
        "advisor": advisor,
        "low_phase": low_phase,
        # 🔴 corpus medians are filled in --trends, not per session — DECIZII «Counterfactual înlocuit»
        "cost_per_turn": None,
    }
    return block, new_flags


# 🔴 the formula is normative, it is not adjusted locally — DECIZII «Rate: advisor_score și mistakes automate»
def derive_quality(v17, low_phase=None):
    """advisor_score (1-5 or None) + mistakes + breakdown, computed from the v1.7 block."""
    v = v17 if isinstance(v17, dict) else {}
    adv = v.get("advisor") or {}
    lp = low_phase if isinstance(low_phase, dict) else (v.get("low_phase") or {})
    flags = dict(lp.get("flags") or [])
    breakdown = {"audit_abateri_total": int(lp.get("audit_abateri_total") or 0),
                 "low_flags": sum(int(n or 0) for n in flags.values()),
                 "reruns": int(lp.get("reruns") or 0)}
    mistakes = sum(breakdown.values())
    verdict = str(adv.get("verdict") or "").strip()
    if not verdict:
        return None, mistakes, breakdown
    score = 3
    if int(adv.get("n_schimbari") or 0) >= 1 and int(adv.get("plan_edits_after") or 0) >= 1:
        score += 1
    if breakdown["audit_abateri_total"] == 0:
        score += 1
    if breakdown["audit_abateri_total"] >= 3:
        score -= 1
    if "NO-GO" in verdict.upper() and any((r or {}).get("effort") == "low"
                                          for r in (v.get("effort_runs") or [])):
        score -= 1
    return max(1, min(5, score)), mistakes, breakdown


def _manual(quality, key):
    """A value from /rate; what a previous run wrote back is marked <key>_src: auto."""
    if not isinstance(quality, dict) or quality.get(key + "_src") == "auto":
        return None
    return quality.get(key)


def apply_quality_to_v17(session):
    """advisor.score / low_phase.mistakes: auto from the v1.7 block, /rate only overrides."""
    v = session.get("v17")
    if not isinstance(v, dict):
        return
    q = session.get("quality")
    auto_score, auto_mistakes, breakdown = derive_quality(v, v.get("low_phase"))
    man_score = clean_score(_manual(q, "advisor_score"))
    try:
        man_mistakes = int(_manual(q, "mistakes"))
    except (TypeError, ValueError):
        man_mistakes = None
    a = v.setdefault("advisor", {})
    a["score"] = auto_score if man_score is None else man_score
    a["advisor_score_src"] = "auto" if man_score is None else "manual"
    lp = v.setdefault("low_phase", {})
    lp["mistakes"] = auto_mistakes if man_mistakes is None else man_mistakes
    lp["mistakes_src"] = "auto" if man_mistakes is None else "manual"
    lp["mistakes_breakdown"] = breakdown
    if isinstance(q, dict):
        q["advisor_score"] = a["score"]
        q["advisor_score_src"] = a["advisor_score_src"]
        q["mistakes"] = lp["mistakes"]
        q["mistakes_src"] = lp["mistakes_src"]


def analyze(jsonl_path, pricing, ctx_warn=None, agents_dir=None,
            as_model=None, rot_at=ROT_AT_DEFAULT, window=WINDOW_DEFAULT,
            versions=None, browser_threshold=BROWSER_THRESHOLD_DEFAULT,
            # 🔴 effort_baseline is accepted, but ignored — DECIZII «Counterfactual înlocuit»
            effort_baseline=None):
    _PARENT_UUIDS.clear()  # 🔴 cache per run, otherwise it grows over the whole corpus — PATTERNS «sessionId vs session_id in jsonl»
    if versions is None:
        versions = []
    if ctx_warn is None:
        ctx_warn = THRESHOLDS["high_context_end"]
    if agents_dir is None:
        agents_dir = AGENTS_DIR_DEFAULT
    if as_model is None:
        as_model = AS_MODEL_DEFAULT
    tool_names, tool_inputs = {}, {}
    # 🔴 a fork has no record of its own: the record belongs to the origin — PATTERNS «Resumed sessions»
    jsonl_path = chain_origin(jsonl_path)
    chain = fork_chain(jsonl_path)
    files = session_files(jsonl_path, chain)
    docs = [(path, label,
             parse_file(path, label, tool_names, tool_inputs,
                        chain if label is None else None))
            for path, label in files]
    main_doc = docs[0][2]
    sub_docs = docs[1:]

    per_model = collections.defaultdict(zeros)
    main: dict = zeros()
    side = zeros()
    agents = {}
    agent_usage = collections.defaultdict(zeros)
    agent_models = collections.defaultdict(collections.Counter)
    agent_runs = collections.Counter()
    tool_results = []
    reads = collections.Counter()
    reads_eff = collections.Counter()
    first_ts = last_ts = None

    for path, label, doc in docs:
        if doc["first_ts"] and (first_ts is None or doc["first_ts"] < first_ts):
            first_ts = doc["first_ts"]
        if doc["last_ts"] and (last_ts is None or doc["last_ts"] > last_ts):
            last_ts = doc["last_ts"]
        reads.update(doc["reads"])
        reads_eff.update(read_counts(doc))
        for r in doc["results"]:
            tool_results.append((r["chars"], r["tool_use_id"]))
        if label is not None:
            agent_runs[label] += 1
        for grp in doc["groups"].values():
            usage = grp["usage"]
            if grp.get("inherited"):
                continue
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

    totals: dict = zeros()
    models_out = {}
    for model, counts in sorted(per_model.items()):
        rates = rates_for(pricing, model)
        row = dict(counts)
        row["cost_usd"] = cost_of(counts, rates)
        models_out[model] = row
        for k in ("input", "output", "cache_read", "cache_creation",
                  "cache_creation_5m", "messages"):
            totals[k] += counts[k]
    totals["cost_usd"] = round(sum(m["cost_usd"] for m in models_out.values()), 4)

    main_groups = [g for g in main_doc["groups"].values()
                   if not g["side"] and not g.get("inherited")]
    efforts = [g.get("effort") for g in main_groups if g.get("effort")]
    main["effort"] = collections.Counter(efforts).most_common(1)[0][0] if efforts else None
    changes, prev = [], None
    for g in main_groups:
        e = g.get("effort")
        if e and e != prev:
            if prev is not None:
                changes.append([local_str(g["at"], "%H:%M"), e])
            prev = e
    main["effort_changes"] = changes
    main_models = collections.Counter(g["model"] for g in main_groups)
    main_model_name = main_models.most_common(1)[0][0] if main_models else "?"
    main["cost_usd"] = cost_of(main, rates_for(pricing, main_model_name))
    totals["main_cost_usd"] = main["cost_usd"]

    tool_results.sort(key=lambda x: -x[0])
    top_tools = [{"tool": tool_names.get(tid, "?"), "chars": n, "tool_use_id": tid}
                 for n, tid in tool_results[:10]]

    # 🔴 separate Counter: regeneration resets the count — PATTERNS «Reread after regeneration»
    rereads = [{"path": p, "reads": n} for p, n in reads_eff.most_common() if n >= 2]
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

    def add_worker(wtype, description, brief_chars, launch_model, entry, launch_id=None,
                   launch_at=None, brief_debugging=False):
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
            "launched_at": launch_at,
            "brief_debugging": bool(brief_debugging),
            "final_report_chars": report_chars,
            "tool_calls": len(rows),
            "edit_calls": doc["edit_calls"] if doc else 0,
            "files_changed": (doc["files_changed"] if doc and wtype.startswith("scripter")
                              else None),
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
                                  launch["tool_use_id"], launch.get("at"),
                                  launch.get("debugging"))
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
        "implementer_runs": by_type.get("implementer", 0) + by_type.get("implementer-complex", 0) + by_type.get("implementer-max", 0) + by_type.get("implementer-sonnet", 0)
                            + by_type.get("scripter", 0) + by_type.get("scripter-complex", 0),
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
    docs_by_scope = {}
    for scope, doc, rows in worker_scopes:
        chars_by_id = {r["tool_use_id"]: r["chars"] for r in rows
                       if isinstance(r.get("tool_use_id"), str)}
        docs_by_scope[scope] = (doc, chars_by_id)
    flags = scope_flags("main", main_doc, main_rows, True)
    for scope, doc, rows in worker_scopes:
        flags.extend(scope_flags(scope, doc, rows, False))
    for w in workers:
        report_cap = report_limit_for(w["type"])
        if w["final_report_chars"] > report_cap:
            flags.append(flag("long_agent_report", w["scope"],
                              "final report %s chars (cap %s)"
                              % (fmt(w["final_report_chars"]), fmt(report_cap)),
                              {"chars": w["final_report_chars"], "cap": report_cap},
                              (w["final_report_chars"] - report_cap) / 4.0))
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
        if w["type"].startswith("implementer") or w["type"].startswith("scripter"):
            wd = docs_by_scope.get(w["scope"])
            fe = first_edit_block(wd[0], tool_inputs, wd[1]) if wd else None
            if fe and (fe["ctx"] >= THRESHOLDS["late_first_edit_ctx"]
                       or fe["read_calls"] >= THRESHOLDS["late_first_edit_reads"]):
                flags.append(flag("late_first_edit", w["scope"],
                                  "first write at call %d, context %s, %d reading calls "
                                  "(%s chars) before it"
                                  % (fe["call"], tok(fe["ctx"]), fe["read_calls"],
                                     fmt(fe["read_chars"])),
                                  fe, 0))
        if w["transcript"] and w["final_report_chars"] == 0 and not w["max_turns_hit"]:
            flags.append(flag("agent_no_report", w["scope"],
                              "ended without a final report", None, 0))
        if (w["type"].startswith("scripter") and w["files_changed"] is not None
                and w["files_changed"] < THRESHOLDS["scripter_min_files"]):
            flags.append(flag("scripter_below_threshold", w["scope"],
                              "%s changed %d file(s) for %s"
                              % (w["type"], w["files_changed"], usd(w["cost_usd"])),
                              {"type": w["type"], "files_changed": w["files_changed"],
                               "usd": round(w["cost_usd"], 4)}, 0))
        # 🔴 sub-agents only ever hold a 5m cache — PATTERNS «Cache TTL 5m for sub-agents»
        wdoc = docs_by_scope.get(w["scope"])
        wcalls = sorted([c for c in wdoc[0]["calls"] if c["at"]],
                        key=lambda c: c["at"]) if wdoc else []
        r_5m = float(rates_for(pricing, w["model"]).get("cache_write_5m", 0.0))
        for prev, cur in zip(wcalls, wcalls[1:]):
            prev_ctx = prev["cache_read"] + prev["cache_creation"]
            gap = span_s(prev["at"], cur["at"])
            if not prev_ctx or gap <= THRESHOLDS["agent_resume_gap_s"]:
                continue
            if 100.0 * cur["cache_read"] / prev_ctx >= THRESHOLDS["agent_resume_read_pct"]:
                continue
            cost = cur["cache_creation"] * r_5m / 1_000_000.0
            flags.append(flag("agent_resume_rewrite", w["scope"],
                              "resume after %.0fs: %s context rewritten (%s)"
                              % (gap, tok(cur["cache_creation"]), usd(cost)),
                              {"kind": "resume", "gap_s": round(gap, 1), "at": cur["at"],
                               "tokens": cur["cache_creation"], "usd": round(cost, 4)}, 0))
    sm_ts = sorted(t for t in main_doc["sendmessage_ts"] if isinstance(t, str))
    audit_ends = sorted(w["ended"] for w in workers
                        if w["type"] == "auditor" and w["ended"])
    for w in workers:
        if w["type"] != "implementer-max" or w.get("brief_debugging"):
            continue
        at = w.get("launched_at") or w.get("started")
        if not at:
            continue
        prev = [e for e in audit_ends if e < at]
        since = prev[-1] if prev else (main_doc["first_ts"] or "")
        if any(since <= t < at for t in sm_ts):
            continue
        flags.append(flag("max_without_sendmessage", "main",
                          "%s launched with no SendMessage since %s"
                          % (w["scope"], "the previous audit" if prev
                             else "the start of the session"),
                          {"scope": w["scope"], "since": since, "at": at}, 0))
    # 🔴 the cap is per brief, not per session — DECIZII «v1.4.1 — 30.08.2026»
    briefs = collections.OrderedDict()
    for w in workers:
        if not (w["type"].startswith("implementer") or w["type"].startswith("scripter")):
            continue
        briefs.setdefault(brief_key(w["description"]) or w["scope"], []).append(w)
    for key, ws in briefs.items():
        if len(ws) > THRESHOLDS["max_implementer_runs"]:
            flags.append(flag("too_many_runs", "main",
                              "brief \"%s\" ran %d× (cap %d)"
                              % (key, len(ws), THRESHOLDS["max_implementer_runs"]),
                              {"brief": key, "runs": len(ws)}, 0))
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
    # 🔴 per call, unlike cache_churn_main which is per session — PATTERNS «Cache TTL 5m for sub-agents»
    timed = sorted([c for c in calls if c["at"]], key=lambda c: c["at"])
    for prev, cur in zip(timed, timed[1:]):
        cur_ctx = cur["cache_read"] + cur["cache_creation"]
        prev_ctx = prev["cache_read"] + prev["cache_creation"]
        gap = span_s(prev["at"], cur["at"])
        if (not cur_ctx or prev_ctx <= THRESHOLDS["cache_rewrite_prev_tokens"]
                or gap > THRESHOLDS["cache_rewrite_max_gap_s"]):
            continue
        if 100.0 * cur["cache_creation"] / cur_ctx <= THRESHOLDS["cache_rewrite_pct"]:
            continue
        flags.append(flag("cache_rewrite_main", "main",
                          "%s: %s rewritten %.0fs after a call with %s cached"
                          % (local_str(cur["at"], "%H:%M"), tok(cur["cache_creation"]),
                             gap, tok(prev_ctx)),
                          {"at": cur["at"], "gap_s": round(gap, 1),
                           "tokens": cur["cache_creation"], "prev_tokens": prev_ctx}, 0))
    if max_concurrent > THRESHOLDS["max_live_agents"]:
        flags.append(flag("parallel_over_cap", "main",
                          "main: %d sub-agents running at once (cap %d)"
                          % (max_concurrent, THRESHOLDS["max_live_agents"]),
                          {"max_concurrent": max_concurrent}, 0))

    version = version_of(first_ts, versions)
    v17, v17_flags = v17_block(main_doc, workers,
                               {sc: d for sc, d, _r in worker_scopes},
                               tool_inputs, pricing, version, flags,
                               totals["cost_usd"])
    flags.extend(v17_flags)

    postmortem = postmortem_block(main_doc, workers, flags, main, by_type)
    cf = counterfactual_block(main_doc, [(sc, d) for sc, d, _r in worker_scopes],
                              pricing, as_model, rot_at, window, totals["cost_usd"])

    ts0, cwd0 = main_doc["first_ts"], main_doc["cwd"]
    if ts0 is None and cwd0 is None:
        ts0, cwd0 = first_meta(jsonl_path)
    out_total = totals["output"] or 1
    totals["agents_cost_usd"] = round(sum(w["cost_usd"] for w in workers), 4)
    # 🔴 inherited workers have no transcript of their own (0 calls, $0) — PATTERNS «Resumed sessions»
    scr = [w for w in workers if w["type"].startswith("scripter") and w.get("transcript")]
    with_files = [w for w in scr if w.get("files_changed")]
    scripter = {
        "runs": len(scr),
        "cost_usd": round(sum(w["cost_usd"] for w in scr), 4),
        "files_changed": sum(w["files_changed"] for w in with_files) if with_files else None,
        "runs_with_files": len(with_files),
    }
    return {
        "session": os.path.basename(jsonl_path)[:-len(".jsonl")],
        "name": session_name(jsonl_path, ts0, cwd0),
        "project": os.path.basename(os.path.dirname(jsonl_path)),
        "task_class": task_class(os.path.basename(os.path.dirname(jsonl_path))),
        "path": jsonl_path,
        "started": first_ts,
        "ended": last_ts,
        "version": version,
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
        "scripter": scripter,
        "resumed_from": main_doc["resumed_from"],
        "forked_to": [session_id_of(p) for p in chain[1:]] or None,
        "inherited_assistant_msgs": main_doc["inherited_msgs"],
        "own_assistant_msgs": main_doc["own_msgs"],
        "parallel": parallel,
        "tool_output": tool_output,
        "rereads": rereads_detail,
        "flags": flags,
        "postmortem": postmortem,
        "counterfactual": cf,
        "v17": v17,
    }


# ---------------------------------------------------------------- markdown

def fmt(n):
    return "{:,}".format(n).replace(",", ".")


def num_or_dash(x):
    return "—" if x is None else x


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
           "wasted (%s of main input volume)"
           % (len(s["flags"]), sev["high"], sev["medium"], sev["low"],
              tok(pm["wasted_total"]), pct(pm.get("wasted_pct_of_main_input"), "n/a"))]
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
        narr = ("narration-only calls %d (%d avoidable, of which %d residual_poll · "
                "%d structural, ~%s cache_read ≈ %s input-equiv.)"
                % (pm.get("narration_calls", 0), pm["narration_avoidable"],
                   pm.get("narration_residual_poll", 0),
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


def summary_ok_list(s):
    """The checks that did NOT fire: the counterpart of the flags, named one by one."""
    codes = set(f["code"] for f in s.get("flags") or [])
    runs = (s.get("iterations") or {}).get("agent_runs_by_type") or {}
    lp = ((s.get("v17") if isinstance(s.get("v17"), dict) else {}) or {}).get("low_phase") or {}
    live = (s.get("parallel") or {}).get("max_concurrent", 0)
    ok = []
    if "too_many_runs" not in codes:
        ok.append("runs ≤ cap")
    if runs.get("explorer", 0) <= THRESHOLDS["max_explorer_runs"]:
        ok.append("explorer %d ≤ %d" % (runs.get("explorer", 0), THRESHOLDS["max_explorer_runs"]))
    if live <= THRESHOLDS["max_live_agents"]:
        ok.append("live agents %d <= %d" % (live, THRESHOLDS["max_live_agents"]))
    if lp.get("audit_ok") and not lp.get("audit_abateri_total"):
        ok.append("audit OK")
    if not any(w.get("type", "").endswith("-max") for w in s.get("workers") or []):
        ok.append("no max escalation")
    return ok


def summary_lines(s):
    """`## Summary`: the whole post-mortem in a few lines, no JSON needed."""
    v = s.get("v17") if isinstance(s.get("v17"), dict) else {}
    v = v or {}
    t, m = s.get("totals") or {}, s.get("main") or {}
    et, ec = v.get("effort_turns") or {}, v.get("effort_cost_usd") or {}
    p, a = v.get("plan") or {}, v.get("advisor") or {}
    lp, cpt = v.get("low_phase") or {}, v.get("cost_per_turn") or {}
    out = ["## Summary", ""]
    out.append("%s · %s · effort %s · $%.2f total (main $%s · agents $%s) · quality %s"
               % (task_class(s), s.get("version") or VERSION_OLDER, m.get("effort") or "—",
                  t.get("cost_usd", 0.0),
                  "—" if m.get("cost_usd") is None else "%.2f" % m["cost_usd"],
                  "—" if t.get("agents_cost_usd") is None else "%.2f" % t["agents_cost_usd"],
                  quality_score(s) or "—"))
    lag = ", ".join("—" if l is None else str(l) for l in (p.get("lag_turns_to_low") or [])) or "—"
    out.append("Turns: plan %d medium ($%.2f) / impl %d low ($%.2f) · high %d · lag %s turns "
               "· $/turn %s"
               % (et.get("medium", 0), ec.get("medium", 0.0), et.get("low", 0),
                  ec.get("low", 0.0), et.get("high", 0), lag,
                  num_or_dash(cpt.get("main_usd_per_turn") or main_usd_per_turn(s))))
    out.append("Advisor: %s · changes %d items · audit DEVIATIONS %d (OK %d)"
               % (a.get("verdict") or "not requested", a.get("n_schimbari", 0),
                  lp.get("audit_abateri_total", 0), lp.get("audit_ok", 0)))
    echo = p.get("echo")
    out.append("Plan echo: %s"
               % ("—" if not echo else "$%.4f (%s chars resent over %d turns)"
                  % (echo.get("cost_est_usd", 0.0), fmt(echo.get("chars", 0)),
                     echo.get("turns_after", 0))))
    flags = s.get("flags") or []
    if flags:
        sev = collections.Counter(f.get("severity") or "low" for f in flags)
        top = collections.Counter(f["code"] for f in flags).most_common(3)
        out.append("Flags: %d (%dH/%dM/%dL) — %s"
                   % (len(flags), sev["high"], sev["medium"], sev["low"],
                      ", ".join("%s×%d" % (c, n) for c, n in top)))
    else:
        out.append("Flags: no flags")
    out.append("ok: " + (" · ".join(summary_ok_list(s)) or "—"))
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
    m = s.get("main") or {}
    if m.get("cost_usd") is not None:
        eff = m.get("effort") or "?"
        if m.get("effort_changes"):
            eff += " → " + " → ".join("%s %s" % (at, val) for at, val in m["effort_changes"])
        line = ("main: $%.2f (effort %s) · agents: $%.2f"
                % (m["cost_usd"], eff, t.get("agents_cost_usd", 0.0)))
        split = m["cost_usd"] + (t.get("agents_cost_usd") or 0.0)
        if abs(split - t["cost_usd"]) > 0.01:
            line += " · split mismatch: %.2f vs totals %.2f" % (split, t["cost_usd"])
        out.append(line)
    if s.get("resumed_from"):
        out.append("resumed from %s · %d inherited msgs (excluded from cost)"
                   % (s["resumed_from"][:8], s.get("inherited_assistant_msgs", 0)))
    if s.get("forked_to"):
        out.append("forked into %s (merged into this record)"
                   % " · ".join(f[:8] for f in s["forked_to"]))
    sc = s.get("scripter") or {}
    if sc.get("runs"):
        out.append("scripter: %d runs · $%.2f · files changed %s"
                   % (sc["runs"], sc.get("cost_usd", 0.0),
                      sc["files_changed"] if sc.get("files_changed") else "—"))
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

    out = [out[0], ""] + summary_lines(s) + ["## Session", ""] + out[1:]

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
                   "edits | files | out tok | $ | brief | report | flags |")
        out.append("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for w in s["workers"]:
            codes = sorted(set(f["code"] for f in flags_by_scope(s, w["scope"])))
            calls = "%d/%s" % (w["api_calls"], w.get("turns_limit") or "?")
            edits = w.get("edit_calls")
            out.append("| %d | %s | %s | %s | %s | %s | %s | %d/%d | %s | %s | %s | %.2f "
                       "| %s | %s | %s |"
                       % (w["n"], w["type"], short_model(w["model"]),
                          local_str(w["started"], "%H:%M"), dur(w["duration_s"]),
                          calls, tok(w.get("peak_ctx", 0)),
                          w.get("verify_with_fix", 0), w.get("verify_calls", 0),
                          "—" if edits is None else edits,
                          w["files_changed"] if w.get("files_changed") else "—",
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

    out.extend(v17_lines(s))

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


V17_BENCH_NOTE = ("Benchmark, not a pass/fail criterion: the cost figures compare configurations, "
                  "they do not pass or fail a session.")


def v17_lines(s):
    """`## v1.7` section: effort phases, plan lag, advisor, low phase, counterfactual."""
    v = s.get("v17")
    if not isinstance(v, dict):
        return []
    et = v.get("effort_turns") or {}
    if not sum(et.get(k, 0) for k in ("high", "medium", "low")):
        return []
    head = "## v1.7 — effort phases & advisor"
    inh = v.get("inherited_turns") or 0
    if inh:
        head += " (%d inherited turns, billed to the parent, outside these figures)" % inh
    out = [head, "", V17_BENCH_NOTE, "",
           "| effort | turns | tool calls | output tok | thinking tok | $ |",
           "|---|---:|---:|---:|---:|---:|"]
    for k in EFFORT_KEYS:
        if not et.get(k):
            continue
        out.append("| %s | %d | %d | %s | %s | %.2f |"
                   % (k, et[k], (v.get("effort_tool_calls") or {}).get(k, 0),
                      tok((v.get("effort_output_tokens") or {}).get(k, 0)),
                      tok((v.get("effort_thinking_tokens") or {}).get(k, 0)),
                      (v.get("effort_cost_usd") or {}).get(k, 0.0)))
    out.append("")
    runs = v.get("effort_runs") or []
    if runs:
        out.append("Phases: " + " → ".join("%s %dt (%d–%d, %d tool calls)"
                                           % (r["effort"], r["turns"], r["from"], r["to"],
                                              r["tool_calls"]) for r in runs[:12]))
    p = v.get("plan") or {}
    lags = ", ".join("—" if l is None else str(l) for l in (p.get("lag_turns_to_low") or [])) or "—"
    out.append("Plan: ExitPlanMode %d · EnterPlanMode %d · lag to low %s turns · mismatch turns %s"
               % (p.get("exit_plan_count", 0), p.get("enter_plan_count", 0), lags,
                  "—" if p.get("mismatch_turns") is None else p["mismatch_turns"]))
    a = v.get("advisor") or {}
    out.append("Advisor: %d calls · %d SendMessage · $%.2f (%.1f%% of the session) · verdict %s "
               "· changes %d · improvements %d (scope+ %d) · plan edits after %d · rounds %d "
               "· score %s"
               % (a.get("calls", 0), a.get("sendmessages", 0), a.get("cost_usd", 0.0),
                  a.get("share_pct", 0.0), a.get("verdict") or "—",
                  a.get("n_schimbari", 0), a.get("n_imbunatatiri", 0), a.get("n_scope_plus", 0),
                  a.get("plan_edits_after", 0), a.get("rounds", 0), a.get("score") or "—"))
    if a.get("reason_line"):
        out.append("Advisor reason: %s" % a["reason_line"])
    lp = v.get("low_phase") or {}
    fl = ", ".join("%s×%d" % (c, n) for c, n in (lp.get("flags") or [])) or "none"
    out.append("Low phase: flags %s · SendMessage resends %d · reruns %d · audit ABATERI %d "
               "· audits OK %d · mistakes %s"
               % (fl, lp.get("sendmessage_resends", 0), lp.get("reruns", 0),
                  lp.get("audit_abateri_total", 0), lp.get("audit_ok", 0),
                  "—" if lp.get("mistakes") is None else lp["mistakes"]))
    echo = p.get("echo")
    if echo:
        out.append("Plan echo: %s chars (~%s tok) re-sent over %d turns → $%.4f cache-read"
                   % (fmt(echo.get("chars", 0)), fmt(echo.get("tokens_est", 0)),
                      echo.get("turns_after", 0), echo.get("cost_est_usd", 0.0)))
    cpt = v.get("cost_per_turn")
    if cpt:
        out.append("Cost/main turn: $%s (%s) · corpus high median %s (n=%d) · medium median %s "
                   "(n=%d)"
                   % (cpt.get("main_usd_per_turn"), cpt.get("task_class"),
                      num_or_dash(cpt.get("corpus_high_median")), cpt.get("corpus_n_high", 0),
                      num_or_dash(cpt.get("corpus_medium_median")),
                      cpt.get("corpus_n_medium", 0)))
    else:
        out.append("Cost/main turn: corpus medians only in --trends")
    out.append("")
    return out


V17_GROUPS = ("v1.7", "high permanent", "medium permanent")


def v17_group_of(s):
    """Which comparison column a session belongs to; None = mixed, not comparable."""
    # 🔴 a session with no main turns of its own has v17 = null — PATTERNS «New fields in old records»
    if not isinstance(s.get("v17"), dict):
        return None
    v = s["v17"]
    et = v.get("effort_turns") or {}
    total = sum(et.values())
    if str(s.get("version") or "").startswith(V17_VERSION_PREFIX):
        return "v1.7"
    if not total:
        return None
    if et.get("high", 0) / float(total) >= 0.9:
        return "high permanent"
    if et.get("medium", 0) / float(total) >= 0.9:
        return "medium permanent"
    return None


EFFORT_PURE_SHARE = 0.9


def effort_profile(s):
    """`high`/`medium` when nearly every main turn ran at that effort; else None."""
    v = s.get("v17")
    if not isinstance(v, dict):
        return None
    et = v.get("effort_turns") or {}
    total = sum(et.values())
    if not total:
        return None
    for k in ("high", "medium"):
        if et.get(k, 0) / float(total) >= EFFORT_PURE_SHARE:
            return k
    return None


def main_usd_per_turn(s):
    v = s.get("v17")
    if not isinstance(v, dict):
        return None
    turns = sum((v.get("effort_turns") or {}).values())
    main_cost = (s.get("main") or {}).get("cost_usd") or 0.0
    return round(main_cost / turns, 4) if turns else None


def apply_cost_per_turn(sessions):
    """v17.cost_per_turn: this session's $/main turn next to the medians of its task class."""
    corpus = collections.defaultdict(lambda: collections.defaultdict(list))
    for s in sessions:
        prof, val = effort_profile(s), main_usd_per_turn(s)
        if prof and val is not None:
            corpus[task_class(s)][prof].append(val)
    for s in sessions:
        v = s.get("v17")
        if not isinstance(v, dict):
            continue
        tc = task_class(s)
        highs, meds = corpus[tc]["high"], corpus[tc]["medium"]
        v["cost_per_turn"] = {
            "main_usd_per_turn": main_usd_per_turn(s),
            # 🔴 under 2 sessions the median means nothing — DECIZII «Counterfactual înlocuit»
            "corpus_high_median": round(median(highs), 4) if len(highs) >= 2 else None,
            "corpus_medium_median": round(median(meds), 4) if len(meds) >= 2 else None,
            "corpus_n_high": len(highs),
            "corpus_n_medium": len(meds),
            "task_class": tc,
        }
    return sessions


def v17_session_metrics(s):
    v = s.get("v17") or {}
    et = v.get("effort_turns") or {}
    turns = sum(et.values())
    cost = (s.get("totals") or {}).get("cost_usd") or 0.0
    main_cost = (s.get("main") or {}).get("cost_usd") or 0.0
    return {
        "cost_usd": cost,
        "cost_per_main_turn": round(main_cost / turns, 4) if turns else None,
        "main_turns": turns,
        "main_tool_calls": s.get("main_tool_calls") or 0,
        "agents": len(s.get("workers") or []),
        "flags": len(s.get("flags") or []),
        "rate": quality_score(s),
        "abateri": (v.get("low_phase") or {}).get("audit_abateri_total"),
    }


V17_COMPARE = (("cost/session $", "cost_usd", "$"), ("cost/main turn $", "cost_per_main_turn", "$"),
               ("main turns", "main_turns", "n"), ("main tool calls", "main_tool_calls", "n"),
               ("agents launched", "agents", "n"), ("flags/session", "flags", "n"),
               ("rate", "rate", "n"), ("audit ABATERI", "abateri", "n"))


def v17_md(sessions):
    """metrics-local/V17.md: one row per v1.7 session + medians against the older setups."""
    rows = [s for s in sessions if v17_group_of(s) == "v1.7"]
    out = ["# V17 — effort phases & advisor (%d v1.7 sessions)" % len(rows), "",
           V17_BENCH_NOTE, ""]
    out.append("| session | class | rate | mistakes | advisor calls/score/verdict | "
               "turns med/low | $ med | $ low | $/turn | corpus med $/turn | "
               "corpus high $/turn | ABATERI | low flags | lag |")
    out.append("|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    if not rows:
        out.append("| _no v1.7 session yet_ | | | | | | | | | | | | | |")
    for s in sorted(rows, key=lambda s: s.get("started") or ""):
        v = s["v17"]
        et, ec = v.get("effort_turns") or {}, v.get("effort_cost_usd") or {}
        a, lp, p = v.get("advisor") or {}, v.get("low_phase") or {}, v.get("plan") or {}
        cpt = v.get("cost_per_turn") or {}
        fl = ", ".join("%s×%d" % (c, n) for c, n in (lp.get("flags") or [])) or "—"
        lag = ", ".join("—" if l is None else str(l)
                        for l in (p.get("lag_turns_to_low") or [])) or "—"
        # 🔴 medians are read on their own class, no high↔medium fallback — DECIZII «Clasa de task»
        out.append("| %s | %s | %s | %s | %d/%s/%s | %d/%d | %.2f | %.2f | %s | %s | %s "
                   "| %d | %s | %s |"
                   % (s.get("name") or s.get("session"), cpt.get("task_class") or task_class(s),
                      quality_score(s) or "—",
                      "—" if lp.get("mistakes") is None else lp["mistakes"],
                      a.get("calls", 0), a.get("score") or "—", a.get("verdict") or "—",
                      et.get("medium", 0), et.get("low", 0),
                      ec.get("medium", 0.0), ec.get("low", 0.0),
                      num_or_dash(cpt.get("main_usd_per_turn")),
                      num_or_dash(cpt.get("corpus_medium_median")),
                      num_or_dash(cpt.get("corpus_high_median")),
                      lp.get("audit_abateri_total", 0), fl, lag))
    out.append("")
    groups = collections.OrderedDict((g, []) for g in V17_GROUPS)
    for s in sessions:
        g = v17_group_of(s)
        if g:
            groups[g].append(v17_session_metrics(s))
    out.append("## Medians per setup")
    out.append("")
    out.append("| metric | " + " | ".join("%s (n=%d)" % (g, len(groups[g])) for g in V17_GROUPS)
               + " |")
    out.append("|---|" + "---:|" * len(V17_GROUPS))
    for label, key, unit in V17_COMPARE:
        cells = []
        for g in V17_GROUPS:
            med = median([m[key] for m in groups[g] if m.get(key) is not None])
            if med is None:
                cells.append("—")
            elif unit == "$":
                cells.append("%.2f" % med)
            else:
                cells.append("%g" % med)
        out.append("| %s | %s |" % (label, " | ".join(cells)))
    out.append("")
    out.append("«high permanent» = pre-v1.7 sessions with ≥90% high turns, «medium permanent» "
               "≥90% medium; mixed sessions are in neither column.")
    out.append("")
    return "\n".join(out)


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
            agg[k] += t.get(k, 0)
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
                # 🔴 old records don't have the key; it's derived on read, not rewritten — DECIZII «Clasa de task»
                rec["task_class"] = task_class(rec)
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
    "main_read_report": "reads",
    "reread": "reads",
    "full_read_big_file": "reads",
    "big_tool_result_main": "reads",
    "read_tool_results_main": "reads",
    "tool_results_read": "reads",
    "image_in_main": "reads",
    "main_read_before_first_agent": "reads",
    "agent_read_plan_whole": "reads",
    "edit_via_bash": "agent overhead",
    "max_without_sendmessage": "discipline",
    "long_agent_report": "agent overhead",
    "agent_reread_own_write": "agent overhead",
    "agent_ctx_high": "agent overhead",
    "late_first_edit": "agent overhead",
    "sterile_verification": "agent overhead",
    "agent_max_turns": "agent overhead",
    "agent_no_report": "agent overhead",
    "narration_turns": "orchestration turns",
    "plan_echo": "orchestration turns",
    "long_brief": "orchestration turns",
    "batchable_bash": "orchestration turns",
    "cache_churn_main": "orchestration turns",
    "cache_rewrite_main": "orchestration turns",
    "agent_resume_rewrite": "agent overhead",
    "scripter_below_threshold": "discipline",
    "fable_wrote_code": "discipline",
    "too_many_runs": "discipline",
    "high_context_end": "discipline",
    "parallel_over_cap": "discipline",
    "comment_bloat": "discipline",
}
FAMILY_ORDER = ("reads", "agent overhead", "orchestration turns", "discipline", "other")


def usd(x):
    return "$%s" % format(float(x or 0.0), ",.2f")


def pct(x, dash="—"):
    return dash if x is None else "%.1f%%" % x


def wasted_pct_cell(v):
    """Percent plus how many sessions were left out for want of a denominator."""
    return pct(v["wasted_pct"], "n/a") + (" (%d excl.)" % v["wasted_na"]
                                          if v["wasted_na"] else "")


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


def edit_cost_of(sessions):
    """$ per implementer edit: sum(cost) / sum(edit_calls) over implementer* workers."""
    cost, edits = 0.0, 0
    for s in sessions:
        for w in s.get("workers") or []:
            # 🔴 old records don't have edit_calls; if included, they'd inflate $/edit — PATTERNS «New fields in old records»
            if (str(w.get("type") or "").startswith("implementer")
                    and w.get("edit_calls") is not None and w.get("transcript")):
                cost += w.get("cost_usd") or 0.0
                edits += w["edit_calls"]
    return (cost / edits) if edits else None


def scripter_saved(sessions, edit_cost):
    """Lower bound: files changed by scripts x $/edit - scripter cost; None if not computable."""
    if not edit_cost:
        return None
    total, seen = 0.0, False
    for s in sessions:
        sc = s.get("scripter") or {}
        if sc.get("files_changed"):
            total += sc["files_changed"] * edit_cost - (sc.get("cost_usd") or 0.0)
            seen = True
    return total if seen else None


CACHE_FLAG_CODES = ("cache_rewrite_main", "agent_resume_rewrite", "scripter_below_threshold")


def cache_flag_stats(sessions):
    # 🔴 records analyzed before v1.8 have no such flags: "seen" separates them from a real 0 — PATTERNS «New fields in old records»
    out = {"cache_rw_n": 0, "cache_rw_tok": 0, "resume_n": 0, "resume_usd": 0.0,
           "scr_below_n": 0, "seen": False}
    for s in sessions:
        for f in s.get("flags") or []:
            code = f.get("code")
            if code not in CACHE_FLAG_CODES:
                continue
            out["seen"] = True
            ev = f.get("evidence") or {}
            if code == "cache_rewrite_main":
                out["cache_rw_n"] += 1
                out["cache_rw_tok"] += int(ev.get("tokens") or 0)
            elif code == "agent_resume_rewrite":
                out["resume_n"] += 1
                out["resume_usd"] += float(ev.get("usd") or 0.0)
            else:
                out["scr_below_n"] += 1
    return out


def version_stats(sessions, rot_at=ROT_AT_DEFAULT, window=WINDOW_DEFAULT):
    """Per-session figures for one version group; the Versions table and the Δ line share them."""
    n = len(sessions)
    d = float(n or 1)
    cfs = [s.get("counterfactual") or {} for s in sessions]
    pms = [s.get("postmortem") or {} for s in sessions]
    ctxs = [s.get("context") or {} for s in sessions]
    sevs = [p.get("severity_counts") or {} for p in pms]
    rr = [c["ratio_realistic"] for c in cfs if c.get("ratio_realistic")]
    # 🔴 cf peak aggregated only over sessions that have the key — PATTERNS «New fields in old records»
    peak_cfs = [int(c["peak_context_cf"]) for c in cfs
                if isinstance(c.get("peak_context_cf"), (int, float))
                and c["peak_context_cf"] > 0]
    hands = sum(p.get("hands_on_calls", 0) for p in pms)
    calls = sum(p.get("main_tool_calls", 0) for p in pms)
    actual = sum((s.get("totals") or {}).get("cost_usd", 0.0) for s in sessions)
    real = sum(c.get("realistic_usd", 0.0) for c in cfs)
    floor = sum(c.get("floor_usd", 0.0) for c in cfs)
    wasted = sum(p.get("wasted_total", 0) for p in pms)
    main_in = sum(main_input_of(s) for s in sessions)
    # 🔴 the percentage is computed only on sessions with input in main — PATTERNS «Percentages with a missing denominator»
    with_in = [(p, main_input_of(s)) for s, p in zip(sessions, pms) if main_input_of(s) > 0]
    wasted_in = sum(p.get("wasted_total", 0) for p, _ in with_in)
    main_in_pct = sum(mi for _, mi in with_in)
    scores = [q for q in (quality_score(s) for s in sessions) if q]
    # 🔴 main_pct's denominator = only sessions that have main.cost_usd — PATTERNS «New fields in old records»
    with_main = [s for s in sessions if (s.get("main") or {}).get("cost_usd") is not None]
    main_sum = sum(s["main"]["cost_usd"] for s in with_main)
    main_denom = sum((s.get("totals") or {}).get("cost_usd", 0.0) for s in with_main)
    efforts = collections.Counter((s.get("main") or {}).get("effort")
                                  for s in sessions if (s.get("main") or {}).get("effort"))
    scrs = [s.get("scripter") or {} for s in sessions]
    cache_new = cache_flag_stats(sessions)
    return {
        "n": n,
        "effort_mix": " · ".join("%s %d" % (k, v) for k, v in efforts.most_common()) or "—",
        "main_pct": (100.0 * main_sum / main_denom) if (with_main and main_denom) else None,
        "edit_cost": edit_cost_of(sessions),
        "scr_runs": sum(sc.get("runs", 0) for sc in scrs),
        "scr_cost": sum(sc.get("cost_usd", 0.0) for sc in scrs),
        "resumed": sum(1 for s in sessions if s.get("resumed_from")),
        "forked": sum(1 for s in sessions if s.get("forked_to")),
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
        "wasted_pct": (100.0 * wasted_in / main_in_pct) if main_in_pct > 0 else None,
        "wasted_na": n - len(with_in),
        "n_pm": sum(1 for p in pms if p.get("wasted_total") is not None),
        "peak_ctx": sum(c.get("main_peak_tokens", 0) for c in ctxs) / d,
        "peak_cf_max": (max(peak_cfs) if peak_cfs else None),
        "peak_cf_median": (median(peak_cfs) if peak_cfs else None),
        "cf_over_rot_pct": ((100.0 * sum(1 for x in peak_cfs if x > rot_at * window)
                             / len(peak_cfs)) if peak_cfs else None),
        "cf_over_window_pct": ((100.0 * sum(1 for x in peak_cfs if x > window)
                               / len(peak_cfs)) if peak_cfs else None),
        "cf_n": len(peak_cfs),
        "cache_rw_n": cache_new["cache_rw_n"],
        "cache_rw_tok": cache_new["cache_rw_tok"],
        "resume_n": cache_new["resume_n"],
        "resume_usd": cache_new["resume_usd"],
        "scr_below_n": cache_new["scr_below_n"],
        "cache_flags_seen": cache_new["seen"],
        # 🔴 None, not 0, when the version has no such records — PATTERNS «New fields in old records»
        "cache_rw_per": (cache_new["cache_rw_n"] / d) if cache_new["seen"] else None,
        "resume_per": (cache_new["resume_n"] / d) if cache_new["seen"] else None,
        "scr_below_per": (cache_new["scr_below_n"] / d) if cache_new["seen"] else None,
    }


# (label, key, unit): "pts" for fields that are already percentages
DELTA_FIELDS = (("$/session", "actual_per", "rel"), ("saved %", "saved_pct", "pts"),
                ("wasted/session", "wasted_per", "rel"), ("wasted %", "wasted_pct", "pts"),
                ("issues/session", "issues_per", "rel"), ("main output %", "out_pct", "pts"),
                ("hands-on %", "hands_pct", "pts"),
                ("cache rewrites/session", "cache_rw_per", "rel"),
                ("agent resumes/session", "resume_per", "rel"),
                ("scripter <4 files/session", "scr_below_per", "rel"))


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


def class_groups(order, groups, cls):
    """The per-version groups kept only for one task class; cls None = everything."""
    return collections.OrderedDict(
        (name, [s for s in (groups.get(name) or []) if cls is None or task_class(s) == cls])
        for name in order)


def cumulative_saved(order, groups):
    """Savings summed in version order; each table cumulates only its own sessions."""
    cum, running = {}, 0.0
    for name in order:
        if groups.get(name):
            running += version_stats(groups[name])["saved"]
        cum[name] = running
    return cum


def rd_cost_block(order, groups):
    """`## R&D governance cost`: what the research on the workflow itself costs, per version."""
    out = ["## R&D governance cost", "",
           "| version | records | $ total | $ main | session hours |",
           "|---|---:|---:|---:|---:|"]
    tot_n, tot_cost, tot_main, tot_h = 0, 0.0, 0.0, 0.0
    for name in order:
        rd = [s for s in (groups.get(name) or []) if task_class(s) == "governance-rd"]
        if not rd:
            continue
        cost = sum((s.get("totals") or {}).get("cost_usd", 0.0) for s in rd)
        main = sum(((s.get("main") or {}).get("cost_usd") or 0.0) for s in rd)
        hours = sum((span_s(s.get("started"), s.get("ended")) or 0) for s in rd) / 3600.0
        tot_n, tot_cost, tot_main, tot_h = tot_n + len(rd), tot_cost + cost, \
            tot_main + main, tot_h + hours
        out.append("| %s | %d | %s | %s | %.1f |" % (name, len(rd), usd(cost), usd(main), hours))
    out.append("| **total** | %d | %s | %s | %.1f |" % (tot_n, usd(tot_cost), usd(tot_main),
                                                        tot_h))
    out.append("")
    return out


def versions_table(order, groups, cum, edit_cost=None, title="Versions", note=True,
                   rot_at=ROT_AT_DEFAULT, window=WINDOW_DEFAULT):
    out = ["## %s" % title, ""]
    out.append("| version | sessions | $ actual | $/session | $ Fable realistic | saved $ "
               "| saved % | saved cumulative | wasted tok/session | wasted % "
               "| issues/session (H/M/L) | main output % | hands-on | peak ctx "
               "| peak ctx cf (max/med) | cf>rot % | quality "
               "| effort | main $ % | $/edit impl | scripter runs / saved $ "
               "| cache rewrites main n / tok | agent resume rewrites n / $ "
               "| scripter runs below threshold n |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:"
               "|---:|---|---:|---:|---:|---:|---:|---:|")
    for name in order:
        sessions = groups.get(name) or []
        v = version_stats(sessions, rot_at, window)
        if not v["n"]:
            out.append("| %s | 0 |%s" % (name, " — |" * 22))
            continue
        saved = scripter_saved(sessions, edit_cost)
        scr = "%d / %s" % (v["scr_runs"], "—" if saved is None else usd(saved))
        cf_cell = ("—" if not v["cf_n"]
                   else "%s/%s" % (tok(v["peak_cf_max"]), tok(v["peak_cf_median"])))
        cf_rot_cell = ("—" if not v["cf_n"]
                       else "%.0f%% (%d/%d)" % (v["cf_over_rot_pct"],
                                                round(v["cf_over_rot_pct"] * v["cf_n"] / 100.0),
                                                v["cf_n"]))
        seen = v["cache_flags_seen"]
        cache_cell = "—" if not seen else "%d / %s" % (v["cache_rw_n"], tok(v["cache_rw_tok"]))
        resume_cell = "—" if not seen else "%d / %s" % (v["resume_n"], usd(v["resume_usd"]))
        below_cell = "—" if not seen else "%d" % v["scr_below_n"]
        out.append("| %s | %d | %s | %s | %s | %s | %.1f%% | %s | %s | %s "
                   "| %.1f (%.1f/%.1f/%.1f) | %.1f%% | %d/%d (%.0f%%) | %s | %s | %s "
                   "| %s · %d/%d "
                   "| %s | %s | %s | %s | %s | %s | %s |"
                   % (name, v["n"], usd(v["actual"]), usd(v["actual_per"]), usd(v["real"]),
                      usd(v["saved"]), v["saved_pct"], usd(cum.get(name, 0.0)),
                      tok(v["wasted_per"]), wasted_pct_cell(v),
                      v["issues_per"], v["high_per"], v["med_per"], v["low_per"],
                      v["out_pct"], v["hands"], v["calls"], v["hands_pct"],
                      tok(v["peak_ctx"]), cf_cell, cf_rot_cell,
                      "—" if v["q_mean"] is None else "%.1f" % v["q_mean"],
                      v["rated"], v["n"],
                      v["effort_mix"],
                      "—" if v["main_pct"] is None else "%.0f%%" % v["main_pct"],
                      "—" if v["edit_cost"] is None else "$%.2f" % v["edit_cost"],
                      scr, cache_cell, resume_cell, below_cell))
    out.append("")
    out.append("single-context threshold: rot %s · window %s"
               % (tok(int(rot_at * window)), tok(window)))
    out.append("")
    if edit_cost and note:
        out.append("Scripter saved = files changed by scripts × $%.2f/edit (corpus implementer "
                   "mean) − scripter cost; lower bound, sessions without a `files changed` "
                   "line count 0." % edit_cost)
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


def corpus_block(kept, skipped_note, edit_cost=None):
    v = version_stats(kept)
    lo, hi = group_range(kept)
    out = ["## Corpus", ""]
    out.append("- **Spend:** %s actual across %d sessions (%s/session)"
               % (usd(v["actual"]), v["n"], usd(v["actual_per"])))
    out.append("- **Fable-only realistic:** %s (floor %s) → **saved %s (%.1f%%)**"
               % (usd(v["real"]), usd(v["floor"]), usd(v["saved"]), v["saved_pct"]))
    out.append("- **Est. wasted:** ~%s tokens = %s of main input volume"
               % (tok(v["wasted"]), pct(v["wasted_pct"], "n/a")))
    out.append("- **Quality:** %s mean · %d/%d rated"
               % ("—" if v["q_mean"] is None else "%.1f" % v["q_mean"],
                  v["rated"], v["n"]))
    saved = scripter_saved(kept, edit_cost)
    out.append("- **Scripter:** %d runs · %s · saved ~%s"
               % (v["scr_runs"], usd(v["scr_cost"]),
                  "—" if saved is None else usd(saved)))
    out.append("- **Span:** %s → %s · %d/%d sessions with a counterfactual%s"
               % (lo, hi, v["n_cf"], v["n"], skipped_note))
    out.append("")
    return out


def version_block(name, sessions, groups, prev_name, cum, edit_cost=None):
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
    out.append("- **Waste:** ~%s tokens = %s of main input volume · %.1f issues/session "
               "(%.1f H / %.1f M / %.1f L)"
               % (tok(v["wasted"]), pct(v["wasted_pct"], "n/a"), v["issues_per"],
                  v["high_per"], v["med_per"], v["low_per"]))
    if prev_name:
        out.append(delta_line(prev_name, version_stats(groups[prev_name]), v))
    if name != VERSION_OLDER and prev_name != VERSION_OLDER and groups.get(VERSION_OLDER):
        out.append(delta_line(VERSION_OLDER, version_stats(groups[VERSION_OLDER]), v))
    if v["resumed"]:
        out.append("- **resumed:** %d sessions" % v["resumed"])
    if v.get("forked"):
        out.append("- **forked:** %d sessions (fork merged into the origin record)"
                   % v["forked"])
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
    out.append("| session | $ actual | $ main | $ agents | effort | scripter | "
               "$ fable-only realistic | saved $ | main output % | "
               "hands-on ratio | issues (H/M/L) | wasted tok | wasted % | peak ctx | q |")
    out.append("|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    recent = sorted(sessions, key=lambda s: s.get("started") or "", reverse=True)[:15]
    for s in sorted(recent, key=lambda s: s.get("started") or ""):
        pm = s.get("postmortem") or {}
        cf = s.get("counterfactual") or {}
        sev = pm.get("severity_counts") or {}
        ctx = s.get("context") or {}
        m = s.get("main") or {}
        tt = s.get("totals") or {}
        sc = s.get("scripter") or {}
        q = quality_score(s)
        act = tt.get("cost_usd", 0.0)
        saved_s = scripter_saved([s], edit_cost)
        scr = "—" if not sc.get("runs") else "%d/%s/%s" % (
            sc["runs"], sc["files_changed"] if sc.get("files_changed") else "—",
            "—" if saved_s is None else usd(saved_s))
        out.append("| %s | %.2f | %s | %s | %s | %s | %.2f | %.2f | %.1f%% | %d/%d "
                   "| %d/%d/%d | %s | %s | %s | %s |"
                   % (s.get("name") or s.get("session") or "?",
                      act,
                      "—" if m.get("cost_usd") is None else "%.2f" % m["cost_usd"],
                      "—" if tt.get("agents_cost_usd") is None
                      else "%.2f" % tt["agents_cost_usd"],
                      m.get("effort") or "—", scr,
                      cf.get("realistic_usd", 0.0),
                      cf.get("realistic_usd", 0.0) - act,
                      ctx.get("main_output_pct", 0.0),
                      pm.get("hands_on_calls", 0), pm.get("main_tool_calls", 0),
                      sev.get("high", 0), sev.get("medium", 0), sev.get("low", 0),
                      tok(pm.get("wasted_total", 0)),
                      pct(pm.get("wasted_pct_of_main_input")
                          if main_input_of(s) > 0 else None, "n/a"),
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


def trends_md(sessions, skipped, versions=None, threshold=BROWSER_THRESHOLD_DEFAULT,
              rot_at=ROT_AT_DEFAULT, window=WINDOW_DEFAULT):
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
    cum = cumulative_saved(order, groups)

    lo, hi = group_range(kept)
    n_browser = sum(1 for s in excluded if s["browser_session"])
    skipped_note = " · %d skipped (old format)" % skipped if skipped else ""
    out = ["# TRENDS — %d sessions kept (%s → %s) · excluded %d "
           "(browser %d · empty %d)"
           % (len(kept), lo, hi, len(excluded), n_browser, len(excluded) - n_browser)]
    out.append("")
    edit_cost = edit_cost_of(kept)
    out.extend(corpus_block(kept, skipped_note, edit_cost))
    # 🔴 per-class tables are not compared against each other — DECIZII «Clasa de task»
    for cls, title in (("product", "Versions — product"),
                       ("governance-rd", "Versions — governance-rd"),
                       (None, "Versions — total")):
        sub = class_groups(order, groups, cls)
        out.extend(versions_table(order, sub, cumulative_saved(order, sub), edit_cost,
                                  title, note=cls is None, rot_at=rot_at, window=window))
    out.extend(rd_cost_block(order, groups))
    out.extend(deltas_table(order, groups))
    live = [name for name in order if groups.get(name)]
    for i, name in enumerate(live):
        out.append("---")
        out.append("")
        out.extend(version_block(name, groups[name], groups,
                                 live[i - 1] if i else None, cum, edit_cost))
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
        name = session_name(path, out_dir=directory)
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
    json_path = os.path.join(out_dir, name + ".json")
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps([rec], indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, json_path)
    md_path = os.path.join(out_dir, name + ".md")
    if os.path.isfile(md_path):
        try:
            text = markdown([rec], aggregate=False) + "\n"
        except (KeyError, TypeError, ValueError):
            text = None
        if text:
            tmp_md = md_path + ".tmp"
            with open(tmp_md, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp_md, md_path)


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


def write_trends(directory, versions, threshold, rot_at=ROT_AT_DEFAULT,
                 window=WINDOW_DEFAULT):
    if not os.path.isdir(directory):
        print("not a directory: %s" % directory, file=sys.stderr)
        return 2
    refreshed = refresh_versions(directory, versions)
    if refreshed:
        print("version refreshed in %d sessions" % refreshed, file=sys.stderr)
    sessions, skipped = load_session_dir(directory)
    if not sessions:
        print("no session report in %s" % directory, file=sys.stderr)
        return 1
    apply_cost_per_turn(sessions)
    text = trends_md(sessions, skipped, versions, threshold, rot_at, window) + "\n"
    tmp = os.path.join(directory, "TRENDS.md.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, os.path.join(directory, "TRENDS.md"))
    # trends_md marks the excluded ones; V17.md sees the same corpus
    kept = [s for s in sessions if not s.get("exclude_reason")]
    tmp17 = os.path.join(directory, "V17.md.tmp")
    with open(tmp17, "w", encoding="utf-8") as fh:
        fh.write(v17_md(kept) + "\n")
    os.replace(tmp17, os.path.join(directory, "V17.md"))
    print("TRENDS.md: %d sessions, %d skipped · V17.md: %d kept"
          % (len(sessions), skipped, len(kept)), file=sys.stderr)
    return 0


def rate_session(out_dir, name, score, note, versions, threshold):
    """--rate: write quality into <name>.json, refresh its .md, then rebuild TRENDS.md."""
    path = os.path.join(out_dir, name + ".json")
    rec = read_record(path)
    if rec is None:
        print("session not found: %s" % path, file=sys.stderr)
        return 1
    old_q = rec.get("quality") or {}
    rec["quality"] = {"score": score, "note": note,
                      "rated_at": datetime.datetime.now(datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "advisor_score": old_q.get("advisor_score"),
                      "advisor_score_src": old_q.get("advisor_score_src"),
                      "mistakes": old_q.get("mistakes"),
                      "mistakes_src": old_q.get("mistakes_src")}
    apply_quality_to_v17(rec)
    write_record(out_dir, name, rec)
    print("%s: quality %d/5" % (name, score), file=sys.stderr)
    return write_trends(out_dir, versions, threshold)


def unique_name(out_dir, s):
    """<day>-HHMM-<project> unless another session id already holds it; then HHMMSS."""
    name = s["name"]
    own = {s.get("session")} | set(s.get("forked_to") or ())
    taken = read_record(os.path.join(out_dir, name + ".json"))
    if not taken or taken.get("session") is None or taken.get("session") in own:
        return name
    m = SESSION_NAME_RE.match(name)
    ts = s.get("started")
    if not m or not ts or local_day(ts) == "?":
        return name
    return "%s-%s-%s" % (local_day(ts), local_str(ts, "%H%M%S"), m.group(1))


def drop_stale_records(out_dir, name, session_id, also=None):
    """Same session id saved under another name (old scheme, a name that moved, or a fork now
    merged into its origin): delete the stale .json/.md and hand back its quality."""
    quality = None
    ids = {session_id} | set(also or ())
    ids.discard(None)
    if not ids:
        return None
    for entry in sorted(os.listdir(out_dir)):
        if not entry.endswith(".json") or entry == name + ".json":
            continue
        rec = read_record(os.path.join(out_dir, entry))
        if not rec or rec.get("session") not in ids:
            continue
        quality = quality or rec.get("quality")
        for ext in (".json", ".md"):
            old = os.path.join(out_dir, entry[:-len(".json")] + ext)
            if os.path.isfile(old):
                os.remove(old)
    return quality


OLD_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-s\d+-(.+)$")


def _new_name(rec, stem, fmt_="%H%M"):
    """(new stem, reason-if-impossible) for one saved record; fmt_ %H%M%S resolves a clash."""
    if not rec or not rec.get("session"):
        return None, "no session id"
    ts = rec.get("started")
    m = SESSION_NAME_RE.match(rec.get("name") or stem)
    proj = m.group(1) if m else ""
    if not ts or not proj:
        path = rec.get("path")
        if path and os.path.isfile(path):
            ts2, cwd = first_meta(path)
            ts = ts or ts2
            proj = proj or project_of(cwd, path)
    if not ts or not proj:
        return None, "no started or project"
    day = local_day(ts)
    if day == "?":
        return None, "undecodable started"
    return "%s-%s-%s" % (day, local_str(ts, fmt_), proj), None


def migrate_names(directory, apply_=False, versions=(), threshold=0.5):
    """--migrate-names: <day>-sN-<project> -> <day>-HHMM-<project>, renaming only (no re-analysis)."""
    if not os.path.isdir(directory):
        print("not a directory: %s" % directory, file=sys.stderr)
        return 2
    entries = [e for e in sorted(os.listdir(directory))
               if e.endswith(".json") and OLD_NAME_RE.match(e[:-len(".json")])]
    taken = {e[:-len(".json")] for e in sorted(os.listdir(directory)) if e.endswith(".json")}
    plan, skipped = [], 0
    for entry in entries:
        stem = entry[:-len(".json")]
        rec = read_record(os.path.join(directory, entry))
        new, why = _new_name(rec, stem)
        if new is None:
            print("SKIP %s %s" % (entry, why))
            skipped += 1
            continue
        if new in taken:
            alt, _why = _new_name(rec, stem, "%H%M%S")
            if alt is None or alt in taken:
                print("SKIP %s name collision on %s" % (entry, new))
                skipped += 1
                continue
            new = alt
        taken.discard(stem)
        taken.add(new)
        plan.append((stem, new, rec))
    plan.sort(key=lambda p: p[1])
    for stem, new, _ in plan:
        print("%s -> %s" % (stem, new))
    print("%d to rename, %d SKIP%s" % (len(plan), skipped, "" if apply_ else " (dry-run)"),
          file=sys.stderr)
    if apply_:
        for stem, new, rec in plan:
            for ext in (".json", ".md"):
                old = os.path.join(directory, stem + ext)
                if os.path.isfile(old):
                    os.rename(old, os.path.join(directory, new + ext))
            rec["name"] = new
            write_record(directory, new, rec)
        if plan:
            write_trends(directory, versions, threshold)
    return 1 if skipped else 0


def main(argv=None):
    # 🔴 stdout UTF-8 forced for LANG=C — PATTERNS «analyzer: locale»
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
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
    ap.add_argument("--migrate-names", dest="migrate_names", metavar="DIR",
                    help="rename <day>-sN-<project>.json/.md in DIR to <day>-HHMM-<project> "
                         "(dry-run unless --yes), then exit")
    ap.add_argument("--yes", action="store_true",
                    help="with --migrate-names: actually rename instead of listing")
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
    ap.add_argument("--build-effort-baseline", dest="build_effort_baseline", metavar="DIR",
                    help="scan DIR's level-1 transcripts for the %s turns at effort high and "
                         "write the medians to --effort-baseline, then exit" % BASELINE_MODEL)
    ap.add_argument("--effort-baseline", dest="effort_baseline",
                    default=EFFORT_BASELINE_DEFAULT,
                    help="ignored since v1.7.2 (see the project's decision log); "
                         "only the target of --build-effort-baseline (default %s)"
                         % EFFORT_BASELINE_DEFAULT)
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
            print("not a directory: %s" % args.rename, file=sys.stderr)
            return 2
        rename_dir(args.rename, args.force)
        return 0

    if args.build_effort_baseline:
        return build_effort_baseline(os.path.expanduser(args.build_effort_baseline),
                                     args.effort_baseline)

    if args.migrate_names:
        return migrate_names(args.migrate_names, args.yes, versions, args.browser_threshold)

    if args.trends:
        return write_trends(args.trends, versions, args.browser_threshold,
                            args.rot_at, args.window)

    if args.rate:
        name, raw = args.rate
        score = clean_score(raw)
        if score is None:
            print("invalid score: %s (an integer 1-5 is required)" % raw, file=sys.stderr)
            return 1
        return rate_session(args.out_dir or out_dir_default, name, score,
                            args.note.strip(), versions, args.browser_threshold)

    if not args.paths:
        ap.error("give at least one .jsonl / directory, or --rename DIR")
    if not args.json and not args.md:
        args.md = True

    try:
        pricing = load_pricing(args.pricing)
    except (OSError, ValueError) as exc:
        pricing = {}
        print("WARN: no usable pricing (%s): %s — all costs reported as 0.0"
              % (args.pricing, exc), file=sys.stderr)

    targets = collect_targets(args.paths)
    if not targets:
        print("no .jsonl found — pass the project folder (~/.claude/projects/<slug>/) or a "
              "<uuid>.jsonl file; a <uuid>/ folder holds only subagent transcripts",
              file=sys.stderr)
        return 1
    # 🔴 fork and origin yield a single record — PATTERNS «Resumed sessions»
    origins = []
    for p in targets:
        origin = chain_origin(p)
        if origin not in origins:
            origins.append(origin)
    targets = origins

    sessions = [analyze(p, pricing, args.ctx_warn, args.agents_dir,
                        args.as_model, args.rot_at, args.window,
                        versions, args.browser_threshold) for p in targets]
    sessions.sort(key=lambda s: s.get("started") or "")

    rating = load_rating(args.rating_file) if args.rating_file else None

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        used_rating = False
        for s in sessions:
            s["name"] = unique_name(args.out_dir, s)
            json_path = os.path.join(args.out_dir, s["name"] + ".json")
            stale_quality = drop_stale_records(args.out_dir, s["name"], s.get("session"),
                                               s.get("forked_to"))
            if rating and not used_rating and rating_matches(rating, s):
                s["quality"] = quality_of(rating)
                used_rating = True
            if "quality" not in s:
                # regeneration must not drop a score written earlier
                old = (read_record(json_path) or {}).get("quality") or stale_quality
                if old:
                    s["quality"] = old
            apply_quality_to_v17(s)
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
