#!/usr/bin/env python3
"""Usage: metrics.py --results-root ABS [--arms ...] [--pricing P] [--out-dir D] — see README.md"""
import argparse
import glob
import json
import os
import re
import statistics
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))
from session_metrics import cost_of, load_pricing, rates_for  # noqa: E402

ROLES = ("explorer", "explorer-max", "scribe")
NUM = ("cost_usd", "duration_s", "turns", "tokens_in", "tokens_out", "cache_read", "peak_context")
SCORE_NUM = ("corect", "util")


def load_scores(root, role, task):
    sf = os.path.join(root, "audit", role, task, "scores.json")
    mf = os.path.join(root, "audit-mapping-%s-%s.json" % (role, task))
    if not (os.path.exists(sf) and os.path.exists(mf)):
        return {}
    letters = json.load(open(sf, encoding="utf-8")).get("letters", {})
    mapping = json.load(open(mf, encoding="utf-8"))
    return {mapping[l]["cell"]: s for l, s in letters.items() if l in mapping}


def cell_rows(root, arms, pricing):
    rows, missing = [], []
    alt = "|".join(re.escape(a) for a in sorted(arms, key=len, reverse=True))
    cre = re.compile(r"^(?P<task>.+)-(?P<arm>%s)-(?P<run>\d+)$" % alt)
    scores = {}
    for role in ROLES:
        for d in sorted(glob.glob(os.path.join(root, role, "*", ""))):
            cell = os.path.basename(d.rstrip("/"))
            m = cre.match(cell)
            if not m:
                continue
            mp = os.path.join(d, "meta.json")
            if not os.path.exists(mp):
                missing.append("%s/%s" % (role, cell))
                continue
            meta = json.load(open(mp, encoding="utf-8"))
            cost = sum(cost_of(c, rates_for(pricing, mdl)) for mdl, c in meta.get("usage_by_model", {}).items())
            unpriced = [mdl for mdl in meta.get("usage_by_model", {}) if mdl not in pricing]
            key = (role, m["task"])
            if key not in scores:
                scores[key] = load_scores(root, *key)
            sc = scores[key].get(cell, {})
            vj = os.path.join(d, "verify.json")
            verify = json.load(open(vj, encoding="utf-8")).get("pass") if os.path.exists(vj) else None
            t = meta.get("tokens", {})
            rows.append({
                "role": role, "task": m["task"], "arm": m["arm"], "run": int(m["run"]), "cell": cell,
                "status": meta.get("status"), "models": meta.get("models"), "unpriced": unpriced,
                "cost_usd": round(cost, 4), "duration_s": meta.get("duration_s", 0), "turns": meta.get("turns", 0),
                "tokens_in": t.get("input", 0), "tokens_out": t.get("output", 0), "cache_read": t.get("cache_read", 0),
                "peak_context": meta.get("peak_context", 0), "verify_pass": verify,
                "corect": sc.get("corect"), "util": sc.get("util"), "verdict": sc.get("verdict"),
                "false_facts": sc.get("false_facts"),
            })
    return rows, missing


def med(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    return {"median": statistics.median(vals), "min": min(vals), "max": max(vals)}


def aggregate(rows):
    groups = {}
    for r in rows:
        groups.setdefault((r["role"], r["task"], r["arm"]), []).append(r)
    out = []
    for (role, task, arm), g in sorted(groups.items()):
        a = {"role": role, "task": task, "arm": arm, "n": len(g)}
        for k in NUM + SCORE_NUM:
            a[k] = med([x[k] for x in g])
        a["inacceptabil"] = sum(1 for x in g if x["verdict"] == "inacceptabil")
        a["false_facts"] = sum(x["false_facts"] or 0 for x in g)
        a["verify_pass"] = "%d/%d" % (sum(1 for x in g if x["verify_pass"]), sum(1 for x in g if x["verify_pass"] is not None))
        a["model_mismatch"] = sum(1 for x in g if x["status"] != "OK")
        out.append(a)
    return out


def fmt(s, prec=0):
    if s is None:
        return "–"
    f = "%%.%df" % prec
    return "%s (%s–%s)" % (f % s["median"], f % s["min"], f % s["max"])


def render(agg, missing):
    h = ["role", "task", "arm", "n", "cost $", "dur s", "turns", "out tok", "peak ctx", "corect", "util",
         "inacc.", "false", "verify", "mismatch"]
    lines = ["# bench-haiku summary", "", "| " + " | ".join(h) + " |", "|" + "---|" * len(h)]
    for a in agg:
        lines.append("| " + " | ".join(str(x) for x in [
            a["role"], a["task"], a["arm"], a["n"], fmt(a["cost_usd"], 3), fmt(a["duration_s"]), fmt(a["turns"]),
            fmt(a["tokens_out"]), fmt(a["peak_context"]), fmt(a["corect"], 1), fmt(a["util"], 1),
            a["inacceptabil"], a["false_facts"], a["verify_pass"], a["model_mismatch"]]) + " |")
    lines += ["", "Values: median (min–max) per role × task × arm."]
    if missing:
        lines += ["", "Cells without meta.json: " + ", ".join(missing)]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", required=True)
    ap.add_argument("--arms", default=os.environ.get("ARMS", "s55-low s55-medium h55-medium h55-high"))
    ap.add_argument("--pricing", default=os.path.join(REPO, "tools", "pricing.json"))
    ap.add_argument("--out-dir")
    ap.add_argument("--expected", type=int, default=0)
    a = ap.parse_args()
    # 🔴 results root must be absolute — RETETE «Benchmark pe celule — capcane la rulare»
    if not os.path.isabs(a.results_root):
        print("--results-root must be absolute: %s" % a.results_root, file=sys.stderr)
        return 2
    rows, missing = cell_rows(a.results_root, a.arms.split(), load_pricing(a.pricing))
    agg = aggregate(rows)
    out = a.out_dir or a.results_root
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"cells": rows, "groups": agg, "missing_meta": missing}, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(render(agg, missing))
    unpriced = sorted({m for r in rows for m in r["unpriced"]})
    print("cells=%d groups=%d missing_meta=%d unpriced_models=%s -> %s/summary.{md,json}" % (
        len(rows), len(agg), len(missing), ",".join(unpriced) or "none", out))
    if a.expected and len(rows) != a.expected:
        print("expected %d cells" % a.expected, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
