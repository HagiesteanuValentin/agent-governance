#!/usr/bin/env python3
"""Extract real explorer/explorer-max/scribe briefs from subagent transcripts into bench task files."""
import argparse
import glob
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime

CELL = "{{CELL_DIR}}"
REL_RE = re.compile(r"(?<![\w/~.:@*-])((?:[\w.-]+/)*[\w-][\w.-]*\.[A-Za-z][A-Za-z0-9]{0,4}|(?:[\w.-]+/)+)(?![\w/*])")
ABS_RE = re.compile(r"(?:~|/home/|/tmp/)[^\s`'\"«»„”)(,;]*")
LIMIT_RE = re.compile(r"(?:Raport|Răspunde)[^≤\n]{0,25}≤\s*(\d+(?:[.,]\d+)?)\s*(k)?", re.I)


def find_jsonl(projects, agent):
    pats = [f"{projects}/*/subagents/agent-{agent}*.jsonl", f"{projects}/*/*/subagents/agent-{agent}*.jsonl"]
    hits = sorted({h for p in pats for h in glob.glob(p)})
    if len(hits) != 1:
        raise SystemExit(f"agent {agent}: {len(hits)} jsonl found")
    return hits[0]


def load(path):
    rows = []
    for ln in open(path, encoding="utf-8"):
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return rows


def text_of(content):
    if isinstance(content, str):
        return content
    return "".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")


def parse(path):
    rows = load(path)
    first = ts = cwd = model = branch = None
    msgs = {}
    uses, results = [], {}
    for d in rows:
        if d.get("type") == "user":
            c = d["message"]["content"]
            if first is None:
                first, ts, cwd, branch = text_of(c), d.get("timestamp"), d.get("cwd"), d.get("gitBranch")
            if isinstance(c, list):
                for x in c:
                    if isinstance(x, dict) and x.get("type") == "tool_result":
                        results[x["tool_use_id"]] = d.get("toolUseResult")
        elif d.get("type") == "assistant":
            m = d["message"]
            model = m.get("model") or model
            u = m.get("usage", {})
            msgs[m.get("id") or id(d)] = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            for x in m.get("content", []):
                if x.get("type") == "tool_use":
                    uses.append(x)
    for u in uses:
        u["_result"] = results.get(u["id"])
    return dict(path=path, first=first, ts=ts, cwd=cwd, branch=branch, model=model, turns=len(msgs), tokens_in=sum(msgs.values()), uses=uses)


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env={**os.environ, "TZ": "UTC"})
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip())
    return r


def in_git(repo, commit, rel):
    return git(repo, "cat-file", "-e", f"{commit}:{rel}", check=False).returncode == 0


def cat_segments(cmd):
    try:
        toks = shlex.split(cmd)
    except ValueError:
        return []
    segs, cur = [], []
    for t in toks + [";"]:
        if t in (";", "&&", "||", "|"):
            if cur:
                segs.append((cur, t))
            cur = []
        else:
            cur.append(t)
    return segs


def observations(session_files):
    obs = {}
    for f in session_files:
        for u in parse(f)["uses"]:
            r = u["_result"]
            if u["name"] == "Read" and isinstance(r, dict) and "filePath" in r.get("file", {}) and "content" in r["file"]:
                fi = r["file"]
                if fi.get("startLine", 1) == 1 and fi.get("numLines") == fi.get("totalLines"):
                    obs.setdefault(fi["filePath"], []).append(("full", fi["content"] + ("\n" if not fi["content"].endswith("\n") else "")))
            elif u["name"] == "Bash" and isinstance(r, dict) and "stdout" in r:
                segs = cat_segments(u["input"].get("command", ""))
                if segs and segs[0][0][0] == "cat" and len(segs[0][0]) == 2 and segs[0][1] != "|":
                    kind = "full" if len(segs) == 1 else "prefix"
                    obs.setdefault(segs[0][0][1], []).append((kind, r["stdout"]))
    return obs


def piece_ok(piece, olist):
    for kind, o in olist:
        if kind == "full" and o.rstrip("\n") == piece.rstrip("\n"):
            return True
        if kind == "prefix" and o.startswith(piece.rstrip("\n")):
            rest = o[len(piece.rstrip("\n")):]
            if rest == "" or re.match(r"\n*[=\-#]{3}", rest):
                return True
    return False


def split_cat(stdout, files, obs):
    if len(files) == 1:
        return {files[0]: stdout}
    cuts = [0] + [m.end() for m in re.finditer(r"\n", stdout) if m.end() < len(stdout)]
    sols = []

    def rec(k, start, acc):
        if k == len(files) - 1:
            piece = stdout[start:]
            if files[k] not in obs or piece_ok(piece, obs[files[k]]):
                sols.append(acc + [piece])
            return
        for c in cuts:
            if c <= start:
                continue
            piece = stdout[start:c]
            if files[k] in obs and not piece_ok(piece, obs[files[k]]):
                continue
            rec(k + 1, c, acc + [piece])

    rec(0, 0, [])
    if len(sols) != 1:
        raise RuntimeError(f"cat {' '.join(files)}: {len(sols)} possible splits")
    return dict(zip(files, sols[0]))


def aux_rel(path, repo):
    if path.startswith(repo + "/"):
        return path[len(repo) + 1:]
    return re.sub(r"^/tmp/(?:claude-\d+/)?", "", path).lstrip("/")


def collect_aux(info, repo, commit):
    session_dir = os.path.dirname(os.path.dirname(info["path"]))
    session_files = [session_dir + ".jsonl"] + glob.glob(session_dir + "/subagents/*.jsonl")
    obs = observations([f for f in session_files if os.path.exists(f)])
    aux = {}
    for u in info["uses"]:
        r = u["_result"]
        if u["name"] == "Read" and isinstance(r, dict) and "filePath" in r.get("file", {}):
            p = r["file"]["filePath"]
            if not (p.startswith(repo + "/") and in_git(repo, commit, p[len(repo) + 1:])):
                fi = r["file"]
                if fi.get("startLine", 1) != 1 or fi.get("numLines") != fi.get("totalLines"):
                    raise RuntimeError(f"partial Read of aux {p}")
                aux[p] = fi["content"] if fi["content"].endswith("\n") else fi["content"] + "\n"
        elif u["name"] == "Bash" and isinstance(r, dict) and "stdout" in r:
            segs = cat_segments(u["input"].get("command", ""))
            if len(segs) == 1 and segs[0][0][0] == "cat" and all(a.startswith("/") for a in segs[0][0][1:]):
                files = segs[0][0][1:]
                outside = [p for p in files if not (p.startswith(repo + "/") and in_git(repo, commit, p[len(repo) + 1:]))]
                if outside:
                    aux.update({p: c for p, c in split_cat(r["stdout"] + "\n", files, obs).items() if p in outside})
    return aux


def rewrite(text, repo, exists, prefix, aux_map):
    n = 0
    for src, dst in sorted(aux_map.items(), key=lambda kv: -len(kv[0])):
        n += text.count(src)
        text = text.replace(src, dst)
    if prefix != repo:
        n += len(re.findall(re.escape(repo) + r"(?![\w-])", text))
        text = re.sub(re.escape(repo) + r"(?![\w-])", prefix, text)

    def sub(m):
        nonlocal n
        tok = m.group(1)
        if exists(tok.rstrip("/")):
            n += 1
            return f"{prefix}/{tok}"
        return tok

    out = []
    for i, part in enumerate(re.split(r"((?:/home/|~/|/tmp/|https?://|\{\{CELL_DIR\}\}/)\S*)", text)):
        out.append(part if i % 2 else REL_RE.sub(sub, part))
    return "".join(out), n


def abs_paths(text):
    res = []
    for p in ABS_RE.findall(text):
        p = p.rstrip(".:…")
        if "tool-results" in p or p in ("~", "/tmp/"):
            continue
        res.append(p)
    return sorted(set(res))


def path_exists(p):
    q = os.path.expanduser(p)
    return bool(glob.glob(q)) if any(c in q for c in "*?[") else os.path.exists(q)


def limit_chars(text):
    m = LIMIT_RE.search(text)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return int(v * 1000) if m.group(2) or v < 20 else int(v)


def build(task, args):
    jsonl = find_jsonl(args.projects_dir, task["agent"])
    info = parse(jsonl)
    meta = json.load(open(jsonl[:-6] + ".meta.json"))
    if meta.get("agentType") != task["role"]:
        raise RuntimeError(f"agentType {meta.get('agentType')} != {task['role']}")
    web = [u["name"] for u in info["uses"] if u["name"] in ("WebSearch", "WebFetch")]
    if web:
        raise RuntimeError(f"uses web: {web}")
    repo = git(info["cwd"], "rev-parse", "--show-toplevel").stdout.strip()
    rec = dict(id=task["id"], role=task["role"], agent=task["agent"], source=jsonl, model=info["model"],
               turns=info["turns"], tokens_in=info["tokens_in"], first_ts=info["ts"], repo=repo)
    body = info["first"]
    for old, new in task.get("replace", []):
        if body.count(old) != 1:
            raise RuntimeError(f"replace: {body.count(old)} matches for {old[:40]!r}")
        body = body.replace(old, new)
    rec["pinned"] = task.get("pinned", [])
    aux_files = {}
    if task["role"] == "scribe":
        ts = datetime.fromisoformat(info["ts"].replace("Z", "+00:00"))
        ref = info["branch"] if info["branch"] and git(repo, "rev-parse", "--verify", "-q", info["branch"], check=False).returncode == 0 else "HEAD"
        line = git(repo, "log", "-1", "--date=iso-strict", f"--before={info['ts']}", "--format=%H %ct %cd", ref).stdout.split()
        if not line:
            raise RuntimeError(f"no commit before {info['ts']} on {ref}")
        commit, ct = line[0], int(line[1])
        if not ct < ts.timestamp():
            raise RuntimeError("commit not strictly before first message")
        targets = sorted({u["input"]["file_path"][len(repo) + 1:] for u in info["uses"]
                          if u["name"] in ("Edit", "Write", "MultiEdit") and u["input"].get("file_path", "").startswith(repo + "/")})
        targets = sorted(set(targets) | set(task.get("targets", [])))
        if not targets:
            raise RuntimeError("no Edit/Write target inside the repo")
        missing = [t for t in targets if not in_git(repo, commit, t)]
        if missing:
            raise RuntimeError(f"targets not in git at {commit[:7]}: {missing}")
        aux = collect_aux(info, repo, commit)
        aux_map = {p: f"{CELL}/{aux_rel(p, repo)}" for p in aux}
        unresolved = [p for p in abs_paths(body) if p.startswith("/tmp/") and p not in aux]
        if unresolved:
            raise RuntimeError(f"brief references unrecovered files: {unresolved}")
        exists = lambda rel: in_git(repo, commit, rel) or any(aux_rel(p, repo) == rel for p in aux)
        body, n = rewrite(body, repo, exists, CELL, aux_map)
        for p, c in aux.items():
            aux_files[aux_rel(p, repo)], k = rewrite(c, repo, exists, CELL, aux_map)
            n += k
        rec.update(commit=commit, commit_date=line[2], targets=targets, anchors=task.get("anchors", {}),
                   aux=sorted(aux_files), rewrites=n)
    else:
        body, n = rewrite(body, repo, lambda rel: os.path.exists(os.path.join(repo, rel)), repo, {})
        rec.update(limit_chars=limit_chars(body), abs_paths=abs_paths(body), rewrites=n)
    header = f"<!-- sursa: {jsonl}, model {info['model']}, turnuri {info['turns']}, tokeni intrați {info['tokens_in']} -->\n"
    return rec, header + body.rstrip("\n") + "\n", aux_files


def check(out_dir):
    fails = []
    tasks = json.load(open(os.path.join(out_dir, "tasks.json")))["tasks"]
    for t in tasks:
        md = os.path.join(out_dir, t["id"] + ".md")
        if not os.path.exists(md):
            fails.append(f"{t['id']}: missing .md")
            continue
        if t["role"] == "scribe":
            for p in t["targets"]:
                if not in_git(t["repo"], t["commit"], p):
                    fails.append(f"{t['id']}: {p} not in {t['commit'][:7]}")
            for p, anchors in t["anchors"].items():
                blob = git(t["repo"], "show", f"{t['commit']}:{p}", check=False).stdout
                fails += [f"{t['id']}: anchor {a!r} not in {p}" for a in anchors if a not in blob]
            fails += [f"{t['id']}: aux {a} missing" for a in t["aux"] if not os.path.isfile(os.path.join(out_dir, t["id"] + ".aux", a))]
        else:
            fails += [f"{t['id']}: path {p} missing" for p in t["abs_paths"] + t.get("pinned", []) if not path_exists(p)]
            fails += [f"{t['id']}: pinned {p} not in brief" for p in t.get("pinned", []) if p not in open(md, encoding="utf-8").read()]
            if not t.get("limit_chars"):
                fails.append(f"{t['id']}: no char limit")
    print(f"CHECK: {len(tasks)} tasks, {len(fails)} failures")
    for f in fails:
        print("  FAIL", f)
    return not fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--spec", help="JSON: {tasks:[{id,role,agent,targets?,anchors?,expect_rewrites?}], rejected:[...]}")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="task id")
    ap.add_argument("--check", action="store_true", help="only verify existing output")
    ap.add_argument("--scan", help="role: list every agent of this role with pass/FAIL reason, writes nothing")
    args = ap.parse_args()
    if args.scan:
        metas = glob.glob(f"{args.projects_dir}/*/subagents/*.meta.json") + glob.glob(f"{args.projects_dir}/*/*/subagents/*.meta.json")
        for m in sorted(metas):
            if json.load(open(m)).get("agentType") != args.scan:
                continue
            agent = os.path.basename(m)[6:-10]
            try:
                rec, md, aux = build({"id": "scan", "role": args.scan, "agent": agent}, args)
                print(f"ok   {agent} {rec['first_ts'][:16]} t={rec['turns']} aux={len(aux)} {rec.get('targets', '')} | {md.splitlines()[1][:90]}")
            except Exception as e:
                print(f"FAIL {agent} {str(e)[:150]}")
        return
    if args.check:
        sys.exit(0 if check(args.out) else 1)
    spec = json.load(open(args.spec))
    tasks_path = os.path.join(args.out, "tasks.json")
    old = {t["id"]: t for t in json.load(open(tasks_path))["tasks"]} if os.path.exists(tasks_path) else {}
    recs, bad, changed = dict(old), 0, 0
    for task in spec["tasks"]:
        if args.only and task["id"] != args.only:
            continue
        try:
            rec, md, aux = build(task, args)
        except (RuntimeError, SystemExit) as e:
            print(f"FAIL {task['id']} ({task['agent']}): {e}")
            bad += 1
            continue
        exp = task.get("expect_rewrites")
        flag = "" if exp is None or exp == rec["rewrites"] else f"  EXPECTED {exp}"
        bad += bool(flag)
        print(f"{task['id']}: {task['agent']} rewrites={rec['rewrites']} aux={len(aux)} "
              + (f"commit={rec['commit'][:7]} targets={len(rec['targets'])}" if task["role"] == "scribe" else f"limit={rec['limit_chars']} paths={len(rec['abs_paths'])}") + flag)
        if args.dry_run:
            continue
        files = {os.path.join(args.out, task["id"] + ".md"): md}
        files.update({os.path.join(args.out, task["id"] + ".aux", rel): c for rel, c in aux.items()})
        for p, c in files.items():
            if os.path.exists(p) and open(p, encoding="utf-8").read() == c:
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(c)
            changed += 1
        recs[task["id"]] = rec
    if not args.dry_run:
        order = [t["id"] for t in spec["tasks"]]
        data = json.dumps({"tasks": [recs[i] for i in order if i in recs], "rejected": spec.get("rejected", [])}, ensure_ascii=False, indent=1) + "\n"
        if not (os.path.exists(tasks_path) and open(tasks_path, encoding="utf-8").read() == data):
            open(tasks_path, "w", encoding="utf-8").write(data)
            changed += 1
        print(f"changed files: {changed}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
