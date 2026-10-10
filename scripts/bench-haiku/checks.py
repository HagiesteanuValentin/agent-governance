#!/usr/bin/env python3
"""Usage: checks.py <task-id> <cell> [--base REV] [--json OUT] — see README.md"""
import argparse
import json
import re
import subprocess
import sys

DIACRITICS = re.compile(r"[ăâîșțşţĂÂÎȘȚŞŢ]")
IGNORED = {"BRIEF.md", "report.md", "meta.json", "verify.json", "diff.patch"}
results = []


def check(name, ok, level="hard"):
    results.append({"check": name, "pass": bool(ok), "level": level})
    print("%s%s %s" % ("PASS" if ok else "FAIL", "" if level == "hard" else "(info)", name))


def git(cell, *args):
    return subprocess.run(["git", "-C", cell, *args], capture_output=True, text=True).stdout


def read(cell, rel):
    try:
        return open("%s/%s" % (cell, rel), encoding="utf-8").read()
    except OSError:
        return ""


def changed(cell, base):
    ch = set(git(cell, "diff", "--name-only", base).splitlines())
    ch |= set(git(cell, "ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(ch - IGNORED)


def scope(cell, base, allowed):
    extra = [c for c in changed(cell, base) if c not in allowed]
    check("only allowed files changed" + (" (extra: %s)" % ", ".join(extra) if extra else ""), not extra)


def section(text, heading, level="## "):
    lines = text.splitlines()
    try:
        i = lines.index(heading)
    except ValueError:
        return None
    j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith(level)), len(lines))
    return "\n".join(lines[i:j])


def items(sec):
    return len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*]) ", sec or ""))


R57_RO = "## r5–r7 — Opus 5.5 vs Opus 5, low/medium (22.09.2026)"
R57_EN = "## r5–r7 — Opus 5.5 vs Opus 5, low/medium (2026-09-22)"
ORCH = "## 2026-09-02 — orchestrator"


def t1(cell, base):
    f = "docs/experiments.md"
    old, new = git(cell, "show", "%s:%s" % (base, f)), read(cell, f)
    scope(cell, base, {f})
    lines = new.splitlines()
    check("lines 137-166 without diacritics", not any(DIACRITICS.search(l) for l in lines[136:166]))
    n_old = len(old.splitlines())
    check("line count %d within %d±2" % (len(lines), n_old), abs(len(lines) - n_old) <= 2)
    check("new EN title present, RO title gone", R57_EN in lines and R57_RO not in lines)
    sec = section(new, R57_EN) or ""
    check("translated section without diacritics", sec and not DIACRITICS.search(sec))
    check("bcb7075 / I7 / Lightbox kept", all(k in sec for k in ("bcb7075", "I7", "Lightbox")))
    oi, ni = old.find(R57_RO), new.find(R57_EN)
    check("text before section unchanged", oi >= 0 and ni >= 0 and old[:oi] == new[:ni])
    check("text from orchestrator heading on unchanged",
          ORCH in old and ORCH in new and old[old.index(ORCH):] == new[new.index(ORCH):])
    old_sec = section(old, R57_RO) or ""
    check("same number of table rows in section",
          sum(l.startswith("|") for l in old_sec.splitlines()) == sum(l.startswith("|") for l in sec.splitlines()),
          "info")


H_R8 = "## r8–r10 — complex task: Opus 5.5 low vs medium, auditor high vs medium (2026-09-23)"
H_SCR = "## scripter A/B — Sonnet 5 high vs Opus 5.5 low (2026-09-23)"


def t2(cell, base):
    f, s = "docs/experiments.md", "scripts/SCRIPTS.md"
    old, new = git(cell, "show", "%s:%s" % (base, f)), read(cell, f)
    scope(cell, base, {f, s})
    cnt = lambda t: len(re.findall(r"(?m)^## ", t))
    check("'^## ' count %d = base %d + 2" % (cnt(new), cnt(old)), cnt(new) == cnt(old) + 2)
    lines = new.splitlines()
    pos = [next((i for i, l in enumerate(lines) if l == h or (h == ORCH and l.startswith(h))), -1)
           for h in (R57_EN, H_R8, H_SCR, ORCH)]
    check("both new headings exact, between r5-r7 and orchestrator", -1 not in pos and pos == sorted(pos))
    block = ""
    if -1 not in pos and pos == sorted(pos):
        block = "\n".join(lines[pos[1]:pos[3]])
    check("new sections without diacritics", block and not DIACRITICS.search(block))
    check("rest of experiments.md unchanged", block and new.replace(block + "\n", "", 1) == old)
    row = [l for l in read(cell, s).splitlines() if l.startswith("|") and "verifica-complex.mjs" in l]
    check("SCRIPTS.md row for verifica-complex.mjs", len(row) == 1)
    for k in ("da90148", "0.358", "0.416", "12/12", "0.209", "0.338"):
        check("figure %s in new sections" % k, k in block, "info")


HANDOFF_HEADS = ["## Acum", "## Pista activă", "## ⏳ De validat pe viu", "## Următorii pași",
                 "## Capcane active", "## Blocat pe alții"]
T3_CODE = {"frontend/src/pages/comanda.astro", "frontend/functions/_shop/order-notify.ts",
           "frontend/src/components/order/PaymentMethod.astro", "scripts/verifica-stripe-comanda.mjs",
           "scripts/captura-element.mjs"}
RET_HEAD = "## Verificare plată card (Stripe, 25 sept. 2026)"


def t3(cell, base):
    old, new = git(cell, "show", "%s:HANDOFF.md" % base), read(cell, "HANDOFF.md")
    scope(cell, base, {"HANDOFF.md", "docs/INFRA.md", "docs/RETETE.md", "docs/PATTERNS.md",
                       "docs/DECIZII.md"} | T3_CODE)
    lines = new.splitlines()
    check("HANDOFF %d lines <= 60" % len(lines), 0 < len(lines) <= 60)
    hdr = [l for l in old.splitlines() if l.startswith("> Doar starea curentă")]
    check("header line '> Doar starea curentă' identical", hdr and hdr[0] in lines)
    pos = [lines.index(h) if h in lines else -1 for h in HANDOFF_HEADS]
    check("6 fixed headings present in order", -1 not in pos and pos == sorted(pos))
    check("trap 'Cheile Stripe sunt de TEST' removed", "Cheile Stripe sunt de TEST pe Production" not in new)
    check("live 3dbe912 / code 09f7678 in HANDOFF", "3dbe912" in new and "09f7678" in new)
    infra = section(read(cell, "docs/INFRA.md"), "## Stripe") or ""
    check("INFRA ## Stripe mentions rk_live_", "rk_live_" in infra)
    ret = section(read(cell, "docs/RETETE.md"), RET_HEAD)
    check("RETETE section exists", ret is not None)
    check("RETETE: 'niciodată pe main' removed", ret is not None and "niciodată pe `main`" not in ret)
    check("RETETE: live probe with cs_live_", ret is not None and "cs_live_" in ret)
    check("Următorii pași <= 5 items", items(section(new, "## Următorii pași")) <= 5, "info")
    check("Capcane active <= 3 items", items(section(new, "## Capcane active")) <= 3, "info")
    old_tab = [l for l in (section(old, "## ⏳ De validat pe viu") or "").splitlines()
               if l.startswith("|") and not re.match(r"^\|[\s|:-]+\|$", l)][1:]
    kept = sum(l in lines for l in old_tab)
    check("De validat: base rows kept verbatim %d/%d" % (kept, len(old_tab)), kept == len(old_tab), "info")
    check("test orders #1035 in HANDOFF", "1035" in new, "info")
    touched = sorted(set(changed(cell, base)) & T3_CODE)
    check("code files touched: %s" % (", ".join(touched) or "none"), not touched, "info")


TASKS = {"scribe-T1": t1, "scribe-T2": t2, "scribe-T3": t3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("cell")
    ap.add_argument("--base", default="base")
    ap.add_argument("--json")
    ap.add_argument("--stat-file")
    a = ap.parse_args()
    if a.task not in TASKS:
        print("no checks for task %s" % a.task, file=sys.stderr)
        return 2
    TASKS[a.task](a.cell, a.base)
    ok = all(r["pass"] for r in results if r["level"] == "hard")
    hard = [r for r in results if r["level"] == "hard"]
    print("%s %d/%d hard" % ("PASS" if ok else "FAIL", sum(r["pass"] for r in hard), len(hard)))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            stat = open(a.stat_file, encoding="utf-8").read() if a.stat_file else ""
            json.dump({"task": a.task, "pass": ok, "diff_stat": stat.rstrip("\n").splitlines(),
                       "changed": changed(a.cell, a.base), "checks": results}, fh, indent=1, ensure_ascii=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
