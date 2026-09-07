#!/usr/bin/env node
// Uz: verifica-simplu.next.mjs <root> [--json <out>] — vezi scripts/SCRIPTS.md
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
export const TARGET_DIRS = ['src/components', 'src/pages', 'src/layouts'];
const I3_FILES = ['src/components/AcasaCorp.astro', 'src/pages/despre.astro'];
export const I_IDS = ['I1', 'I2', 'I3', 'I4', 'I5', 'I6', 'I7', 'I8'];
export const LABEL = {
  I1: 'hex', I2: 'svg-focusable', I3: 'style-static', I4: 'img-complet',
  I5: 'button-type', I6: 'todo-client', I7: 'description', I8: 'npm-check',
};

// ---------- mascare comentarii/script ----------
const blank = (s) => s.replace(/[^\n]/g, ' ');
export function mask(src) {
  let s = src;
  s = s.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, blank);
  s = s.replace(/<!--[\s\S]*?-->/g, blank);
  s = s.replace(/\/\*[\s\S]*?\*\//g, blank);
  s = s.replace(/(^|[^:\w"'\\/])\/\/[^\n]*/g, (m, p1) => p1 + blank(m.slice(p1.length)));
  return s;
}
const lineOf = (s, idx) => s.slice(0, idx).split('\n').length;
function lineAt(s, idx) {
  const a = s.lastIndexOf('\n', idx - 1) + 1;
  let b = s.indexOf('\n', idx);
  if (b < 0) b = s.length;
  return s.slice(a, b);
}
export function tagWindows(src, tag) {
  const out = [];
  const re = new RegExp(`<${tag}\\b`, 'gi');
  let m;
  while ((m = re.exec(src)) !== null) {
    let end = src.indexOf('>', m.index);
    if (end < 0) end = Math.min(src.length, m.index + 4000);
    out.push({ idx: m.index, text: src.slice(m.index, end + 1) });
  }
  return out;
}

// ---------- context pe worktree ----------
export function creeazaContext(root) {
  const abs = path.resolve(root);
  const git = (...args) => execFileSync('git', ['-C', abs, ...args], { encoding: 'utf8', maxBuffer: 2 ** 28 });
  const gitSafe = (...args) => { try { return git(...args); } catch { return ''; } };
  const showMaster = (rel) => gitSafe('show', `master:${rel}`);
  const masterFiles = gitSafe('ls-tree', '-r', '--name-only', 'master').split('\n').filter(Boolean);
  const isTargetAstro = (f) => f.endsWith('.astro') && TARGET_DIRS.some((d) => f.startsWith(`${d}/`));
  const readCur = (rel) => { try { return fs.readFileSync(path.join(abs, rel), 'utf8'); } catch { return null; } };
  const currentTargets = () => {
    const out = [];
    for (const d of TARGET_DIRS) {
      const dir = path.join(abs, d);
      if (!fs.existsSync(dir)) continue;
      for (const e of fs.readdirSync(dir)) if (e.endsWith('.astro')) out.push(`${d}/${e}`);
    }
    return out.sort();
  };
  return { root: abs, git, gitSafe, showMaster, masterFiles, isTargetAstro, readCur, currentTargets };
}

// ---------- I1: hex colors in <style> and style="…" ----------
const I1_EXCL = /(href="|id="|url\(|name=")$/;
function styleScope(src) {
  const s = mask(src);
  const keep = s.replace(/[^\n]/g, ' ').split('');
  const put = (a, b) => { for (let i = a; i < b; i++) if (s[i] !== '\n') keep[i] = s[i]; };
  let m;
  const reBlock = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
  while ((m = reBlock.exec(s)) !== null) { const a = m.index + m[0].indexOf('>') + 1; put(a, a + m[1].length); }
  const reAttr = /style="([^"]*)"/g;
  while ((m = reAttr.exec(s)) !== null) { const a = m.index + 7; put(a, a + m[1].length); }
  return keep.join('');
}
export function hexMatches(src) {
  const s = styleScope(src);
  const out = [];
  const re = /#[0-9a-fA-F]{3,8}\b/g;
  let m;
  while ((m = re.exec(s)) !== null) {
    const before = s.slice(Math.max(0, m.index - 8), m.index);
    const line = lineAt(s, m.index);
    const sarit = I1_EXCL.test(before) || /<a\s+href/i.test(line);
    out.push({ match: m[0], line: lineOf(s, m.index), sarit });
  }
  return out;
}

// ---------- itemii I1–I8 ----------
export function itemiI(ctx) {
  const { readCur, currentTargets, gitSafe } = ctx;
  const items = {};
  const set = (id, status, found, target, detail = '') => { items[id] = { status, found, target, detail }; };
  const targets = currentTargets();

  // I1
  {
    let found = 0;
    const det = [];
    for (const f of targets) {
      const c = readCur(f);
      if (c == null) continue;
      const hits = hexMatches(c).filter((h) => !h.sarit);
      if (hits.length) { found += hits.length; det.push(`${f}:${hits.length}`); }
    }
    set('I1', found === 0 ? 'OK' : 'FAIL', found, 0, det.join(' '));
  }
  // I2
  {
    let found = 0;
    const det = [];
    for (const f of targets) {
      const c = readCur(f);
      if (c == null) continue;
      const bad = tagWindows(c, 'svg').filter((t) => /aria-hidden="true"/.test(t.text) && !/focusable="false"/.test(t.text));
      if (bad.length) { found += bad.length; det.push(`${f}:${bad.length}`); }
    }
    set('I2', found === 0 ? 'OK' : 'FAIL', found, 0, det.join(' '));
  }
  // I3
  {
    let found = 0;
    const det = [];
    for (const f of I3_FILES) {
      const c = readCur(f);
      if (c == null) continue;
      let n = 0;
      for (const line of c.split('\n')) {
        if (line.includes('{')) continue;
        n += (line.match(/style="/g) || []).length;
      }
      if (n) { found += n; det.push(`${f}:${n}`); }
    }
    set('I3', found === 0 ? 'OK' : 'FAIL', found, 0, det.join(' '));
  }
  // I4
  {
    let found = 0;
    const det = [];
    for (const f of targets) {
      const c = readCur(f);
      if (c == null) continue;
      const tags = tagWindows(mask(c), 'img');
      if (!tags.length) continue;
      const bad = tags.filter((t) => !(/loading=/.test(t.text) && /decoding=/.test(t.text) && /width=/.test(t.text) && /height=/.test(t.text)));
      if (bad.length) { found += bad.length; det.push(`${f}:${bad.length}/${tags.length}`); }
    }
    set('I4', found === 0 ? 'OK' : 'FAIL', found, 0, det.join(' '));
  }
  // I5
  {
    let found = 0;
    const det = [];
    for (const f of targets) {
      const c = readCur(f);
      if (c == null) continue;
      const bad = tagWindows(c, 'button').filter((t) => !/type=/.test(t.text));
      if (bad.length) { found += bad.length; det.push(`${f}:${bad.length}`); }
    }
    set('I5', found === 0 ? 'OK' : 'FAIL', found, 0, det.join(' '));
  }
  // I6
  {
    const c = readCur('docs/TODO-CLIENT.md');
    const n = c == null ? 0 : c.split('\n').filter((l) => l.includes('src/content/') && l.includes(':')).length;
    const tinta = gitSafe('grep', '-o', 'TODO-CLIENT', 'master', '--', 'src/content').split('\n').filter(Boolean).length;
    set('I6', n >= tinta ? 'OK' : 'FAIL', n, tinta, c == null ? 'file missing' : '');
  }
  // I7
  {
    const pages = targets.filter((f) => f.startsWith('src/pages/'));
    const bad = pages.filter((f) => { const c = readCur(f); return c == null || !c.includes('description'); });
    set('I7', bad.length === 0 ? 'OK' : 'FAIL', bad.length, 0, bad.join(' '));
  }
  // I8 — once, at the end
  let out = '';
  let code = 0;
  try {
    out = execFileSync('npm', ['run', 'check'], { cwd: ctx.root, encoding: 'utf8', maxBuffer: 2 ** 28, stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (e) {
    out = `${e.stdout || ''}${e.stderr || ''}`;
    code = typeof e.status === 'number' ? e.status : 1;
  }
  const em = out.match(/-\s*(\d+)\s+errors?/);
  const wm = out.match(/-\s*(\d+)\s+warnings?/);
  const check = { errors: em ? Number(em[1]) : null, warnings: wm ? Number(wm[1]) : null, exit: code };
  let baseErr = 0;
  const bf = path.join(SCRIPT_DIR, 'cell-baseline-simplu.txt');
  if (fs.existsSync(bf)) {
    const bm = fs.readFileSync(bf, 'utf8').match(/errors=(\d+)/);
    if (bm) baseErr = Number(bm[1]);
  }
  const err = check.errors == null ? 999 : check.errors;
  set('I8', err <= baseErr ? 'OK' : 'FAIL', err, baseErr, `warnings=${check.warnings} exit=${check.exit}`);

  return { items, check };
}

export function afiseazaI(items) {
  for (const id of I_IDS) {
    const it = items[id];
    console.log(`${id} ${LABEL[id]}: ${it.status} (found ${it.found}, target ${it.target})`);
  }
  const ok = I_IDS.filter((id) => items[id].status === 'OK').length;
  console.log(`I: ${ok}/${I_IDS.length} ok, ${I_IDS.length - ok} fail`);
  return ok;
}

// ---------- CLI ----------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const argv = process.argv.slice(2);
  let root = '';
  let jsonOut = '';
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--json') jsonOut = argv[++i];
    else if (a.startsWith('--')) { console.error(`Argument necunoscut: ${a}`); process.exit(2); }
    else if (!root) root = a;
    else { console.error(`Extra argument: ${a}`); process.exit(2); }
  }
  if (!root) { console.error('Uz: verifica-simplu.next.mjs <root> [--json <out>]'); process.exit(2); }
  root = path.resolve(root);
  if (!fs.existsSync(path.join(root, '.git'))) { console.error(`Nu e worktree git: ${root}`); process.exit(2); }

  const ctx = creeazaContext(root);
  const { items, check } = itemiI(ctx);
  const ok = afiseazaI(items);
  if (jsonOut) {
    const sumar = { ok: 0, fail: 0 };
    for (const id of I_IDS) sumar[items[id].status === 'OK' ? 'ok' : 'fail']++;
    fs.mkdirSync(path.dirname(path.resolve(jsonOut)), { recursive: true });
    fs.writeFileSync(jsonOut, `${JSON.stringify({ root, items, summary: sumar, check }, null, 2)}\n`);
  }
  process.exit(ok === I_IDS.length ? 0 : 1);
}
