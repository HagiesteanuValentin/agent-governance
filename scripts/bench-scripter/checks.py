#!/usr/bin/env python3
"""Usage: checks.py <T1..T3> <worktree> <rundir> <out.json> — see scripts/bench-scripter/README.md"""
import fnmatch, json, pathlib, re, struct, subprocess, sys

SLUGS = ["mihaela-art", "termclima", "diana-makeup"]
TASKS = {
    "T1": {
        "script": "scripts/verify-studii-caz.mjs",
        "md": ("docs/refine/studii-caz.measurements.md", 4000),
        "allowed": ["scripts/verify-studii-caz.mjs", "docs/refine/studii-caz.measurements.md", "docs/refine/studii-caz-*.png"],
        "json": [],
    },
    "T2": {
        "script": "scripts/verifica-produs.mjs",
        "md": ("docs/polish/produs.masuratori.md", 3000),
        "allowed": ["scripts/verifica-produs.mjs", "docs/polish/produs.masuratori.md", "docs/polish/capturi-produs/*"],
        "json": [],
    },
    "T3": {
        "script": "scripts/verifica-index-miscare.mjs",
        "md": ("docs/polish/index.masuratori.md", 3000),
        "allowed": ["scripts/verifica-index-miscare.mjs", "docs/polish/index.masuratori.md", "docs/polish/capturi-miscare/*"],
        "json": ["docs/polish/capturi-miscare/masuratori.json"],
    },
}
NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}|\b1[6-9]\d{11}\b")
results = []


def check(name, ok, detail=""):
    results.append({"criteriu": name, "pass": bool(ok), "detaliu": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def png_size(p):
    with open(p, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def near(a, b):
    return abs(a - b) <= max(1.0, 0.10 * max(abs(a), abs(b)))


def cmp_text(a, b, where, diffs):
    ta, tb = NUM.split(a), NUM.split(b)
    na, nb = NUM.findall(a), NUM.findall(b)
    if ta != tb or len(na) != len(nb):
        diffs.append(f"{where}: text diferit")
        return
    for x, y in zip(na, nb):
        if not near(float(x), float(y)):
            diffs.append(f"{where}: {x} vs {y}")


def cmp_json(a, b, where, diffs):
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            diffs.append(f"{where}: chei diferite {sorted(set(a) ^ set(b))[:5]}")
        for k in set(a) & set(b):
            cmp_json(a[k], b[k], f"{where}.{k}", diffs)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{where}: lungime {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            cmp_json(x, y, f"{where}[{i}]", diffs)
    elif isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        if a != b:
            diffs.append(f"{where}: {a} vs {b}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not near(a, b):
            diffs.append(f"{where}: {a} vs {b}")
    elif isinstance(a, str) and isinstance(b, str):
        cmp_text(a, b, where, diffs)
    elif a != b:
        diffs.append(f"{where}: tip diferit")


def as_json(text):
    for start in (0, text.find("{"), text.find("[")):
        if start < 0:
            continue
        try:
            return json.loads(text[start:])
        except ValueError:
            pass
    return None


def main():
    task, root, rundir, out = sys.argv[1], pathlib.Path(sys.argv[2]).resolve(), pathlib.Path(sys.argv[3]), sys.argv[4]
    t = TASKS[task]
    exits = [int((rundir / f"run{i}.exit").read_text().strip()) for i in (1, 2)]

    check("script exists", (root / t["script"]).exists(), t["script"])
    check("exit 0 de 2×", exits == [0, 0], f"exit {exits}")

    if task == "T1":
        want = [f"docs/refine/studii-caz-{s}-{bp}.png" for s in SLUGS for bp in ("mobile", "tablet", "desktop")]
        sizes = {w: png_size(root / w) if (root / w).exists() else None for w in want}
        bad = [f"{w.split('/')[-1]}={s}" for w, s in sizes.items() if not s or max(s) > 1568]
        check("9 PNG studii-caz-<pagina>-<bp>, latura lungă ≤1568", not bad, "; ".join(bad[:4]))
    else:
        d, maxw = ("docs/polish/capturi-produs", 1440) if task == "T2" else ("docs/polish/capturi-miscare", 800)
        pngs = sorted((root / d).glob("*-mic.png"))
        sizes = {p.name: png_size(p) for p in pngs}
        bad = [f"{n}={s}" for n, s in sizes.items() if not s or s[0] > maxw]
        counts = (3, 9) if task == "T2" else (3,)
        check(f"{' sau '.join(map(str, counts))} PNG -mic în {d}, lățime ≤{maxw}", len(pngs) in counts and not bad,
              f"{len(pngs)} PNG: " + ", ".join(f"{n} {s[0]}x{s[1]}" if s else n for n, s in sizes.items()))

    md, limit = t["md"]
    mdp = root / md
    n = len(mdp.read_text(encoding="utf-8")) if mdp.exists() else -1
    check(f"{md} prezent, ≤{limit} caractere", 0 < n <= limit, f"{n} caractere")
    if task == "T1" and mdp.exists():
        txt = mdp.read_text(encoding="utf-8").lower()
        missing = [s for s in SLUGS + ["hover"] if s not in txt]
        check("md are cele 3 pagini + hover", not missing, f"lipsă: {missing}" if missing else "")
    for j in t["json"]:
        check(f"{j} prezent", (root / j).exists())

    diffs, stamps, compared = [], [], []
    runs = [rundir / "run1", rundir / "run2"]
    names = sorted({p.relative_to(runs[0]).as_posix() for p in runs[0].rglob("*") if p.is_file()})
    for rel in names:
        a, b = runs[0] / rel, runs[1] / rel
        if not b.exists():
            diffs.append(f"{rel}: lipsă la rularea 2")
            continue
        compared.append(rel)
        ta, tb = a.read_text(encoding="utf-8", errors="replace"), b.read_text(encoding="utf-8", errors="replace")
        ja, jb = (as_json(ta), as_json(tb)) if rel.endswith((".json", ".out")) else (None, None)
        if ja is not None and jb is not None:
            cmp_json(ja, jb, rel, diffs)
            stamps += [rel] if TIMESTAMP.search(ta) else []
        else:
            cmp_text(ta, tb, rel, diffs)
    check("ieșiri stabile între rulări (chei egale, cifre ±10%/±1)", exits == [0, 0] and compared and not diffs,
          (f"exit {exits}; " if exits != [0, 0] else "") + f"comparat {compared}; " + "; ".join(diffs[:5]))
    check("fără timestamp în JSON", not stamps, ", ".join(stamps))

    st = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                        capture_output=True, text=True).stdout.splitlines()
    paths = [l[3:].split(" -> ")[-1].strip('"') for l in st]
    extra = [p for p in paths if not any(fnmatch.fnmatch(p, g) for g in t["allowed"])]
    check("fișiere noi/modificate doar în căile permise", not extra, ", ".join(extra[:8]))

    ok = all(r["pass"] for r in results)
    json.dump({"task": task, "worktree": str(root), "exits": exits, "pass": ok, "criterii": results},
              open(out, "w"), ensure_ascii=False, indent=1)
    print(f"TOTAL {sum(r['pass'] for r in results)}/{len(results)} PASS -> {out}")
    sys.exit(0 if ok else 1)


main()
