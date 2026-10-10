#!/usr/bin/env bash
# Usage: anon.sh <role> <task> [--force] — see scripts/bench-haiku/README.md
set -euo pipefail
BENCH_ROOT="${BENCH_ROOT:-${HOME}/workflow/experimente/bench-haiku}"
TASKS="${TASKS:-$BENCH_ROOT/tasks/tasks.json}"
ARMS="${ARMS:-s55-low s55-medium h55-medium h55-high}"
ROLE="${1:?Usage: anon.sh <role> <task> [--force]}"; TASK="${2:?task missing}"
OUT="$BENCH_ROOT/audit/$ROLE/$TASK"
MAP="$BENCH_ROOT/audit-mapping-$ROLE-$TASK.json"
if [[ -e "$OUT" && "${3:-}" != "--force" ]]; then
  echo "$OUT exists (auditors may be reading it); --force to redo with a new shuffle" >&2; exit 1
fi
rm -rf "$OUT"; mkdir -p "$OUT"

python3 - "$BENCH_ROOT" "$ROLE" "$TASK" "$OUT" "$MAP" "$TASKS" "$ARMS" <<'PY'
import json, os, random, re, shutil, sys
root, role, task, out, mapf, tasks_f, arms = sys.argv[1:8]
arms = arms.split()
spec = next(t for t in json.load(open(tasks_f))["tasks"] if t["id"] == task)
MODEL = r"(?i)\b(claude-(sonnet|haiku)-5-5(-\d+)?|(sonnet|haiku)[ -]?5[.-]5)(?![\w.]*\d)"
ARM = r"(?i)\b(%s|s55-(low|medium)|h55-(medium|high)|[sh]55)\b" % "|".join(map(re.escape, sorted(arms, key=len, reverse=True)))
CELLNAME = r"\bcell-[\w.-]*\w"
roots = sorted({root, os.path.realpath(root), root.replace(os.path.expanduser("~"), "~", 1), os.path.expanduser("~/workflow/experimente/bench-haiku")}, key=len, reverse=True)
cell_re = re.compile(r"^%s-(%s)-(\d+)$" % (re.escape(task), "|".join(map(re.escape, arms))))
cells = sorted(d for d in os.listdir(os.path.join(root, role)) if cell_re.match(d))
if not cells:
    sys.exit("no cells for %s/%s under %s" % (role, task, root))


def clean(text, cell):
    for r in roots:
        text = text.replace(os.path.join(r, role, cell), "CELL") if cell else text
        text = text.replace(r, "ROOT")
    text = re.sub(r"%s-[\w.-]+?-\d+\b" % re.escape(task), "CELL", text)
    text = re.sub(CELLNAME, "CELL", text)
    text = re.sub(MODEL, "MODEL", text)
    return re.sub(ARM, "MODEL", text)


def put(src, dst, cell):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, encoding="utf-8", errors="replace") as fh:
        text = clean(fh.read(), cell)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(text)


random.shuffle(cells)
mapping, missing = {}, 0
for i, cell in enumerate(cells):
    letter, src = chr(ord("A") + i), os.path.join(root, role, cell)
    files = ["report.md"] + (["diff.patch"] + spec.get("targets", []) if role == "scribe" else [])
    n = 0
    for rel in files:
        p = os.path.join(src, rel)
        if os.path.isfile(p):
            put(p, os.path.join(out, letter, rel), cell); n += 1
        else:
            print("WARN %s missing in %s" % (rel, cell), file=sys.stderr); missing += 1
    mapping[letter] = {"cell": cell, "arm": cell_re.match(cell).group(1), "path": src}
    print("%s <- %d files" % (letter, n))
brief = os.path.join(os.path.dirname(tasks_f), task + ".md")
with open(brief, encoding="utf-8") as fh:
    text = "".join(l for l in fh if not l.startswith("<!-- sursa:"))
with open(os.path.join(out, "BRIEF.md"), "w", encoding="utf-8") as fh:
    fh.write(clean(text.replace("{{CELL_DIR}}", "CELL"), ""))
with open(mapf, "w", encoding="utf-8") as fh:
    json.dump(mapping, fh, indent=1)
print("letters=%d missing_files=%d mapping -> %s" % (len(cells), missing, mapf))
PY
