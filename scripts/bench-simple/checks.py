#!/usr/bin/env python3
"""Usage: checks.py <T1..T4> <worktree> [--base REV] — see scripts/SCRIPTS.md"""
import argparse, collections, pathlib, re, subprocess, sys

FAQ3 = {"cat-de-des-igienizare-revizie.md", "garantia-aparatului-vs-montajului.md", "pierd-garantia-fara-igienizare.md"}
ALLOWED = {
    "T1": {"src/components/SEO.astro"},
    "T2": {"src/components/CardLucrare.astro", "src/components/Galerie3D.astro"},
    "T3": None,
    "T4": {"src/pages/produs/[slug].astro", "src/styles/produs.css"},
}
IGNORED_DIRS = ("dist/", ".astro/", "node_modules")
results = []


def check(name, ok):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name)


def read(root, rel):
    p = root / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout


def changed_files(root, base):
    ch = set(git(root, "diff", "--name-only", base).splitlines())
    ch |= set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    return {c for c in ch if not c.startswith(IGNORED_DIRS)}


def comments(src):
    out, in_block = [], False
    for line in src.splitlines():
        s = line.strip()
        if in_block:
            out.append(s)
            in_block = "*/" not in s
            continue
        m = re.search(r"/\*|<!--|(?<![:\w'\"])//", s)
        if m:
            out.append(s[m.start():])
            in_block = m.group(0) == "/*" and "*/" not in s[m.start():]
    return [c for c in out if c]


def scope_and_comments(root, base, task):
    ch = changed_files(root, base)
    allowed = ALLOWED[task]
    if allowed is None:
        allowed = {f for f in git(root, "ls-tree", "-r", "--name-only", base, "src/content/faq").splitlines()}
    extra = sorted(ch - allowed)
    check("scope only allowed files" + (f" (extra: {', '.join(extra)})" if extra else ""), not extra)
    lost = []
    for rel in sorted(ch & allowed):
        old = git(root, "show", f"{base}:{rel}")
        have = collections.Counter(comments(read(root, rel)))
        for c, n in collections.Counter(comments(old)).items():
            if have[c] < n:
                lost.append(f"{rel}: {c[:60]}")
    check(f"base comments intact line by line ({len(lost)} lost/rewritten)", not lost)
    for l in lost[:10]:
        print("   LOST " + l)
    return ch


def metas(html):
    out = collections.defaultdict(list)
    for tag in re.findall(r"<meta\b[^>]*>", html):
        k = re.search(r'(?:property|name)="([^"]+)"', tag)
        v = re.search(r'content="([^"]*)"', tag)
        if k and v:
            out[k.group(1)].append(v.group(1))
    return out


def task1(root, d):
    check("T1 dist/og/termclima.png exists", (d / "og/termclima.png").exists())
    pages = [d / "index.html"] + sorted(d.glob("*/index.html"))[:3]
    for p in pages:
        rel = p.relative_to(d).as_posix()
        m = metas(p.read_text(encoding="utf-8") if p.exists() else "")
        og = m.get("og:image", [])
        check(f"T1 {rel} exactly one og:image, absolute, /og/termclima.png",
              len(og) == 1 and re.fullmatch(r"https://[^\"]+/og/termclima\.png", og[0]))
        check(f"T1 {rel} og:image:width == 1200, height == 630",
              m.get("og:image:width") == ["1200"] and m.get("og:image:height") == ["630"])
        alt = m.get("og:image:alt", [])
        check(f"T1 {rel} og:image:type == image/png, one non-empty og:image:alt",
              m.get("og:image:type") == ["image/png"] and len(alt) == 1 and alt[0].strip())
        check(f"T1 {rel} twitter:card == summary_large_image", m.get("twitter:card") == ["summary_large_image"])
        check(f"T1 {rel} twitter:image == og:image", og and m.get("twitter:image") == og)


def rule(src, sel):
    m = re.search(r"^\s*" + re.escape(sel) + r"\s*\{([^}]*)\}", src, re.M)
    return m.group(1) if m else ""


def task2(root, d):
    for rel, sel in (("src/components/CardLucrare.astro", ".expus"), ("src/components/Galerie3D.astro", ".fisa-expus .expus")):
        src = read(root, rel)
        main_, before = rule(src, sel), rule(src, sel + "::before")
        name = rel.split("/")[-1]
        check(f"T2 {name} {sel}: opacity 0.92, no border", re.search(r"opacity:\s*0?\.92\s*;", main_) and "border:" not in main_)
        check(f"T2 {name} {sel}::before: border 1.5px accent-hi + mask-image",
              re.search(r"border:\s*1\.5px solid var\(--art-accent-hi\)", before) and re.search(r"(?<!-)mask-image:", before))
        check(f"T2 {name} ::before positioned (absolute, inset 0, content)",
              re.search(r"position:\s*absolute", before) and re.search(r"inset:\s*0", before) and "content:" in before)
        check(f"T2 {name} {sel} has no mask-image left", "mask-image" not in main_)
    css = " ".join(p.read_text(encoding="utf-8", errors="ignore") for p in d.rglob("*.css"))
    css += " ".join(p.read_text(encoding="utf-8", errors="ignore") for p in d.rglob("*.html"))
    check("T2 dist has opacity .92 and no .78", re.search(r"opacity:\s*0?\.92", css) and not re.search(r"opacity:\s*0?\.78", css))


OLD_T3 = ["condiționată de igienizarea anuală făcută de noi", "Igienizarea anuală la noi păstrează garanția",
          "O igienizare pe an la noi le păstrează"]


def body(s):
    return s.split("\n---\n", 1)[1] if "\n---\n" in s else ""


def task3(root, d, base):
    files = sorted((root / "src/content/faq").glob("*.md"))
    texts = {f.name: f.read_text(encoding="utf-8") for f in files}
    bad = [n for n, t in texts.items() if not re.search(r"^placeholder:\s*false\s*$", t, re.M)]
    check(f"T3 all {len(texts)} FAQ placeholder: false" + (f" (not: {', '.join(bad)})" if bad else ""), texts and not bad)
    left = [p for p in OLD_T3 if any(p in t for t in texts.values())]
    check("T3 old guarantee claims gone" + (f" ({left})" if left else ""), not left)
    check("T3 pierd-garantia answers «Nu»", body(texts.get("pierd-garantia-fara-igienizare.md", "")).lstrip().startswith("Nu"))
    g = body(texts.get("garantia-aparatului-vs-montajului.md", ""))
    check("T3 garantia-aparatului mentions other provider (alt prestator / altă parte)", re.search(r"alt prestator|altă parte", g))
    touched = [n for n in texts if n not in FAQ3 and
               body(texts[n]) != body(git(root, "show", f"{base}:src/content/faq/{n}"))]
    check("T3 other FAQ bodies unchanged" + (f" ({', '.join(touched)})" if touched else ""), not touched)
    for n, t in texts.items():
        old = git(root, "show", f"{base}:src/content/faq/{n}")
        fm = lambda s: re.sub(r"^placeholder:.*$", "", s.split("\n---\n", 1)[0], flags=re.M)
        if fm(old) != fm(t):
            check(f"T3 {n} frontmatter only placeholder changed", False)


def task4(root, d):
    pages = sorted(d.glob("produs/*/index.html"))
    check("T4 dist/produs/*/index.html exists", pages)
    for p in pages[:3]:
        h = p.read_text(encoding="utf-8")
        rel = p.relative_to(d).as_posix()
        check(f"T4 {rel} exactly one <footer>", len(re.findall(r"<footer\b", h)) == 1)
        i, s, a = h.find("<footer"), h.find('class="scena-p"'), h.find("</article>")
        check(f"T4 {rel} footer inside .scena-p, role=contentinfo",
              -1 < s < i < a and re.search(r'<footer\b[^>]*role="contentinfo"', h))
    css = read(root, "src/styles/produs.css")
    rules = re.findall(r"\.scena-p\s*>\s*\.footer\s*\{([^}]*)\}", css)
    anim = [r for r in rules if "position: absolute" in r or "position:absolute" in r]
    check("T4 .scena-p > .footer absolute rule exists", anim)
    r = anim[0] if anim else ""
    check("T4 footer animation-range 5.35 -> 5.95 ecran",
          re.search(r"5\.35\s*\*\s*var\(--ecran\)", r) and re.search(r"5\.95\s*\*\s*var\(--ecran\)", r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["T1", "T2", "T3", "T4"])
    ap.add_argument("worktree")
    ap.add_argument("--base", default="HEAD")
    a = ap.parse_args()
    root = pathlib.Path(a.worktree).resolve()
    d = root / "dist"
    scope_and_comments(root, a.base, a.task)
    {"T1": lambda: task1(root, d), "T2": lambda: task2(root, d),
     "T3": lambda: task3(root, d, a.base), "T4": lambda: task4(root, d)}[a.task]()
    fails = sum(not ok for _, ok in results)
    print(f"TOTAL {len(results) - fails}/{len(results)} PASS")
    sys.exit(1 if fails else 0)


main()
