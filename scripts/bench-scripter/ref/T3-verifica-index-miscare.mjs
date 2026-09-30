import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

const arg = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i > 0 ? process.argv[i + 1] : d; };
const url = arg('url', 'http://localhost:4321/');
const out = arg('out', 'docs/polish/capturi-miscare/');
const vps = arg('vp', '390x844,900x900,1440x900').split(',').map((s) => s.split('x').map(Number));
const pas = Number(arg('pas', 2));
const latMic = Number(arg('mic', 800));
// 🔴 playwright nu e în package.json; se ia din cache-ul npx, versiunea care se potrivește cu chromium din ~/.cache/ms-playwright — RETETE «Măsori bugetul»
const pwPath = arg('pw', process.env.PW_CORE || (() => {
  const base = join(homedir(), '.npm/_npx');
  const c = readdirSync(base).map((d) => join(base, d, 'node_modules/playwright-core')).filter((p) => { try { readdirSync(p); return true; } catch { return false; } });
  const rev = readdirSync(join(homedir(), '.cache/ms-playwright')).filter((d) => d.startsWith('chromium-')).map((d) => d.split('-')[1]);
  return c.find((p) => { try { return rev.includes(JSON.parse(readFileSync(`${p}/browsers.json`, 'utf8')).browsers.find((b) => b.name === 'chromium').revision); } catch { return false; } });
})());

const citeste = () => {
  const el = [];
  const add = (nume, e, strat) => e && el.push([nume, e, strat]);
  [...document.querySelectorAll('.scena > *')].forEach((s, i) => add(`strat${i}`, s, true));
  add('h1', document.querySelector('.hero h1')); add('subtitlu', document.querySelector('.hero-sub'));
  add('vaza', document.querySelector('.hero-vaza'));
  const g = document.querySelectorAll('.hero-vaza g'); add('inel-prim', g[0]); add('inel-ultim', g[g.length - 1]);
  add('filament', document.querySelector('.filament'));
  document.querySelectorAll('.produs').forEach((p, i) => { add(`text${i + 1}`, p.querySelector('.produs-text')); add(`poza${i + 1}`, p.querySelector('.apare-poza')); });
  add('la-comanda', document.querySelector('#la-comanda')); add('contact', document.querySelector('#contact')); add('footer', document.querySelector('footer'));
  const r = (x) => +(+x).toFixed(3);
  const efop = (e) => { let o = 1; for (let x = e; x && x.nodeType === 1; x = x.parentElement) o *= +getComputedStyle(x).opacity; return o; };
  const date = {};
  const px = (v, H) => (v.endsWith('%') ? parseFloat(v) * H / 100 : parseFloat(v)) || 0;
  const una = (e) => {
    const cs = getComputedStyle(e), b = e.getBoundingClientRect();
    const tf = [cs.transform, cs.translate, cs.scale, cs.rotate].filter((x) => x && x !== 'none' && x !== 'matrix(1, 0, 0, 1, 0, 0)').join(' ').replace(/(-?\d+\.?\d*(e-?\d+)?)/g, (m) => String(r(m))) || 'none';
    const m = cs.clipPath.match(/inset\(([^)]*)\)/); const v = m ? m[1].split(/\s+/) : [];
    const inchis = !!m && px(v[0], b.height) + px(v[2] ?? v[0], b.height) >= b.height - 0.5;
    return { cs, b, tf, clip: cs.clipPath, inchis, op: r(cs.opacity) };
  };
  for (const [n, e, strat] of el) {
    const kids = e.matches('.produs-text, .hero-sub, .hero h1') ? [...e.querySelectorAll('.produs-text > *, .cuv > span')] : [];
    const parti = [una(e), ...kids.map(una)];
    const { cs, b } = parti[0];
    const op = Math.min(...parti.map((x) => x.op)), tf = parti.map((x) => x.tf).join(';'), clip = parti.map((x) => x.clip).join(';');
    const st = strat ? null : e.closest('.scena > *');
    const inchis = parti[0].inchis || (!!st && una(st).inchis);
    const inView = b.bottom > 0 && b.top < innerHeight && b.right > 0 && b.left < innerWidth && b.width > 0 && b.height > 0;
    const ef = r(efop(e) * (kids.length ? Math.max(...parti.slice(1).map((x) => x.op)) : 1));
    date[n] = { op, ef, tf, clip, viz: inView && ef > 0.1 && !inchis && cs.visibility !== 'hidden', strat: !!strat, final: inView && ef > 0.1 && !inchis && cs.visibility !== 'hidden' && op >= 0.999 && parti.every((x) => x.tf === 'none') && !parti.some((x) => x.inchis) };
  }
  return { date, ox: document.documentElement.scrollWidth > innerWidth };
};

const initCls = () => { window.__cls = 0; new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: 'layout-shift', buffered: true }); };
const cadru = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
const intervale = (arr) => { const o = []; let s = null; arr.forEach(([p, v], i) => { if (v && s === null) s = p; if (!v && s !== null) { o.push(`${s}-${arr[i - 1][0]}`); s = null; } }); if (s !== null) o.push(`${s}-${arr.at(-1)[0]}`); return o; };

const rez = { url, pas, latimi: {}, reduce: {}, faraView: {}, capturi: [] };
let browser;
try {
  if (!pwPath) throw new Error('playwright-core negăsit');
  const { chromium } = await import(join(pwPath, 'index.mjs'));
  browser = await chromium.launch();
  mkdirSync(out, { recursive: true });
  const pagina = async (w, h, { reduce = false, faraView = false } = {}) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: reduce ? 'reduce' : 'no-preference', deviceScaleFactor: Math.min(1, latMic / w) });
    const page = await ctx.newPage();
    // 🔴 flagul Blink nu oprește view(): @supports se rescrie în răspunsuri — PATTERNS «Scena fixată»
    if (faraView) {
      await page.route('**/*', async (rt) => { const r = await rt.fetch(); const ct = r.headers()['content-type'] || '';
        if (!/html|css|javascript/.test(ct)) return rt.fulfill({ response: r });
        rt.fulfill({ response: r, body: (await r.text()).replace(/@supports\s*\(\s*animation-timeline:\s*(view|scroll)\(\)\s*\)/g, '@supports (nu-exista: 1)') }); });
      await page.addInitScript(() => { const s = CSS.supports; CSS.supports = (...a) => /timeline/.test(a.join(' ')) ? false : s.apply(CSS, a); });
    }
    await page.addInitScript(initCls);
    await page.goto(url, { waitUntil: 'load' });
    await page.waitForTimeout(2500);
    return { ctx, page };
  };
  const derula = async (page) => {
    const max = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    const s = [];
    for (let p = 0; p <= 100; p += pas) { await page.evaluate((y) => scrollTo(0, y), Math.round(max * p / 100)); await page.evaluate(cadru); s.push([p, await page.evaluate(citeste)]); }
    return s;
  };
  for (const [w, h] of vps) {
    const k = `${w}x${h}`;
    const { ctx, page } = await pagina(w, h);
    const f = `${out}hero-${w}-mic.png`; await page.screenshot({ path: f }); rez.capturi.push(f);
    const s = await derula(page);
    const cls = +(await page.evaluate(() => window.__cls)).toFixed(4);
    const nume = Object.keys(s[0][1].date), el = {};
    for (const n of nume) {
      const ser = s.map(([p, x]) => [p, x.date[n]]);
      const sig = (d) => `${d.op}|${d.tf}|${d.clip}`;
      const start = ser.find(([, d]) => sig(d) !== sig(ser[0][1]))?.[0] ?? null;
      const fi = ser.findIndex(([, d]) => d.final);
      let tine = null;
      if (fi >= 0) { let j = fi; while (j + 1 < ser.length && ser[j + 1][1].final) j++; tine = ser[j][0] - ser[fi][0]; }
      el[n] = { start, final: fi >= 0 ? ser[fi][0] : null, tine, ajunge: fi >= 0, viz: intervale(ser.map(([p, d]) => [p, d.viz])) };
    }
    const straturi = nume.filter((n) => s[0][1].date[n].strat);
    const supra = intervale(s.map(([p, x]) => [p, straturi.filter((n) => x.date[n].viz).length >= 2]));
    const gol = intervale(s.map(([p, x]) => [p, !nume.some((n) => n !== 'filament' && !x.date[n].strat && x.date[n].viz)]));
    rez.latimi[k] = { cls, overflow: intervale(s.map(([p, x]) => [p, x.ox])), suprapuneri: supra, gol, el };
    await ctx.close();
    for (const [mod, opt] of [['reduce', { reduce: true }], ['faraView', { faraView: true }]]) {
      const { ctx: c2, page: p2 } = await pagina(w, h, opt);
      const s2 = await derula(p2);
      const n2 = Object.keys(s2[0][1].date).filter((n) => !s2[0][1].date[n].strat && n !== 'filament');
      const niciodata = n2.filter((n) => !s2.some(([, x]) => x.date[n].viz));
      rez[mod][k] = { totulVizibil: niciodata.length === 0, niciodata, overflow: intervale(s2.map(([p, x]) => [p, x.ox])), cls: +(await p2.evaluate(() => window.__cls)).toFixed(4) };
      await c2.close();
    }
  }
  writeFileSync(`${out}masuratori.json`, JSON.stringify(rez, null, 1));
  console.log(JSON.stringify(rez));
} catch (e) { console.error(e); process.exitCode = 1; } finally { await browser?.close(); }
