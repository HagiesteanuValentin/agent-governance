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

DEFAULT_ROOT = os.environ.get("BENCH_ROOT") or os.path.expanduser("~/workflow/experimente/bench-scripter")
DEFAULT_ARMS = "o55-low s55-medium s55-high"
VERIFY_RE = re.compile(r"node (\./)?scripts/")
TASK_SCRIPT = {"T1": "scripts/verify-studii-caz.mjs", "T2": "scripts/verifica-produs.mjs",
               "T3": "scripts/verifica-index-miscare.mjs"}
FULL_FLAGS = {"--url", "--port", "--has", "--crop"}
SEG_SPLIT = re.compile(r"&&|\|\||[;|\n&]")


def cell_re(arms):
    alt = "|".join(re.escape(a) for a in sorted(arms, key=len, reverse=True))
    return re.compile(r"Director de lucru: (\S*)/(T\d+)/cell-scripter-(%s)-(\d+)" % alt)


def script_runs(cmd, script):
    full = partial = 0
    name = os.path.basename(script)
    for seg in SEG_SPLIT.split(cmd):
        toks = seg.split()
        for i, t in enumerate(toks):
            if os.path.basename(t) != "node":
                continue
            rest = toks[i + 1:]
            node_flags = []
            while rest and rest[0].startswith("-"):
                node_flags.append(rest.pop(0))
            if not rest or os.path.basename(rest[0].strip("'\"")) != name:
                continue
            if "--check" in node_flags or "-c" in node_flags:
                continue
            flags = [a.split("=", 1)[0] for a in rest[1:] if a.startswith("-") and not a[1:2].isdigit()]
            if all(f in FULL_FLAGS for f in flags):
                full += 1
            else:
                partial += 1
    return full, partial


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def first_user_text(rec):
    c = rec.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in c or [] if isinstance(b, dict))


def parse(path, pricing, results_root, cre):
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
    first = next((r for r in recs if r.get("type") == "user"), None)
    m = cre.search(first_user_text(first)) if first else None
    if not m or os.path.normpath(os.path.expanduser(m.group(1).lstrip("`'\""))) != os.path.normpath(results_root):
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
    cost, peak = 0.0, 0
    for mdl, u in usage.values():
        c = {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
             "cache_read": u.get("cache_read_input_tokens") or 0,
             "cache_creation": u.get("cache_creation_input_tokens") or 0}
        for k in tok:
            tok[k] += c[k]
        peak = max(peak, c["input"] + c["cache_read"] + c["cache_creation"])
        cost += cost_of(c, rates_for(pricing, mdl))
    vp, reason = None, None
    jp = os.path.join(results_root, T, "cell-scripter-%s-%d.json" % (arm, run))
    if os.path.exists(jp):
        with open(jp, encoding="utf-8") as fh:
            v = json.load(fh)
        vp = bool(v.get("pass"))
        reason = next((c.get("criteriu") for c in v.get("criterii", []) if not c.get("pass")), None)
    full = partial = 0
    for b in tools:
        if b.get("name") == "Bash":
            f, p = script_runs(str(b.get("input", {}).get("command", "")), TASK_SCRIPT[T])
            full, partial = full + f, partial + p
    return {
        "T": T, "arm": arm, "run": run, "model": model,
        "duration_s": round(max(times) - min(times)) if times else 0,
        "tool_calls": len(tools),
        "verify_calls": sum(1 for b in tools if b.get("name") == "Bash"
                            and VERIFY_RE.search(str(b.get("input", {}).get("command", "")))),
        "full_runs": full, "partial_runs": partial, "peak_context": peak,
        "edits": sum(1 for b in tools if b.get("name") in ("Edit", "Write")),
        "input_tokens": tok["input"], "output_tokens": tok["output"],
        "cache_read_tokens": tok["cache_read"], "cache_creation_tokens": tok["cache_creation"],
        "cost_usd": round(cost, 4), "verify_pass": vp, "fail_reason": reason,
        "transcript": os.path.basename(path),
    }


def row(cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


def render(rows):
    h1 = ["T", "arm", "run", "model", "dur_s", "tools", "verify", "full_runs", "partial",
          "peak_ctx", "edits", "in", "out", "cache_r", "cache_w", "cost", "pass", "fail_reason"]
    out = ["# bench-scripter metrics", "", row(h1), row(["---"] * len(h1))]
    for r in rows:
        out.append(row([r["T"], r["arm"], r["run"], r["model"], r["duration_s"], r["tool_calls"],
                        r["verify_calls"], r["full_runs"], r["partial_runs"], r["peak_context"],
                        r["edits"], r["input_tokens"], r["output_tokens"],
                        r["cache_read_tokens"], r["cache_creation_tokens"], "%.2f" % r["cost_usd"],
                        {True: "PASS", False: "FAIL", None: "?"}[r["verify_pass"]],
                        r["fail_reason"] or ""]))
    h2 = ["T", "arm", "n", "med dur_s", "med cost", "med verify", "med full_runs",
          "max peak_ctx", "sum cost", "PASS"]
    out += ["", "## T x arm", "", row(h2), row(["---"] * len(h2))]
    groups = {}
    for r in rows:
        groups.setdefault((r["T"], r["arm"]), []).append(r)
    for (T, arm), g in groups.items():
        out.append(row([T, arm, len(g), statistics.median(x["duration_s"] for x in g),
                        "%.2f" % statistics.median(x["cost_usd"] for x in g),
                        statistics.median(x["verify_calls"] for x in g),
                        statistics.median(x["full_runs"] for x in g),
                        max(x["peak_context"] for x in g),
                        "%.2f" % sum(x["cost_usd"] for x in g),
                        "%d/%d" % (sum(1 for x in g if x["verify_pass"]), len(g))]))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subagents-dir", required=True, action="append")
    ap.add_argument("--results-root", default=DEFAULT_ROOT)
    ap.add_argument("--arms", default=DEFAULT_ARMS)
    ap.add_argument("--pricing", default=os.path.join(ROOT, "tools", "pricing.json"))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--expected", type=int, default=0)
    a = ap.parse_args()
    pricing = load_pricing(a.pricing)
    cre = cell_re(a.arms.split())
    root = os.path.expanduser(a.results_root)
    paths = sorted(p for d in a.subagents_dir for p in glob.glob(os.path.join(d, "agent-*.jsonl")))
    rows = [r for p in paths for r in [parse(p, pricing, root, cre)] if r]
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
