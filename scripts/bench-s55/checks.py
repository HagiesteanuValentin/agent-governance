#!/usr/bin/env python3
"""Usage: checks.py <A|B|C> <worktree> [--base REV] — see scripts/SCRIPTS.md"""
import argparse, pathlib, re, subprocess, sys

IGNORED = {"functions/_kb.ts"}
ALLOWED = {
    "A": {"src/pages/parteneri.astro", "src/components/Footer.astro", "src/pages/sitemap.xml.ts"},
    "B": {"src/pages/parteneri.astro", "src/pages/partners.astro", "src/components/Footer.astro",
          "src/layouts/PartnerLayout.astro", "src/layouts/BaseLayout.astro", "src/pages/sitemap.xml.ts"},
    "C": {"src/components/ContactForm.astro"},
}
results = []


def check(name, ok):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name)


def read(root, rel):
    p = root / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout


def link(html, href, text):
    return re.search(r'<a\b[^>]*href="%s"[^>]*>\s*%s\s*</a>' % (re.escape(href), re.escape(text)), html) is not None


def header(html):
    m = re.search(r"<header\b.*?</header>", html, re.S)
    return m.group(0) if m else ""


def scope(root, base, task):
    changed = set(git(root, "diff", "--name-only", base, "--", "src").split())
    changed |= set(git(root, "ls-files", "--others", "--exclude-standard", "--", "src").split())
    extra = sorted(changed - IGNORED - ALLOWED[task])
    check("scope src/ only allowed files" + (f" (extra: {', '.join(extra)})" if extra else ""), not extra)


def task_a(root, d):
    p = read(d, "parteneri/index.html")
    check("A dist/parteneri/index.html exists", p)
    check("A title exact", "<title>Subcontractare site-uri web pentru agenții — white label | Vulcan Edge</title>" in p)
    check("A canonical /parteneri/", '<link rel="canonical" href="https://vulcanedge.net/parteneri/">' in p)
    check("A no noindex", p and "noindex" not in p)
    check("A no hreflang", p and "hreflang" not in p)
    main_ = (re.search(r"<main\b.*?</main>", p, re.S) or re.match("", "")).group(0)
    check("A no /pachete in <main>", main_ and "/pachete" not in main_)
    check("A no € and no digit+lei/€", p and "€" not in p and not re.search(r"\d\s*(?:&nbsp;| )?\s*(?:lei|€)", p))
    check("A subject=Brief%20agen", "subject=Brief%20agen" in p)
    check("A /portofoliu/", "/portofoliu/" in p)
    s = read(d, "sitemap.xml")
    check("A sitemap has /parteneri/, not /partners", "/parteneri/" in s and "/partners" not in s)
    check("A home footer Parteneri -> /parteneri/", link(read(d, "index.html"), "/parteneri/", "Parteneri"))
    check("A partners footer Parteneri (RO)", link(read(d, "partners/index.html"), "/parteneri/", "Parteneri (RO)"))
    check("A parteneri footer Partners (EN)", link(p, "/partners/", "Partners (EN)"))


def task_b(root, d):
    p, e = read(d, "parteneri/index.html"), read(d, "partners/index.html")
    check("B noindex on parteneri + partners", "noindex" in p and "noindex" in e)
    s = read(d, "sitemap.xml")
    check("B sitemap without /parteneri/ and /partners", s and "/parteneri/" not in s and "/partners" not in s)
    hits = subprocess.run(["grep", "-rl", "CONFIRM", str(d)], capture_output=True, text=True).stdout.split()
    check("B CONFIRM only in partners/index.html", [pathlib.Path(h).relative_to(d).as_posix() for h in hits] == ["partners/index.html"])
    check("B zero [X] in parteneri", p and "[X]" not in p)
    for page in ("index.html", "pachete/index.html"):
        h = read(d, page)
        check(f"B footer both links on {page}", link(h, "/parteneri/", "Parteneri (RO)") and link(h, "/partners/", "Partners (EN)"))
    for name, h, subj in (("parteneri", p, "subject=Brief%20agen%C8%9Bie"), ("partners", e, "subject=Partner%20brief")):
        hd = header(h)
        check(f"B {name} header without /pachete and main nav", hd and "/pachete" not in hd and "Navigație principală" not in hd)
        check(f"B {name} header CTA {subj}", subj in hd)
    check("B partners lang=en + og:locale en_GB", '<html lang="en"' in e and re.search(r'og:locale"\s+content="en_GB"', e))
    check("B parteneri lang=ro + og:locale ro_RO", '<html lang="ro"' in p and re.search(r'og:locale"\s+content="ro_RO"', p))
    check("B partners Skip to content", "Skip to content" in e)
    for t in ("Shop are backend", "Add-on-uri, ofertate separat", "Plata: 40% la kickoff",
              "site-urile de prezentare", "Lucrez pe contract de subcontractare", "oferta vine în 24 de ore"):
        check(f"B parteneri has «{t}»", t in re.sub(r"\s+", " ", p))


NEW_C = ["Contabilitate", "Fonduri europene", "Imobiliare", "Turism", "Panouri fotovoltaice", "Mutări", "Cofetărie", "Pensiune"]
OLD_C = ["Expert contabil", "Consultant fonduri europene", "Agent imobiliar", "Agent de turism",
         "Montaj panouri fotovoltaice", "Firmă de mutări", "Cofetărie artizanală", "Pensiune turistică"]


def task_c(root, d, base):
    h = read(d, "contact/index.html")
    check("C contact has the 8 new labels", h and all(re.search(r">\s*%s\s*<" % re.escape(t), h) for t in NEW_C))
    check("C contact has none of the 8 old labels", h and not any(t in h for t in OLD_C))
    rel = "src/components/ContactForm.astro"
    old, new = git(root, "show", f"{base}:{rel}"), read(root, rel)
    ids = lambda s: sorted(re.findall(r'\[\s*"([^"]+)",\s*"', s))
    check("C n values identical to base", old and ids(old) == ids(new))
    diff = git(root, "diff", base, "--", rel)
    check("C no diff line touches icons", not re.search(r"^[+-](?![+-]).*(icon|svg)", diff, re.M | re.I))
    mag = lambda s: (re.search(r"magazin:\s*\[.*?\n\s*\]", s, re.S) or re.match("", "")).group(0)
    check("C Magazin labels unchanged", mag(old) and mag(old) == mag(new))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["A", "B", "C"])
    ap.add_argument("worktree")
    ap.add_argument("--base", default="HEAD")
    a = ap.parse_args()
    root = pathlib.Path(a.worktree).resolve()
    d = root / "dist"
    scope(root, a.base, a.task)
    {"A": lambda: task_a(root, d), "B": lambda: task_b(root, d), "C": lambda: task_c(root, d, a.base)}[a.task]()
    fails = sum(not ok for _, ok in results)
    print(f"TOTAL {len(results) - fails}/{len(results)} PASS")
    sys.exit(1 if fails else 0)


main()
