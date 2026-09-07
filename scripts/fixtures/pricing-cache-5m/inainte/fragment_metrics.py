# fixture: fragments from tools/session_metrics.py, one per rule in pricing-cache-5m.py

def cost_of(counts, rates):
    total = 0.0
    for ck, rk in COST_KEYS:
        total += counts.get(ck, 0) * float(rates.get(rk, 0.0)) / 1_000_000.0
    return round(total, 4)


def zeros():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "messages": 0}


def add_usage(acc, usage):
    acc["input"] += usage.get("input_tokens") or 0
    acc["output"] += usage.get("output_tokens") or 0
    acc["cache_read"] += usage.get("cache_read_input_tokens") or 0
    acc["cache_creation"] += usage.get("cache_creation_input_tokens") or 0
    acc["messages"] += 1


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


def turn_cost(call, pricing):
    # 🔴 inherited turns were billed to the parent session — PATTERNS «Resumed sessions»
    if call.get("inherited"):
        return 0.0
    return cost_of({"input": call["input"], "output": call["output"],
                    "cache_read": call["cache_read"],
                    "cache_creation": call["cache_creation"]},
                   rates_for(pricing, call["model"]))


    totals: dict = zeros()
    models_out = {}
    for model, counts in sorted(per_model.items()):
        rates = rates_for(pricing, model)
        row = dict(counts)
        row["cost_usd"] = cost_of(counts, rates)
        models_out[model] = row
        for k in ("input", "output", "cache_read", "cache_creation", "messages"):
            totals[k] += counts[k]
    totals["cost_usd"] = round(sum(m["cost_usd"] for m in models_out.values()), 4)


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
