#!/usr/bin/env python3
"""Compare cell transcripts by context band and aggregate them across runs.

Input: subagent transcript dirs (<session>/subagents/), optional results dir with
`<cell>-r<k>.json` checker output. Output: --md, --json, --out-dir. Stdlib only.
"""

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from session_metrics import (VERIFY_TOKENS, add_usage, blocks, cost_of, dur,  # noqa: E402
                             load_pricing, rates_for, read_lines, span_s,
                             subagent_meta, tok, zeros)

HERE = os.path.dirname(os.path.abspath(__file__))

# 🔴 union of VERIF (hooks/context-agent.sh) + VERIFY_TOKENS — DECIZII «verify_calls în cell_metrics»
HOOK_VERIF = (r"astro check|npm run build|npm test|vitest|pytest"
              r"|verifica-[\w-]+\.mjs|verify-")
VERIFY_RE = re.compile(HOOK_VERIF + "|" + "|".join(re.escape(t) for t in VERIFY_TOKENS),
                       re.I)

EFFORT_RE = re.compile(r"(xhigh|x-high|extra-high|veryhigh|very-high|high|medium|low)", re.I)
VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")
BANDS = ((0, 50_000), (50_000, 100_000), (100_000, 150_000), (150_000, 200_000),
         (200_000, None))
STATUSES = ("OK", "FAIL", "FORCED", "NOT_RUN_REPORTED", "NOT_RUN_SILENT", "SILENT_DELETE")
FIX_TOOLS = ("Edit", "Write", "NotebookEdit")

RUN_NUM = ("api_calls", "tool_calls", "tool_errors", "edits", "reads", "rereads",
           "verify_calls", "output_tokens", "ctx_peak", "ctx_final", "ctx_first_edit",
           "duration_s", "cost_usd", "report_chars", "items_ok", "usd_per_ok_item")
BAND_NUM = ("calls", "errors", "error_rate", "edits", "reads", "rereads",
            "output_per_call", "usd_per_call")


def band_label(lo, hi):
    if hi is None:
        return "%dk+" % (lo // 1000)
    return "%d-%dk" % (lo // 1000, hi // 1000)


def band_of(ctx):
    for lo, hi in BANDS:
        if ctx >= lo and (hi is None or ctx < hi):
            return band_label(lo, hi)
    return band_label(*BANDS[-1])


def new_band():
    return {"calls": 0, "errors": 0, "edits": 0, "reads": 0, "rereads": 0,
            "output": 0, "cost_usd": 0.0}


def effort_of(name, fallback):
    m = EFFORT_RE.search(name or "")
    if m:
        return m.group(1).lower().replace("-", "")
    return fallback or "?"


def cc_version(results_dir, fallback):
    if results_dir:
        path = os.path.join(results_dir, "env.txt")
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            raw = ""
        m = VERSION_RE.search(raw)
        if m:
            return m.group(1)
    return fallback or "?"


def parse_cell(path, pricing):
    """One transcript -> per-run metrics + per-band buckets."""
    groups, order = {}, []
    tool_call = {}          # tool_use_id -> group id
    reads = collections.Counter()
    tools = collections.Counter()
    first_ts = last_ts = None
    version = None
    effort_field = None
    final_text = ""
    errors_by_gid = collections.Counter()

    for obj in read_lines(path):
        ts = obj.get("timestamp")
        if isinstance(ts, str):
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts
        if version is None and isinstance(obj.get("version"), str):
            version = obj["version"]
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}

        for b in blocks(msg):
            if b.get("type") == "tool_result" and b.get("is_error"):
                tid = b.get("tool_use_id")
                if isinstance(tid, str) and tid in tool_call:
                    errors_by_gid[tool_call[tid]] += 1

        if obj.get("type") != "assistant":
            continue
        if effort_field is None and isinstance(obj.get("effort"), str):
            effort_field = obj["effort"]
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        gid = msg.get("id") or obj.get("uuid")
        grp = groups.get(gid)
        if grp is None:
            grp = groups[gid] = {"usage": dict(usage), "model": msg.get("model") or "?",
                                 "at": ts, "tools": [], "edits": 0, "reads": 0,
                                 "rereads": 0, "verify": 0, "texts": []}
            order.append(gid)
        else:
            grp["usage"]["output_tokens"] = max(grp["usage"].get("output_tokens") or 0,
                                                usage.get("output_tokens") or 0)
        for b in blocks(msg):
            bt = b.get("type")
            if bt == "text" and isinstance(b.get("text"), str):
                grp["texts"].append(b["text"])
                final_text = b["text"]
            elif bt == "tool_use":
                name = b.get("name") or "?"
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                grp["tools"].append(name)
                tools[name] += 1
                if isinstance(b.get("id"), str):
                    tool_call[b["id"]] = gid
                if name == "Read":
                    fp = inp.get("file_path")
                    if isinstance(fp, str) and fp:
                        reads[fp] += 1
                        grp["reads"] += 1
                        if reads[fp] >= 2:
                            grp["rereads"] += 1
                elif name in FIX_TOOLS:
                    grp["edits"] += 1
                elif name == "Bash":
                    cmd = inp.get("command")
                    if isinstance(cmd, str) and VERIFY_RE.search(cmd):
                        grp["verify"] += 1

    usage_all = zeros()
    bands = collections.OrderedDict((band_label(lo, hi), new_band()) for lo, hi in BANDS)
    models = collections.Counter()
    cost = 0.0
    peak = final_ctx = 0
    ctx_first_edit = None
    tool_calls = errors = edits = verify = rereads = 0

    for gid in order:
        grp = groups[gid]
        u = grp["usage"]
        add_usage(usage_all, u)
        models[grp["model"]] += 1
        ctx = ((u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
               + (u.get("cache_creation_input_tokens") or 0))
        out = u.get("output_tokens") or 0
        c = cost_of({"input": u.get("input_tokens") or 0, "output": out,
                     "cache_read": u.get("cache_read_input_tokens") or 0,
                     "cache_creation": u.get("cache_creation_input_tokens") or 0},
                    rates_for(pricing, grp["model"]))
        cost += c
        peak = max(peak, ctx)
        final_ctx = ctx
        if grp["edits"] and ctx_first_edit is None:
            ctx_first_edit = ctx
        err = errors_by_gid[gid]
        errors += err
        edits += grp["edits"]
        verify += grp["verify"]
        rereads += grp["rereads"]
        if grp["tools"]:
            tool_calls += 1
        bk = bands[band_of(ctx)]
        bk["calls"] += 1
        bk["errors"] += err
        bk["edits"] += grp["edits"]
        bk["reads"] += grp["reads"]
        bk["rereads"] += grp["rereads"]
        bk["output"] += out
        bk["cost_usd"] += c

    for bk in bands.values():
        n = bk["calls"] or 1
        bk["error_rate"] = round(bk["errors"] / float(n), 3)
        bk["output_per_call"] = round(bk["output"] / float(n))
        bk["usd_per_call"] = round(bk["cost_usd"] / float(n), 4)
        bk["cost_usd"] = round(bk["cost_usd"], 4)

    return {
        "transcript": path,
        "first_ts": first_ts, "last_ts": last_ts,
        "duration_s": round(span_s(first_ts, last_ts)),
        "models": sorted(models),
        "model_drift": len(models) >= 2,
        "version": version,
        "effort_field": effort_field,
        "api_calls": len(order),
        "tool_calls": tool_calls,
        "tools": dict(tools),
        "tool_errors": errors,
        "edits": edits,
        "reads": sum(reads.values()),
        "rereads": rereads,
        "reread_paths": sum(1 for n in reads.values() if n >= 2),
        "verify_calls": verify,
        "output_tokens": usage_all["output"],
        "ctx_peak": peak,
        "ctx_final": final_ctx,
        "ctx_first_edit": ctx_first_edit,
        "cost_usd": round(cost, 4),
        "report_chars": len(final_text),
        "final_text": final_text,
        "bands": bands,
    }


def read_result(results_dir, cell, k):
    """Checker JSON for one run -> (status, items_ok). Tolerant about its shape."""
    if not results_dir:
        return None, None
    path = os.path.join(results_dir, "%s-r%d.json" % (cell, k))
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None, None
    items = None
    status = None
    if isinstance(raw, dict):
        s = raw.get("status") or raw.get("result")
        if isinstance(s, str):
            status = s.strip().upper()
        for key in ("items", "results", "checks"):
            val = raw.get(key)
            if isinstance(val, list):
                items = val
                break
            if isinstance(val, dict):
                items = list(val.values())
                break
    elif isinstance(raw, list):
        items = raw
    ok = None
    if items is not None:
        ok = 0
        seen = []
        for it in items:
            st = None
            if isinstance(it, dict):
                st = it.get("status") or it.get("result")
                if st is None and isinstance(it.get("ok"), bool):
                    st = "OK" if it["ok"] else "FAIL"
            elif isinstance(it, str):
                st = it
            st = st.strip().upper() if isinstance(st, str) else "?"
            seen.append(st)
            if st == "OK":
                ok += 1
        if status is None:
            bad = [s for s in seen if s != "OK"]
            status = bad[0] if bad else "OK"
    if status is not None and status not in STATUSES:
        status = "?"
    return status, ok


def mean(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / float(len(values))


def aggregate(runs):
    out = {}
    for key in RUN_NUM:
        vals = [r.get(key) for r in runs if isinstance(r.get(key), (int, float))]
        if not vals:
            out[key] = {"mean": None, "min": None, "max": None}
            continue
        out[key] = {"mean": round(mean(vals), 4), "min": min(vals), "max": max(vals)}
    bands = {}
    for lo, hi in BANDS:
        lbl = band_label(lo, hi)
        bands[lbl] = {}
        for key in BAND_NUM:
            vals = [r["bands"][lbl].get(key) for r in runs]
            vals = [v for v in vals if isinstance(v, (int, float))]
            bands[lbl][key] = {"mean": round(mean(vals), 4) if vals else None,
                               "min": min(vals) if vals else None,
                               "max": max(vals) if vals else None}
    out["bands"] = bands
    return out


def fmt(v, nd=0):
    if v is None:
        return "-"
    if isinstance(v, float) and nd:
        return ("%%.%df" % nd) % v
    if isinstance(v, float):
        return "%d" % round(v)
    return str(v)


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def render_md(cells):
    out = ["# Cell metrics", "", "## Runs", ""]
    heads = ["cell", "run", "model", "drift", "cc", "effort", "calls", "tools",
             "tool err", "ctx peak", "ctx end", "ctx@1st edit", "out tok", "$",
             "durata", "E/W", "recitiri", "verify", "raport", "status", "$/item OK"]
    rows = []
    for cell, runs in cells.items():
        for r in runs:
            rows.append([cell, "r%d" % r["run"], ",".join(r["models"]) or "?",
                         "model_drift" if r["model_drift"] else "",
                         r["cc_version"], r["effort"], r["api_calls"], r["tool_calls"],
                         r["tool_errors"], tok(r["ctx_peak"]), tok(r["ctx_final"]),
                         tok(r["ctx_first_edit"]) if r["ctx_first_edit"] else "-",
                         tok(r["output_tokens"]), "%.4f" % r["cost_usd"],
                         dur(r["duration_s"]), r["edits"], r["rereads"],
                         r["verify_calls"], r["report_chars"],
                         r["status"] or "-",
                         "%.4f" % r["usd_per_ok_item"] if r.get("usd_per_ok_item") else "-"])
    out.append(table(heads, rows))

    out += ["", "## Context bands (mean per run)", ""]
    bheads = ["cell", "banda", "apeluri", "erori", "rata", "E/W", "Read", "recitiri",
              "out/apel", "$/apel"]
    brows = []
    for cell, runs in cells.items():
        agg = aggregate(runs)["bands"]
        for lo, hi in BANDS:
            lbl = band_label(lo, hi)
            a = agg[lbl]
            if not a["calls"]["mean"]:
                continue
            brows.append([cell, lbl, fmt(a["calls"]["mean"]), fmt(a["errors"]["mean"]),
                          fmt(a["error_rate"]["mean"], 3), fmt(a["edits"]["mean"]),
                          fmt(a["reads"]["mean"]), fmt(a["rereads"]["mean"]),
                          fmt(a["output_per_call"]["mean"]),
                          fmt(a["usd_per_call"]["mean"], 4)])
    out.append(table(bheads, brows))

    out += ["", "## Aggregate per cell (mean, min-max)", ""]
    keys = ["api_calls", "tool_errors", "edits", "rereads", "verify_calls",
            "output_tokens", "ctx_peak", "duration_s", "cost_usd", "report_chars"]
    aheads = ["cell", "rulari"] + keys
    arows = []
    for cell, runs in cells.items():
        agg = aggregate(runs)
        row = [cell, len(runs)]
        for k in keys:
            a = agg[k]
            nd = 4 if k == "cost_usd" else 0
            if a["mean"] is None:
                row.append("-")
            else:
                row.append("%s (%s-%s)" % (fmt(a["mean"], nd), fmt(a["min"], nd),
                                           fmt(a["max"], nd)))
        arows.append(row)
    out.append(table(aheads, arows))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subagents-dir", action="append", default=[], required=True)
    ap.add_argument("--agent-prefix", default="cell-")
    ap.add_argument("--first-run", type=int, default=1, help="eticheta r<k> a primei rulari gasite (lot nou = k)")
    ap.add_argument("--results-dir", default=None)
    ap.add_argument("--dump-reports", default=None)
    ap.add_argument("--exclude-agent", action="append", default=[],
                    help="id din numele agent-<id>.jsonl; repetabil")
    ap.add_argument("--min-calls", type=int, default=1,
                    help="rulari cu mai putine apeluri de unelte sunt sarite")
    ap.add_argument("--pricing", default=os.path.join(HERE, "pricing.json"))
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    pricing = load_pricing(args.pricing)
    excluded = set(args.exclude_agent)
    found = []
    for d in args.subagents_dir:
        d = os.path.abspath(os.path.expanduser(d))
        if not os.path.isdir(d):
            sys.stderr.write("nu e director: %s\n" % d)
            return 2
        for name in sorted(os.listdir(d)):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(d, name)
            agent_id = name[:-len(".jsonl")]
            if agent_id.startswith("agent-"):
                agent_id = agent_id[len("agent-"):]
            if agent_id in excluded:
                sys.stderr.write("sarit (--exclude-agent): %s\n" % name)
                continue
            meta = subagent_meta(path)
            cell = meta.get("agentType") or name[:-len(".jsonl")]
            if args.agent_prefix and not cell.startswith(args.agent_prefix):
                continue
            found.append((cell, path))

    if not found:
        sys.stderr.write("0 celule cu prefixul %r in %s\n"
                         % (args.agent_prefix, ", ".join(args.subagents_dir)))
        return 1

    parsed = collections.defaultdict(list)
    for cell, path in found:
        run = parse_cell(path, pricing)
        # 🔴 r<k> numbering happens after filtering — DECIZII «verify_calls in cell_metrics»
        if run["tool_calls"] < args.min_calls:
            sys.stderr.write("sarit (--min-calls %d): %s, %d apeluri de unelte\n"
                             % (args.min_calls, os.path.basename(path), run["tool_calls"]))
            continue
        parsed[cell].append(run)

    if not any(parsed.values()):
        sys.stderr.write("0 runs after filtering (--min-calls %d, --exclude-agent %s)\n"
                         % (args.min_calls, ",".join(sorted(excluded)) or "-"))
        return 1

    cells = collections.OrderedDict()
    for cell in sorted(parsed):
        runs = sorted(parsed[cell], key=lambda r: r["first_ts"] or "")
        out_runs = []
        for k, r in enumerate(runs, args.first_run):
            r["run"] = k
            r["cell"] = cell
            r["cc_version"] = cc_version(args.results_dir, r["version"])
            r["effort"] = effort_of(cell, r["effort_field"])
            status, ok = read_result(args.results_dir, cell, k)
            r["status"] = status
            r["items_ok"] = ok
            r["usd_per_ok_item"] = (round(r["cost_usd"] / ok, 4)
                                    if ok else None)
            out_runs.append(r)
        cells[cell] = out_runs

    if args.dump_reports:
        os.makedirs(args.dump_reports, exist_ok=True)
        n = 0
        for cell, runs in cells.items():
            for r in runs:
                p = os.path.join(args.dump_reports, "%s-r%d.md" % (cell, r["run"]))
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(r["final_text"] or "")
                n += 1
        sys.stderr.write("dump-reports: %d fisiere in %s\n" % (n, args.dump_reports))

    payload = {"cells": [
        {"cell": cell, "runs": [{k: v for k, v in r.items() if k != "final_text"}
                                for r in runs],
         "aggregate": aggregate(runs)}
        for cell, runs in cells.items()]}

    md = render_md(cells)
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, "cells.md"), "w", encoding="utf-8") as fh:
            fh.write(md)
        with open(os.path.join(args.out_dir, "cells.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    if args.md or not (args.json or args.out_dir):
        sys.stdout.write(md)
    if args.json:
        json.dump(payload, sys.stdout, indent=1, ensure_ascii=False)
        sys.stdout.write("\n")
    sys.stderr.write("%d celule, %d rulari\n"
                     % (len(cells), sum(len(v) for v in cells.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
