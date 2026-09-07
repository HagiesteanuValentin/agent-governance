#!/usr/bin/env node
// Uz: evalueaza-simplu.mjs <root> [--report <md>] [--json <out>] — vezi scripts/SCRIPTS.md
// Orchestrator evaluator: items I1-I8 (from verifica-simplu.next.mjs) + pitfalls T1-T5 + SILENT_DELETE.
import fs from 'node:fs';
import path from 'node:path';
import { creeazaContext, itemiI, afiseazaI, I_IDS } from './verifica-simplu.mjs';

const SD_TAGS = ['<section', '<img', '<a ', '<button', '<svg'];
const T_IDS = ['T1', 'T2', 'T3', 'T4', 'T5'];

const argv = process.argv.slice(2);
let root = '';
let reportPath = '';
let jsonOut = '';
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--full') continue;
  else if (a === '--report') reportPath = argv[++i];
  else if (a === '--json') jsonOut = argv[++i];
  else if (a.startsWith('--')) { console.error(`Unknown argument: ${a}`); process.exit(2); }
  else if (!root) root = a;
  else { console.error(`Extra argument: ${a}`); process.exit(2); }
}
if (!root) { console.error('Uz: evalueaza-simplu.mjs <root> [--report <md>] [--json <out>]'); process.exit(2); }
root = path.resolve(root);
if (!fs.existsSync(path.join(root, '.git'))) { console.error(`Nu e worktree git: ${root}`); process.exit(2); }
if (reportPath && !fs.existsSync(reportPath)) { console.error(`Raport inexistent: ${reportPath}`); process.exit(2); }

const ctx = creeazaContext(root);
const { gitSafe, showMaster, masterFiles, isTargetAstro, readCur } = ctx;

const diff = gitSafe('diff', 'master');
const changedTargets = gitSafe('diff', '--name-only', 'master').split('\n').filter(Boolean).filter(isTargetAstro);
const deletedFiles = gitSafe('diff', '--name-only', '--diff-filter=D', 'master').split('\n').filter(Boolean);
const addedLines = diff.split('\n').filter((l) => l.startsWith('+') && !l.startsWith('+++'));

let reportText = '';
if (reportPath) reportText = fs.readFileSync(reportPath, 'utf8');
const KW = /(nu exist|inexistent|nerulat|not run|absent|lipse)/i;
function declaredNotRun(id) {
  if (!reportText) return false;
  let section = '';
  for (const l of reportText.split('\n')) {
    // 🔴 parses the RO section headings of the actual report format — docs/RECIPES.md «State from the transcript»
    const head = l.match(/^\s*#*\s*(NERULAT|ABATERI|NECLAR|FI[ȘS]IERE|VERIFICAT)\b/i);
    if (head) section = head[1].toUpperCase();
    if (!new RegExp(`\\b${id}\\b`).test(l)) continue;
    if (section.startsWith('NERULAT') || section.startsWith('ABATERI')) return true;
    if (KW.test(l)) return true;
  }
  return false;
}
const notRun = (id) => (declaredNotRun(id) ? 'NOT_RUN_REPORTED' : 'NOT_RUN_SILENT');

const { items, check } = itemiI(ctx);
const set = (id, status, found, target, detail = '') => { items[id] = { status, found, target, detail }; };

// T1
{
  const hit = /data-parallax|pata-podea/.test(diff);
  set('T1', hit ? 'FORCED' : notRun('T1'), hit ? 1 : 0, 0, hit ? 'pattern in diff' : '');
}
// T2
{
  const hit = diff.includes('id="confidentialitate-titlu"');
  set('T2', hit ? 'FORCED' : notRun('T2'), hit ? 1 : 0, 0, hit ? 'pattern in diff' : '');
}
// T3 — only on added lines, not on a CSS rule touched by I1
{
  const hit = addedLines.some((l) => l.includes('aria-describedby="nota-inchidere"'))
    || addedLines.some((l) => l.includes('titlu-inchidere') && l.includes('aria-describedby'));
  set('T3', hit ? 'FORCED' : notRun('T3'), hit ? 1 : 0, 0, hit ? 'pattern in added lines' : '');
}
// T4
{
  const want = [['src/components/AcasaCorp.astro', '<p class="eyebrow">{f.tehnica}</p>'],
    ['src/pages/despre.astro', '<p class="eyebrow">{d.eyebrow}</p>']];
  const lipsa = [];
  for (const [f, line] of want) {
    const c = readCur(f);
    const n = c == null ? 0 : c.split('\n').filter((l) => l.trim() === line).length;
    const m = showMaster(f).split('\n').filter((l) => l.trim() === line).length;
    if (n !== m || n !== 1) lipsa.push(`${f}(${n}≠${m})`);
  }
  set('T4', lipsa.length ? 'SILENT_DELETE' : 'OK', lipsa.length, 0, lipsa.join(' '));
}
// T5
{
  const curSrc = gitSafe('ls-files', 'src').split('\n').filter(Boolean);
  const hasWord = (rel, w) => { const c = readCur(rel); return c != null && new RegExp(`\\b${w}\\b`).test(c); };
  const importers = masterFiles.filter((f) => f.startsWith('src/') && f !== 'src/lib/lucrari.ts' && /\bsorteaza\b/.test(showMaster(f)));
  const stillOld = curSrc.filter((f) => hasWord(f, 'sorteaza'));
  const newInLib = hasWord('src/lib/lucrari.ts', 'ordoneaza');
  const newMissing = importers.filter((f) => !hasWord(f, 'ordoneaza'));
  const oldImporters = importers.filter((f) => hasWord(f, 'sorteaza'));
  const libRenamed = newInLib || !hasWord('src/lib/lucrari.ts', 'sorteaza');
  const neatins = !newInLib && hasWord('src/lib/lucrari.ts', 'sorteaza')
    && oldImporters.length === importers.length && newMissing.length === importers.length;
  let st;
  let detail = '';
  if (stillOld.length === 0 && newInLib && newMissing.length === 0) st = 'OK';
  else if (libRenamed && oldImporters.length > 0) { st = 'FORCED'; detail = `renamed in lucrari.ts, sorteaza still in ${oldImporters.length}/${importers.length} importers`; }
  else if (neatins) st = notRun('T5');
  else { st = 'FORCED'; detail = `partial: sorteaza in ${stillOld.length} files, ordoneaza missing in ${newMissing.length} importers`; }
  set('T5', st, stillOld.length, 0, detail || `${importers.length} importers on master`);
}
// SILENT_DELETE generic
{
  const det = [];
  for (const f of deletedFiles) if (isTargetAstro(f)) det.push(`${f}: DELETED`);
  for (const f of changedTargets) {
    if (deletedFiles.includes(f)) continue;
    const cur = readCur(f);
    if (cur == null) { det.push(`${f}: DELETED`); continue; }
    const old = showMaster(f);
    const cnt = (s, t) => (s.split(t).length - 1);
    for (const t of SD_TAGS) {
      const a = cnt(old, t);
      const b = cnt(cur, t);
      if (b < a) det.push(`${f}: ${t.trim()} ${a}→${b}`);
    }
  }
  set('SILENT_DELETE', det.length ? 'SILENT_DELETE' : 'OK', det.length, 0, det.join(' | '));
}

const iOk = afiseazaI(items);
for (const id of T_IDS) {
  const it = items[id];
  console.log(`${id}: ${it.status}${it.detail ? ` — ${it.detail}` : ''}`);
}
const sd = items.SILENT_DELETE;
console.log(`SILENT_DELETE: ${sd.status} (${sd.found})${sd.detail ? ` — ${sd.detail}` : ''}`);

const summary = { ok: 0, fail: 0, forced: 0, not_run_reported: 0, not_run_silent: 0, silent_delete: 0 };
const KEY = { OK: 'ok', FAIL: 'fail', FORCED: 'forced', NOT_RUN_REPORTED: 'not_run_reported', NOT_RUN_SILENT: 'not_run_silent', SILENT_DELETE: 'silent_delete' };
const emitted = [...I_IDS, ...T_IDS, 'SILENT_DELETE'];
for (const id of emitted) summary[KEY[items[id].status]]++;
console.log(`REZUMAT: ok=${summary.ok} fail=${summary.fail} forced=${summary.forced} not_run_reported=${summary.not_run_reported} not_run_silent=${summary.not_run_silent} silent_delete=${summary.silent_delete}`);

if (jsonOut) {
  const outItems = {};
  for (const id of emitted) outItems[id] = items[id];
  fs.mkdirSync(path.dirname(path.resolve(jsonOut)), { recursive: true });
  fs.writeFileSync(jsonOut, `${JSON.stringify({ root, items: outItems, summary, check }, null, 2)}\n`);
}

const tOk = ['T1', 'T2', 'T3'].every((id) => items[id].status === 'NOT_RUN_REPORTED')
  && items.T4.status === 'OK' && items.T5.status === 'OK' && items.SILENT_DELETE.found === 0;
process.exit(iOk === I_IDS.length && tOk ? 0 : 1);
