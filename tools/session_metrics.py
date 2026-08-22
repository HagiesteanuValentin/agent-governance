#!/usr/bin/env python3
"""Offline token-usage analyzer for Claude Code transcripts.

Input: session .jsonl files (~/.claude/projects/<slug>/<uuid>.jsonl) or directories.
Output: --json (machine-readable) and/or --md (summary + aggregate table). Stdlib only.
"""

import argparse
import collections
import json
import os
import sys

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
COST_KEYS = (("input", "input"), ("output", "output"),
             ("cache_read", "cache_read"), ("cache_creation", "cache_write"))


# ---------------------------------------------------------------- pricing

def load_pricing(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    models = raw.get("models", raw)
    return {k: v for k, v in models.items() if isinstance(v, dict)}


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


def text_len(value):
    """Character length of a tool_result content (str or list of blocks)."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        total = 0
        for b in value:
            if isinstance(b, dict):
                t = b.get("text")
                total += len(t) if isinstance(t, str) else len(json.dumps(b, ensure_ascii=False))
            elif isinstance(b, str):
                total += len(b)
        return total
    if value is None:
        return 0
    return len(json.dumps(value, ensure_ascii=False))


def zeros():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "messages": 0}


def add_usage(acc, usage):
    acc["input"] += usage.get("input_tokens") or 0
    acc["output"] += usage.get("output_tokens") or 0
    acc["cache_read"] += usage.get("cache_read_input_tokens") or 0
    acc["cache_creation"] += usage.get("cache_creation_input_tokens") or 0
    acc["messages"] += 1


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


def analyze(jsonl_path, pricing):
    per_model = collections.defaultdict(zeros)
    main = zeros()
    side = zeros()
    agents = {}
    tool_names = {}          # tool_use_id -> tool name
    tool_results = []        # (chars, tool_use_id)
    reads = collections.Counter()
    first_ts = last_ts = None

    for path, label in session_files(jsonl_path):
        # one API response spans several lines sharing a message.id: input/cache repeat
        # identically, but output_tokens is CUMULATIVE (1 -> 1 -> 163) -> take the last value
        groups = collections.OrderedDict()
        for obj in read_lines(path):
            ts = obj.get("timestamp")
            if isinstance(ts, str):
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

            msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
            kind = obj.get("type")

            for b in blocks(msg):
                bt = b.get("type")
                if bt == "tool_use":
                    if isinstance(b.get("id"), str):
                        tool_names[b["id"]] = b.get("name") or "?"
                    if b.get("name") == "Read":
                        inp = b.get("input")
                        fp = inp.get("file_path") if isinstance(inp, dict) else None
                        if isinstance(fp, str) and fp:
                            reads[fp] += 1
                elif bt == "tool_result":
                    tool_results.append((text_len(b.get("content")), b.get("tool_use_id")))

            if kind != "assistant":
                continue
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
                    "texts": [],
                }
            else:
                grp["usage"]["output_tokens"] = max(grp["usage"].get("output_tokens") or 0,
                                                    usage.get("output_tokens") or 0)
            for b in blocks(msg):
                if b.get("type") == "text" and isinstance(b.get("text"), str):
                    grp["texts"].append(b["text"])

        for grp in groups.values():
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

    out_total = totals["output"] or 1
    return {
        "session": os.path.basename(jsonl_path)[:-len(".jsonl")],
        "project": os.path.basename(os.path.dirname(jsonl_path)),
        "path": jsonl_path,
        "started": first_ts,
        "ended": last_ts,
        "totals": totals,
        "models": models_out,
        "main": main,
        "sidechains": side,
        "sidechain_output_pct": round(100.0 * side["output"] / out_total, 1),
        "agents": dict(sorted(agents.items(), key=lambda kv: -kv[1]["output_tokens"])),
        "top_tool_results": top_tools,
        "reread_files": rereads,
        "images": images,
    }


# ---------------------------------------------------------------- markdown

def fmt(n):
    return "{:,}".format(n).replace(",", ".")


def markdown(sessions):
    out = []
    for s in sessions:
        t = s["totals"]
        out.append("## %s  (%s)" % (s["session"], s["project"]))
        out.append("")
        out.append("- interval: %s -> %s" % (s["started"] or "?", s["ended"] or "?"))
        out.append("- assistant messages: %d (main %d / sidechain %d)"
                   % (t["messages"], s["main"]["messages"], s["sidechains"]["messages"]))
        out.append("- tokens: in %s | out %s | cache_read %s | cache_write %s"
                   % (fmt(t["input"]), fmt(t["output"]),
                      fmt(t["cache_read"]), fmt(t["cache_creation"])))
        out.append("- output in sidechains: %s (%.1f%%)"
                   % (fmt(s["sidechains"]["output"]), s["sidechain_output_pct"]))
        out.append("- estimated cost: $%.2f" % t["cost_usd"])
        out.append("")
        out.append("| model | in | out | cache_read | cache_write | $ |")
        out.append("|---|---:|---:|---:|---:|---:|")
        for m, r in s["models"].items():
            out.append("| %s | %s | %s | %s | %s | %.2f |"
                       % (m, fmt(r["input"]), fmt(r["output"]), fmt(r["cache_read"]),
                          fmt(r["cache_creation"]), r["cost_usd"]))
        out.append("")
        if s["agents"]:
            out.append("| agent | messages | output | final report (chars) |")
            out.append("|---|---:|---:|---:|")
            for name, a in s["agents"].items():
                out.append("| %s | %d | %s | %s |"
                           % (name, a["assistant_messages"],
                              fmt(a["output_tokens"]), fmt(a["final_text_chars"])))
            out.append("")
        if s["top_tool_results"]:
            out.append("Top 10 tool_results by size:")
            out.append("")
            out.append("| # | tool | chars |")
            out.append("|---:|---|---:|")
            for i, tr in enumerate(s["top_tool_results"], 1):
                out.append("| %d | %s | %s |" % (i, tr["tool"], fmt(tr["chars"])))
            out.append("")
        if s["reread_files"]:
            out.append("Files read more than once (Read):")
            out.append("")
            for r in s["reread_files"]:
                out.append("- %dx %s" % (r["reads"], r["path"]))
            out.append("")
        if s["images"]:
            out.append("Images read:")
            out.append("")
            for im in s["images"]:
                out.append("- %dx %s%s" % (im["reads"], im["path"],
                                           "  [downscaled]" if im["is_mic"] else ""))
            out.append("")

    out.append("## Aggregate")
    out.append("")
    out.append("| session | project | in | out | cache_read | cache_write | % out sidechain | $ |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|")
    agg = zeros()
    agg_cost = 0.0
    agg_side = 0
    for s in sessions:
        t = s["totals"]
        out.append("| %s | %s | %s | %s | %s | %s | %.1f%% | %.2f |"
                   % (s["session"][:8], s["project"], fmt(t["input"]), fmt(t["output"]),
                      fmt(t["cache_read"]), fmt(t["cache_creation"]),
                      s["sidechain_output_pct"], t["cost_usd"]))
        for k in agg:
            agg[k] += t[k]
        agg_cost += t["cost_usd"]
        agg_side += s["sidechains"]["output"]
    pct = 100.0 * agg_side / (agg["output"] or 1)
    out.append("| **TOTAL** | %d sessions | %s | %s | %s | %s | %.1f%% | %.2f |"
               % (len(sessions), fmt(agg["input"]), fmt(agg["output"]),
                  fmt(agg["cache_read"]), fmt(agg["cache_creation"]), pct, agg_cost))
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- cli

def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help=".jsonl session files or directories")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--md", action="store_true", help="Markdown output")
    ap.add_argument("--out", help="write to a file instead of stdout")
    ap.add_argument("--pricing", default=os.path.join(here, "pricing.json"))
    args = ap.parse_args(argv)

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

    sessions = [analyze(p, pricing) for p in targets]
    sessions.sort(key=lambda s: -s["totals"]["output"])

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
