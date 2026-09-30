#!/usr/bin/env bash
# Usage: anon.sh <T1..T3> [--force] — see scripts/bench-scripter/README.md
set -euo pipefail
BENCH_ROOT="${BENCH_ROOT:-${HOME}/workflow/experimente/bench-scripter}"
DEFAULT_CELLS="cell-scripter-o55-low cell-scripter-s55-medium"
read -r -a CELLS <<<"${CELLS:-$DEFAULT_CELLS}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TASK="${1:?Usage: anon.sh <T1..T3> [--force]}"
[[ -f "$HERE/briefs/$TASK.md" ]] || { echo "Unknown task: $TASK" >&2; exit 1; }
OUT="$BENCH_ROOT/audit/$TASK"
MAP="$BENCH_ROOT/audit-mapping-$TASK.json"
if [[ -e "$OUT" && "${2:-}" != "--force" ]]; then
  echo "$OUT exists (auditors may be reading it); --force to redo with a new shuffle" >&2; exit 1
fi
rm -rf "$OUT"; mkdir -p "$OUT"

WTS=()
for CELL in "${CELLS[@]}"; do
  for WT in "$BENCH_ROOT/$TASK/$CELL"-*/; do
    [[ -d "$WT/.git" ]] && WTS+=("${WT%/}")
  done
done
(( ${#WTS[@]} > 0 )) || { echo "No cells for ${CELLS[*]} in $BENCH_ROOT/$TASK" >&2; exit 1; }
(( ${#WTS[@]} <= 26 )) || { echo "Too many cells (${#WTS[@]})" >&2; exit 1; }
[[ -d "$BENCH_ROOT/$TASK/ref-1/.git" ]] || { echo "ref-1 missing in $BENCH_ROOT/$TASK" >&2; exit 1; }

python3 - "$BENCH_ROOT" "$TASK" "$OUT" "$MAP" "$HERE/briefs/$TASK.md" "${CELLS[*]}" "${WTS[@]}" <<'PY'
import json, os, random, re, shutil, subprocess, sys
root, task, out, mapf, brief, cells = sys.argv[1:7]
wts = sys.argv[7:]
arms = [c.removeprefix("cell-scripter-") for c in cells.split()]
TEXT = {".mjs", ".js", ".ts", ".md", ".json", ".txt", ".out", ".csv", ".html"}
MODEL = r"(?i)\b(opus|sonnet|haiku|claude-[\w.-]+)\b( \d+(\.\d+)?)?( (low|medium|high|xhigh))?"
roots = {root, os.path.realpath(root), root.replace(os.path.expanduser("~"), "~", 1)}


def outputs(wt):
    st = subprocess.run(["git", "-C", wt, "status", "--porcelain", "--untracked-files=all"],
                        capture_output=True, text=True, check=True).stdout
    files = [l[3:] for l in st.splitlines() if l[3:] and not l[3:].startswith("node_modules/")]
    so = os.path.join(os.path.dirname(wt), ".verify-" + os.path.basename(wt), "run1", "stdout.out")
    return files, so


def clean(text, wt, port):
    for r in roots:
        text = text.replace(os.path.join(r, task, os.path.basename(wt)), "<CELL>")
        text = text.replace(r, "<BENCH>")
    text = re.sub(r"cell-scripter-[\w.-]+?-\d+\b", "<cell>", text)
    text = re.sub(r"\b(%s)\b" % "|".join(map(re.escape, arms + ["o55", "s55"])), "<arm>", text)
    text = re.sub(MODEL, "<model>", text)
    text = re.sub(r"(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):44\d\d\b", r"\1:44NN", text)
    return re.sub(r"(?i)(port\W{0,4})44\d\d\b", r"\g<1>44NN", text)


def copy(wt, dest, skip_scripts):
    env = open(os.path.join(wt, "CELL.env")).read()
    port = re.search(r"PORT=(\d+)", env).group(1)
    files, so = outputs(wt)
    pairs = [(os.path.join(wt, f), f) for f in files if not (skip_scripts and f.startswith("scripts/"))]
    if os.path.exists(so):
        pairs.append((so, "stdout.out"))
    for src, rel in pairs:
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.splitext(rel)[1] in TEXT:
            text = clean(open(src, encoding="utf-8", errors="replace").read(), wt, port)
            open(dst, "w", encoding="utf-8").write(text)
            if re.search(r"\b%s\b" % port, text):
                print("WARN port %s still in %s" % (port, dst), file=sys.stderr)
        else:
            shutil.copy2(src, dst)
    return len(pairs)


random.shuffle(wts)
mapping = {}
for i, wt in enumerate(wts):
    letter = chr(ord("A") + i)
    n = copy(wt, os.path.join(out, letter), False)
    name = os.path.basename(wt)
    mapping[letter] = {"cell": name, "arm": re.sub(r"^cell-scripter-|-\d+$", "", name), "path": wt}
    print("%s <- %d files" % (letter, n))
print("ref-out <- %d files" % copy(os.path.join(root, task, "ref-1"), os.path.join(out, "ref-out"), True))
with open(os.path.join(out, "BRIEF.md"), "w", encoding="utf-8") as fh:
    fh.write(re.sub(MODEL, "<model>", open(brief, encoding="utf-8").read()))
with open(mapf, "w", encoding="utf-8") as fh:
    json.dump(mapping, fh, indent=1)
print("mapping -> %s" % mapf)
PY
