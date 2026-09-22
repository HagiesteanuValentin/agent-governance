#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const args = process.argv.slice(2);
let root = null, jsonOut = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--json') { jsonOut = args[++i]; if (!jsonOut) usage('lipsește <out> după --json'); }
  else if (args[i].startsWith('--')) usage(`argument necunoscut ${args[i]}`);
  else if (!root) root = path.resolve(args[i]);
  else usage(`argument în plus ${args[i]}`);
}
function usage(m) { console.error(`✗ ${m}\nfolosire: node verifica-complex.mjs <root> [--json <out>]`); process.exit(2); }
if (!root) usage('lipsește <root>');
for (const p of ['scripts/index-lucrari.mjs', 'src/content/lucrari', 'node_modules', 'functions']) {
  if (!fs.existsSync(path.join(root, p))) usage(`${root} nu e checkout blueprint_pictura (lipsește ${p})`);
}

const I1_TINTA = { 'papadia': 1250, 'prin-obiectiv': 1450, 'poarta-de-stanca': 850, 'natura-statica-cu-cireasa': 650 };
const I2_PASTRATE = { 'camp-rosu': 450, 'identitati': 1250, 'rose': 450, 'somn-pe-nisip': 1300, 'sub-nufar': 1280 };
const I2_FARA = 'stanci-la-reflux';
const I3_RAND = 'lucrare?.pretRon !== undefined && lucrare.pretRon >= rg.minPret';
const BASE = 'da90148';

const git = (...a) => spawnSync('git', ['-C', root, ...a], { encoding: 'utf8' });
const statusInainte = git('status', '--porcelain').stdout;
const rez = {};

function genereazaInTmp() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'verifica-complex-'));
  try {
    fs.mkdirSync(path.join(tmp, 'scripts'));
    fs.copyFileSync(path.join(root, 'scripts/index-lucrari.mjs'), path.join(tmp, 'scripts/index-lucrari.mjs'));
    fs.cpSync(path.join(root, 'src/content/lucrari'), path.join(tmp, 'src/content/lucrari'), { recursive: true });
    fs.symlinkSync(path.join(root, 'node_modules'), path.join(tmp, 'node_modules'));
    const r = spawnSync(process.execPath, ['scripts/index-lucrari.mjs'], { cwd: tmp, encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`generatorul în tmp a ieșit ${r.status}: ${r.stderr.trim()}`);
    return fs.readFileSync(path.join(tmp, 'src/generated/lucrari-server.ts'), 'utf8');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

let intrari = {};
try {
  const gen = genereazaInTmp();
  for (const m of gen.matchAll(/^\s*'([^']+)':\s*\{(.*)\},?\s*$/gm)) {
    const pr = m[2].match(/\bpretRon:\s*(\d+(?:\.\d+)?)/);
    intrari[m[1]] = { pretRon: pr ? Number(pr[1]) : undefined, pretEstimat: /\bpretEstimat:\s*true\b/.test(m[2]) };
  }
} catch (e) {
  console.error(`✗ ${e.message}`);
  intrari = null;
}

if (intrari) {
  const potrivite = Object.entries(I1_TINTA).filter(([s, v]) => intrari[s]?.pretRon === v).length;
  rez.I1 = { ok: potrivite === 4, gasit: potrivite, tinta: 4 };
  const slugi = Object.keys(intrari);
  const cuPret = slugi.filter((s) => intrari[s].pretRon !== undefined).length;
  const estimate = slugi.filter((s) => intrari[s].pretEstimat);
  const estimateCorecte = estimate.length === 4 && estimate.every((s) => s in I1_TINTA);
  const pastrate = Object.entries(I2_PASTRATE).every(([s, v]) => intrari[s]?.pretRon === v && !intrari[s].pretEstimat);
  const faraPret = intrari[I2_FARA] !== undefined && intrari[I2_FARA].pretRon === undefined;
  rez.I2 = {
    ok: cuPret === 9 && slugi.length === 10 && faraPret && estimateCorecte && pastrate,
    gasit: `${cuPret}/${slugi.length}, ${estimate.length} estimate${faraPret ? '' : `, ${I2_FARA} are pretRon`}${pastrate ? '' : ', cele 5 păstrate diferă'}`,
    tinta: '9/10, 4 estimate',
  };
} else {
  rez.I1 = { ok: false, gasit: 'eroare generator', tinta: 4 };
  rez.I2 = { ok: false, gasit: 'eroare generator', tinta: '9/10, 4 estimate' };
}

const scoringPath = path.join(root, 'functions/_lib/scoring.ts');
const areRand = fs.existsSync(scoringPath) && fs.readFileSync(scoringPath, 'utf8').includes(I3_RAND);
const diffReguli = git('diff', BASE, '--', 'src/content/scoring/reguli.json');
const reguliNeatinse = diffReguli.status === 0 && diffReguli.stdout.trim() === '';
rez.I3 = { ok: areRand && reguliNeatinse, gasit: `rând minPret ${areRand ? 'da' : 'nu'}, reguli.json ${reguliNeatinse ? 'neatins' : 'modificat'}`, tinta: 'rând da, reguli.json neatins' };

let aparitii = 0, cuPretEstimat = false;
for (const f of ['functions/api/lead.ts', 'functions/_lib/email.ts']) {
  const p = path.join(root, f);
  if (!fs.existsSync(p)) continue;
  const t = fs.readFileSync(p, 'utf8');
  const n = (t.match(/preț estimat/gi) || []).length;
  aparitii += n;
  if (n >= 1 && t.includes('pretEstimat')) cuPretEstimat = true;
}
rez.I4 = { ok: cuPretEstimat, gasit: `${aparitii}${aparitii && !cuPretEstimat ? ' (fără pretEstimat)' : ''}`, tinta: '≥1, cu pretEstimat' };

const v = spawnSync(process.execPath, ['scripts/index-lucrari.mjs', '--verifica'], { cwd: root, encoding: 'utf8' });
rez.I5 = { ok: v.status === 0, gasit: `exit ${v.status}`, tinta: 'exit 0' };

const statusDupa = git('status', '--porcelain').stdout;
const readOnly = statusInainte === statusDupa;

for (const [k, r] of Object.entries(rez)) console.log(`${k} | ${r.ok ? 'ok' : 'FAIL'} | găsit ${r.gasit}, țintă ${r.tinta}`);
const n = Object.values(rez).filter((r) => r.ok).length;
console.log(`OK ${n}/5`);
if (!readOnly) console.error(`✗ git status --porcelain diferă după rulare pe ${root}`);
if (jsonOut) fs.writeFileSync(jsonOut, JSON.stringify(rez, null, 2) + '\n');
process.exit(n === 5 && readOnly ? 0 : 1);
