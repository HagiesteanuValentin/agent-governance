#!/usr/bin/env python3
"""Idempotent patch: Fable 5.1 prices in pricing.json + separate 5m/1h billing in session_metrics.py.

No hardcoded prices: each model comes from --price.
  --price NAME=input,output,cache_read,cache_write_5m,cache_write   (repeatable)
  --note TEXT   --date YYYY-MM-DD
  --pricing PATH  --metrics PATH  --only PATH  --dry-run
Exit != 0 if a file doesn't have exactly the expected number of matches.
"""
import argparse
import json
import os
import sys

# fiecare regula: (eticheta, ancora, inlocuire, marker-de-deja-aplicat)
RULES = [
    (
        "cost_of-5m",
        "def cost_of(counts, rates):\n"
        "    total = 0.0\n"
        "    for ck, rk in COST_KEYS:\n"
        "        total += counts.get(ck, 0) * float(rates.get(rk, 0.0)) / 1_000_000.0\n"
        "    return round(total, 4)\n",
        "def cost_of(counts, rates):\n"
        "    total = 0.0\n"
        "    for ck, rk in COST_KEYS:\n"
        "        total += counts.get(ck, 0) * float(rates.get(rk, 0.0)) / 1_000_000.0\n"
        "    # \U0001f534 cache_creation is the total; the 5m portion is re-taxed at cache_write_5m"
        " \u2014 DECIZII \u00abv1.8 \u2014 Fable 5.1 pricing\u00bb\n"
        "    n5m = counts.get(\"cache_creation_5m\", 0)\n"
        "    if n5m:\n"
        "        r_1h = float(rates.get(\"cache_write\", 0.0))\n"
        "        r_5m = float(rates.get(\"cache_write_5m\", r_1h))\n"
        "        total += n5m * (r_5m - r_1h) / 1_000_000.0\n"
        "    return round(total, 4)\n",
        "cache_creation_5m\", 0)\n    if n5m:",
    ),
    (
        "zeros",
        '    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "messages": 0}\n',
        '    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,\n'
        '            "cache_creation_5m": 0, "messages": 0}\n',
        '"cache_creation_5m": 0, "messages": 0}',
    ),
    (
        "add_usage+cc5m",
        'def add_usage(acc, usage):\n',
        'def cc_5m(usage):\n'
        '    cc = usage.get("cache_creation")\n'
        '    return (cc.get("ephemeral_5m_input_tokens") or 0) if isinstance(cc, dict) else 0\n'
        '\n'
        '\n'
        'def add_usage(acc, usage):\n',
        "def cc_5m(usage):",
    ),
    (
        "add_usage-body",
        '    acc["cache_creation"] += usage.get("cache_creation_input_tokens") or 0\n',
        '    acc["cache_creation"] += usage.get("cache_creation_input_tokens") or 0\n'
        '    acc["cache_creation_5m"] += cc_5m(usage)\n',
        'acc["cache_creation_5m"] += cc_5m(usage)',
    ),
    (
        "calls-dict",
        '            "cache_creation": usage.get("cache_creation_input_tokens") or 0,\n'
        '            "output": usage.get("output_tokens") or 0,\n',
        '            "cache_creation": usage.get("cache_creation_input_tokens") or 0,\n'
        '            "cache_creation_5m": cc_5m(usage),\n'
        '            "output": usage.get("output_tokens") or 0,\n',
        '"cache_creation_5m": cc_5m(usage),',
    ),
    (
        "turn_cost",
        '                    "cache_creation": call["cache_creation"]},\n',
        '                    "cache_creation": call["cache_creation"],\n'
        '                    "cache_creation_5m": call.get("cache_creation_5m", 0)},\n',
        '"cache_creation_5m": call.get("cache_creation_5m", 0)},',
    ),
    (
        "totals-keys",
        '        for k in ("input", "output", "cache_read", "cache_creation", "messages"):\n',
        '        for k in ("input", "output", "cache_read", "cache_creation",\n'
        '                  "cache_creation_5m", "messages"):\n',
        '                  "cache_creation_5m", "messages"):',
    ),
    (
        "cf-rates",
        '    r_cw = float(rates.get("cache_write", 0.0))\n',
        '    r_cw = float(rates.get("cache_write", 0.0))\n'
        '    r_cw5 = float(rates.get("cache_write_5m", r_cw))\n'
        '\n'
        '    def cw_cost(call, tokens):\n'
        '        # \U0001f534 the 5m portion is taxed at r_cw5, proportional to the call'
        ' — DECIZII «v1.8 — Fable 5.1 pricing»\n'
        '        total = call.get("cache_creation") or 0\n'
        '        if not total or not tokens:\n'
        '            return 0.0\n'
        '        share5 = min(call.get("cache_creation_5m", 0), total) * tokens / total\n'
        '        return share5 * r_cw5 + (tokens - share5) * r_cw\n',
        "def cw_cost(call, tokens):",
    ),
    (
        "cf-floor",
        '        floor += (c["output"] * r_out + c["input"] * r_in\n'
        '                  + c["cache_read"] * r_cr + c["cache_creation"] * r_cw) / 1e6\n',
        '        floor += (c["output"] * r_out + c["input"] * r_in\n'
        '                  + c["cache_read"] * r_cr + cw_cost(c, c["cache_creation"])) / 1e6\n',
        'cw_cost(c, c["cache_creation"])) / 1e6',
    ),
    (
        "cf-boot",
        '            floor += (c["output"] * r_out + inp * r_in + crd * r_cr'
        ' + ccr * r_cw) / 1e6\n',
        '            floor += (c["output"] * r_out + inp * r_in + crd * r_cr\n'
        '                      + cw_cost(c, ccr)) / 1e6\n',
        'cw_cost(c, ccr)) / 1e6',
    ),
    (
        "cf-realistic",
        '        realistic += (c["output"] * r_out + max(ctx_cf - cc_net, 0) * r_cr\n'
        '                      + cc_net * r_cw) / 1e6\n',
        '        realistic += (c["output"] * r_out + max(ctx_cf - cc_net, 0) * r_cr\n'
        '                      + cw_cost(c, cc_net)) / 1e6\n',
        'cw_cost(c, cc_net)) / 1e6',
    ),
    (
        "agg-tolerant",
        "        for k in agg:\n            agg[k] += t[k]\n",
        "        for k in agg:\n            agg[k] += t.get(k, 0)\n",
        "agg[k] += t.get(k, 0)",
    ),
]


def parse_price(spec):
    name, _, vals = spec.partition("=")
    parts = [v.strip() for v in vals.split(",")]
    if not name or len(parts) != 5:
        raise SystemExit("--price %s: expected NAME=input,output,cache_read,"
                         "cache_write_5m,cache_write" % spec)
    keys = ("input", "output", "cache_read", "cache_write_5m", "cache_write")
    return name, {k: float(v) for k, v in zip(keys, parts)}


def parse_extra(spec):
    name, _, rest = spec.partition("=")
    key, _, val = rest.partition(":")
    if not name or not key or not val:
        raise SystemExit("--extra %s: expected NAME=KEY:VALUE" % spec)
    return name, key, float(val)


def patch_pricing(path, prices, extras, note, date, dry_run):
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    before = json.dumps(doc, sort_keys=True)
    hits = 0
    for name, rates in prices.items():
        cur = doc["models"].get(name)
        if cur != rates:
            hits += 1
        doc["models"][name] = rates
    for name, key, val in extras:
        doc["models"].setdefault(name, {})[key] = val
    for name, rates in doc["models"].items():
        if "cache_write_5m" not in rates:
            print("  ! %s: no cache_write_5m (not given in --price)" % name)
    if note:
        doc["_note"] = note
    if date:
        doc["_updated"] = date
    after = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    changed = json.dumps(json.loads(after), sort_keys=True) != before
    print("%s: %d modele scrise, schimbat=%s" % (path, hits, changed))
    if changed and not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(after)
    return changed


def patch_metrics(path, dry_run):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    applied, skipped, errors = 0, 0, []
    for label, anchor, repl, marker in RULES:
        if marker in src:
            skipped += 1
            continue
        n = src.count(anchor)
        if n != 1:
            errors.append("%s: %d potriviri (astept 1)" % (label, n))
            continue
        src = src.replace(anchor, repl, 1)
        applied += 1
        print("  + %s" % label)
    print("%s: %d applied, %d already present, %d errors" %
          (path, applied, skipped, len(errors)))
    for e in errors:
        print("  ! %s" % e)
    if errors:
        return None
    if applied and not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
    return applied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pricing")
    ap.add_argument("--metrics")
    ap.add_argument("--price", action="append", default=[])
    ap.add_argument("--extra", action="append", default=[],
                    help="informative field: NAME=KEY:VALUE (unused by the analyzer)")
    ap.add_argument("--note", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    prices = dict(parse_price(s) for s in args.price)
    targets = [t for t in (args.pricing, args.metrics) if t]
    if args.only:
        targets = [t for t in targets if os.path.abspath(t) == os.path.abspath(args.only)]
        if not targets:
            raise SystemExit("--only %s nu e printre tinte" % args.only)

    rc = 0
    for t in targets:
        if t == args.pricing:
            if not prices:
                raise SystemExit("pricing.json without --price")
            patch_pricing(t, prices, [parse_extra(e) for e in args.extra],
                          args.note, args.date, args.dry_run)
        else:
            if patch_metrics(t, args.dry_run) is None:
                rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
