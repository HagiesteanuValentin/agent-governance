#!/usr/bin/env python3
"""Per-cell metrics for bench-scripter from subagent transcripts."""
import argparse
import glob
import json
import os
import re
import statistics
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from session_metrics import cost_of, load_pricing, rates_for  # noqa: E402

CELL_RE = re.compile(r"Director de lucru: (\S*/bench-scripter)/(T\d+)/cell-scripter-(s55-medium|s55-high|o55-low)-(\d+)")
VERIFY_RE = re.compile(r"node (\./)?scripts/")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def first_user_text(rec):
    c = rec.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in c or [] if isinstance(b, dict))


def parse(path, pricing, results_root):
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
    first = next((r for r in recs if r.get("type") == "user"), None)
    m = CELL_RE.search(first_user_text(first)) if first else None
    if not m:
        return None
    T, arm, run = m.group(2), m.group(3), int(m.group(4))
    model, times, usage, tool_ids = None, [], {}, {}
    for r in recs:
        if r.get("timestamp"):
            times.append(ts(r["timestamp"]))
        if r.get("type") != "assistant":
            continue
        msg = r.get("message", {})
        model = model or msg.get("model")
        if msg.get("id") and msg.get("usage"):
            prev = usage.get(msg["id"], (None, {}))[1]
            merged = {k: max(prev.get(k) or 0, v) if isinstance(v, int) else v
                      for k, v in msg["usage"].items()}
            usage[msg["id"]] = (msg.get("model"), merged)
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tool_ids[b["id"]] = b
    tools = list(tool_ids.values())
    tok = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    cost = 0.0
    for mdl, u in usage.values():
        c = {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
             "cache_read": u.get("cache_read_input_tokens") or 0,
             "cache_creation": u.get("cache_creation_input_tokens") or 0}
        for k in tok:
            tok[k] += c[k]
        cost += cost_of(c, rates_for(pricing, mdl))
    vp, reason = None, None
    jp = os.path.join(results_root, T, "cell-scripter-%s-%d.json" % (arm, run))
    if os.path.exists(jp):
        with open(jp, encoding="utf-8") as fh:
            v = json.load(fh)
        vp = bool(v.get("pass"))
        reason = next((c.get("criteriu") for c in v.get("criterii", []) if not c.get("pass")), None)
    return {
        "T": T, "arm": arm, "run": run, "model": model,
        "duration_s": round(max(times) - min(times)) if times else 0,
        "tool_calls": len(tools),
        "verify_calls": sum(1 for b in tools if b.get("name") == "Bash"
                            and VERIFY_RE.search(str(b.get("input", {}).get("command", "")))),
        "edits": sum(1 for b in tools if b.get("name") in ("Edit", "Write")),
        "input_tokens": tok["input"], "output_tokens": tok["output"],
        "cache_read_tokens": tok["cache_read"], "cache_creation_tokens": tok["cache_creation"],
        "cost_usd": round(cost, 4), "verify_pass": vp, "fail_reason": reason,
        "transcript": os.path.basename(path),
    }


def row(cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


def render(rows):
    h1 = ["T", "arm", "run", "model", "dur_s", "tools", "verify", "edits", "in", "out",
          "cache_r", "cache_w", "cost", "pass", "fail_reason"]
    out = ["# bench-scripter metrics", "", row(h1), row(["---"] * len(h1))]
    for r in rows:
        out.append(row([r["T"], r["arm"], r["run"], r["model"], r["duration_s"], r["tool_calls"],
                        r["verify_calls"], r["edits"], r["input_tokens"], r["output_tokens"],
                        r["cache_read_tokens"], r["cache_creation_tokens"], "%.2f" % r["cost_usd"],
                        {True: "PASS", False: "FAIL", None: "?"}[r["verify_pass"]],
                        r["fail_reason"] or ""]))
    h2 = ["T", "arm", "n", "med dur_s", "med cost", "med verify", "sum cost", "PASS"]
    out += ["", "## T x arm", "", row(h2), row(["---"] * len(h2))]
    groups = {}
    for r in rows:
        groups.setdefault((r["T"], r["arm"]), []).append(r)
    for (T, arm), g in groups.items():
        out.append(row([T, arm, len(g), statistics.median(x["duration_s"] for x in g),
                        "%.2f" % statistics.median(x["cost_usd"] for x in g),
                        statistics.median(x["verify_calls"] for x in g),
                        "%.2f" % sum(x["cost_usd"] for x in g),
                        "%d/%d" % (sum(1 for x in g if x["verify_pass"]), len(g))]))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subagents-dir", required=True)
    ap.add_argument("--results-root", required=True)
    ap.add_argument("--pricing", default=os.path.join(ROOT, "tools", "pricing.json"))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--expected", type=int, default=0)
    a = ap.parse_args()
    pricing = load_pricing(a.pricing)
    rows = [r for p in sorted(glob.glob(os.path.join(a.subagents_dir, "agent-*.jsonl")))
            for r in [parse(p, pricing, a.results_root)] if r]
    rows.sort(key=lambda r: (int(r["T"][1:]), r["arm"], r["run"]))
    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "metrics.md"), "w", encoding="utf-8") as fh:
        fh.write(render(rows))
    print("cells: %d" % len(rows))
    if a.expected and len(rows) != a.expected:
        print("expected %d" % a.expected, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
