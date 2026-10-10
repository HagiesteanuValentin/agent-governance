#!/usr/bin/env python3
"""Usage: collect.py <launch-log.md> <root> [--projects-dir D] [--agents-dir D] [--only CELL] [--dry-run] — see README.md"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime


def find_transcript(projects, agent_id):
    pats = [os.path.join(projects, "*", "subagents", "agent-%s*.jsonl" % agent_id),
            os.path.join(projects, "*", "*", "subagents", "agent-%s*.jsonl" % agent_id)]
    hits = sorted({p for pat in pats for p in glob.glob(pat)})
    return hits


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def final_text(assistants):
    for r in reversed(assistants):
        msg = r.get("message", {})
        for b in reversed(msg.get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SubagentHandback":
                return str((b.get("input") or {}).get("message", ""))
        texts = [b.get("text", "") for b in msg.get("content") or []
                 if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()]
        if texts:
            return "\n".join(texts)
    return ""


def parse(path):
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
    times = [ts(r["timestamp"]) for r in recs if r.get("timestamp")]
    assistants = [r for r in recs if r.get("type") == "assistant" and isinstance(r.get("message"), dict)]
    usage = {}
    for r in assistants:
        msg = r["message"]
        if msg.get("id") and msg.get("usage"):
            prev = usage.get(msg["id"], (None, {}))[1]
            merged = {k: max(prev.get(k) or 0, v) if isinstance(v, int) else v for k, v in msg["usage"].items()}
            usage[msg["id"]] = (msg.get("model"), merged)
    by_model, tok, peak = {}, {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}, 0
    for mdl, u in usage.values():
        c = {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
             "cache_read": u.get("cache_read_input_tokens") or 0,
             "cache_creation": u.get("cache_creation_input_tokens") or 0}
        agg = by_model.setdefault(mdl or "?", {k: 0 for k in tok})
        for k in tok:
            tok[k] += c[k]
            agg[k] += c[k]
        peak = max(peak, c["input"] + c["cache_read"] + c["cache_creation"])
    models = sorted({r["message"].get("model") for r in assistants
                     if r["message"].get("model") and r["message"].get("model") != "<synthetic>"})
    meta = {"turns": len(usage), "tokens": tok, "usage_by_model": by_model, "peak_context": peak,
            "duration_s": round(max(times) - min(times)) if times else 0, "models": models,
            "tool_calls": sum(1 for r in assistants for b in r["message"].get("content") or []
                              if isinstance(b, dict) and b.get("type") == "tool_use")}
    return meta, final_text(assistants)


ROLES = ("explorer-max", "explorer", "scribe")
LOG_RE = re.compile(r"^(cell-\S+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(OK|FAIL)\s*$")


def parse_log_line(ln):
    m = LOG_RE.match(ln.strip().strip("|`-* ").replace("`", ""))
    if not m:
        return None
    agent, task, run, agent_id, start, end, status = m.groups()
    role = next((r for r in ROLES if agent.startswith("cell-%s-" % r)), None)
    if not role:
        return None
    return {"agent": agent, "role": role, "arm": agent[len("cell-%s-" % role):], "task": task,
            "run": int(run), "agent_id": agent_id, "start": start, "end": end, "launch_status": status}


def declared_model(agents_dir, agent):
    try:
        text = open(os.path.join(agents_dir, agent + ".md"), encoding="utf-8").read()
    except OSError:
        return None, None
    fm = text.split("---", 2)[1] if text.startswith("---") else ""
    get = lambda k: next((l.split(":", 1)[1].strip() for l in fm.splitlines() if l.startswith(k + ":")), None)
    return get("model"), get("effort")


def write_if_changed(path, text, dry):
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if old == text:
        return False
    if not dry:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("root")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--agents-dir", default=os.path.expanduser("~/.claude/agents"))
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    rows, bad, changed, skipped = 0, 0, 0, 0
    for ln in open(a.log, encoding="utf-8"):
        e = parse_log_line(ln)
        if not e:
            if re.search(r"^\W*cell-\S+.*\bFAIL\b", ln):
                print("SKIP FAIL row without agentId: %s" % ln.strip(), file=sys.stderr)
            skipped += ln.strip() != ""
            continue
        name = "%s-%s-%d" % (e["task"], e["arm"], e["run"])
        if a.only and a.only != name:
            continue
        rows += 1
        cell = os.path.join(root, e["role"], name)
        if not os.path.isdir(cell):
            print("NO_CELL %s" % cell); bad += 1; continue
        hits = find_transcript(a.projects_dir, e["agent_id"])
        if len(hits) != 1:
            print("NO_TRANSCRIPT %s %s (%d hits)" % (name, e["agent_id"], len(hits))); bad += 1; continue
        declared, effort = declared_model(a.agents_dir, e["agent"])
        meta, report = parse(hits[0])
        mismatch = [m for m in meta["models"] if m != declared] or ([] if meta["models"] else ["<none>"])
        meta = {"cell": name, "agent": e["agent"], "agent_id": e["agent_id"], "transcript": hits[0],
                "model_declared": declared, "effort_declared": effort, "launch": e,
                "status": "MODEL_MISMATCH" if mismatch else "OK", **meta}
        n = write_if_changed(os.path.join(cell, "report.md"), report.rstrip("\n") + "\n", a.dry_run)
        n += write_if_changed(os.path.join(cell, "meta.json"),
                              json.dumps(meta, indent=1, ensure_ascii=False) + "\n", a.dry_run)
        changed += n
        print("%s %s turns=%d out=%d peak=%d report=%dB models=%s%s%s" % (
            meta["status"], meta["cell"], meta["turns"], meta["tokens"]["output"], meta["peak_context"],
            len(report), ",".join(meta["models"]), " files_changed=%d" % n,
            " (dry-run)" if a.dry_run else ""))
        if mismatch:
            bad += 1
    print("rows=%d problems=%d files_changed=%d other_lines_skipped=%d" % (rows, bad, changed, skipped))
    return 1 if bad or not rows else 0


if __name__ == "__main__":
    sys.exit(main())
