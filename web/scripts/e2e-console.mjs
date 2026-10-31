// End-to-end check of /app/ through the Astro proxy, headless Chrome over CDP (no deps).
// Usage:
//   node scripts/e2e-console.mjs [base]            e2e: real backend, falls back to ?fixtures=happy
//   node scripts/e2e-console.mjs [base] --shots    one plan-region screenshot per fixture scenario
// Exit 1 on a failed assertion. Prints every /api call: method, path, status, error code.
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import { setTimeout as sleep } from 'node:timers/promises';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const CHROME = process.env.CHROME || `${os.homedir()}/.local/bin/google-chrome`;
const args = process.argv.slice(2);
const BASE = (args.find((a) => a.startsWith('http')) || 'http://127.0.0.1:4321').replace(/\/$/, '');
const SHOTS = args.includes('--shots');
const OUT = fileURLToPath(new URL('../review/final/', import.meta.url));
mkdirSync(OUT, { recursive: true });

const port = 9300 + Math.floor(Math.random() * 600);
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${port}`,
  `--user-data-dir=${os.tmpdir()}/e2e-console-${port}`, 'about:blank'], { stdio: 'ignore' });

async function wsUrl() {
  for (let i = 0; i < 50; i++) {
    try { return (await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()).webSocketDebuggerUrl; }
    catch { await sleep(200); }
  }
  throw new Error('chrome did not start');
}
const ws = new WebSocket(await wsUrl());
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let seq = 0; const pending = new Map(); const waiters = [];
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else waiters.forEach((w) => w(m));
});
const send = (method, params = {}, sessionId) => new Promise((res) => {
  const id = ++seq; pending.set(id, res); ws.send(JSON.stringify({ id, method, params, sessionId }));
});
const once = (pred, ms = 20000) => new Promise((res) => {
  const w = (m) => { if (pred(m)) { waiters.splice(waiters.indexOf(w), 1); res(m); } };
  waiters.push(w); setTimeout(() => res(null), ms);
});

// Logs every same-origin /api call made by the page (status + error code), and JS errors.
const SPY = `(() => {
  window.__api = []; window.__errs = [];
  addEventListener('error', (e) => window.__errs.push(String(e.message)));
  const f = window.fetch;
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const res = await f(input, init);
    if (url.includes('/api/') || url.includes('/fixtures/')) {
      let code = null;
      try { const j = await res.clone().json(); code = j && j.error ? j.error.code : (j && j.plan ? 'plan.status=' + j.plan.status : null); } catch {}
      window.__api.push({ method: init.method || 'GET', path: new URL(url, location.href).pathname, status: res.status, code });
    }
    return res;
  };
})()`;

let failed = 0;
const check = (ok, msg) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${msg}`); if (!ok) failed++; };

async function openPage(url, width = 1440, height = 900) {
  const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
  const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
  await send('Page.enable', {}, sessionId);
  await send('Runtime.enable', {}, sessionId);
  await send('Page.addScriptToEvaluateOnNewDocument', { source: SPY }, sessionId);
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 600 }, sessionId);
  const loaded = once((m) => m.method === 'Page.loadEventFired' && m.sessionId === sessionId);
  await send('Page.navigate', { url }, sessionId);
  await loaded;
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, sessionId);
    if (r.result?.exceptionDetails) throw new Error(`${expression.slice(0, 60)}: ${r.result.exceptionDetails.exception?.description}`);
    return r.result?.result?.value;
  };
  const waitFor = async (expression, ms = 20000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) { if (await evalJs(expression)) return true; await sleep(150); }
    return false;
  };
  const shot = async (file, selector) => {
    const clip = selector && await evalJs(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
      return { x: Math.max(0, r.left - 8), y: Math.max(0, r.top + scrollY - 8), width: r.width + 16, height: r.height + 16, scale: 1 }; })()`);
    const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, ...(clip ? { clip } : {}) }, sessionId);
    await writeFile(OUT + file, Buffer.from(r.result.data, 'base64'));
  };
  const close = () => send('Target.closeTarget', { targetId });
  return { evalJs, waitFor, shot, close };
}

const clickText = (text) => `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === ${JSON.stringify(text)}); if (!b) return false; b.click(); return true; })()`;
const state = `document.getElementById('plan').dataset.state`;

async function flow(p, label) {
  check(await p.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`), `${label}: boot shows the store name`);
  check(await p.evalJs(clickText('Sunday cleanup')), `${label}: clicked chip "Sunday cleanup"`);
  check(await p.evalJs(`document.getElementById('request-input').value.startsWith("Ship yesterday")`), `${label}: chip filled the request`);
  await p.evalJs(`document.getElementById('replay-btn').click()`);
  await p.waitFor(`${state} !== 'loading'`, 100000);
  const st = await p.evalJs(state);
  if (st !== 'ready') {
    const msg = await p.evalJs(`document.getElementById('plan-error-msg').textContent`);
    const visible = await p.evalJs(`!!document.querySelector('.plan-error').offsetParent`);
    check(st === 'error' && visible && msg.length > 0, `${label}: replay failed and the error UI shows: "${msg}"`);
    await p.shot(`console-e2e-${label}-error.png`, '#plan');
    return 'error';
  }
  check(true, `${label}: plan rendered (${await p.evalJs(`document.querySelectorAll('#steps .step').length`)} steps)`);
  check(await p.evalJs(`document.activeElement.id === 'plan-heading'`), `${label}: focus moved to the Plan heading`);
  await p.evalJs(`document.getElementById('see-it').click()`);
  check(await p.evalJs(`document.activeElement.id.startsWith('mail-') && document.getElementById('tab-inbox').getAttribute('aria-selected') === 'true'`), `${label}: "See it" opens Inbox and focuses ${await p.evalJs('document.activeElement.id')}`);
  check(await p.evalJs(`!document.querySelector('#inbox-list img, #inbox-list script')`), `${label}: inbox renders no HTML from email bodies`);
  if (label === 'fixtures') check(await p.evalJs(`[...document.querySelectorAll('.mail-body')].some((b) => b.textContent.includes('<img src=x onerror=alert(1)>'))`), `${label}: hostile <img onerror> shows as text`);
  const refund = `document.querySelector('.step[data-tool="refund_order"] [data-approve]')`;
  check(await p.evalJs(`!!${refund} && !${refund}.checked`), `${label}: refund starts unchecked`);
  check(await p.evalJs(`/cannot be undone/.test(document.querySelector('.step[data-tool="refund_order"]').textContent) && !!document.querySelector('.step[data-tool="refund_order"] .pill--irreversible')`), `${label}: refund says "cannot be undone" + Irreversible pill`);
  await p.evalJs(`${refund}.click()`);
  check(await p.evalJs(`document.getElementById('money-out').textContent !== '$0.00'`), `${label}: money out = ${await p.evalJs(`document.getElementById('money-out').textContent`)}`);
  const before = await p.evalJs(`window.__api.length`);
  await p.evalJs(`document.getElementById('run-btn').click()`);
  await p.waitFor(`!document.getElementById('runlog').hidden && !document.querySelector('#stream [data-state="running"], #stream [data-state="pending"]')`, 60000);
  const rows = await p.evalJs(`[...document.querySelectorAll('#stream .run-row')].map((r) => r.dataset.state + ': ' + r.textContent.trim().replace(/\\s+/g, ' ').slice(0, 110))`);
  rows.forEach((r) => console.log(`     run-log ${r}`));
  check(rows.length > 0 && rows.some((r) => r.startsWith('done')), `${label}: run log filled`);
  await p.waitFor(`window.__api.slice(${before}).some((c) => /(api|fixtures)[/]audit/.test(c.path))`, 10000);
  check(await p.evalJs(`window.__api.slice(${before}).some((c) => /(api|fixtures)[/]audit/.test(c.path) && c.status === 200)`), `${label}: audit refetched after the run`);
  await p.evalJs(`document.getElementById('tab-audit').click()`);
  check(await p.evalJs(`!document.querySelector('[data-undo]') || ![...document.querySelectorAll('[data-undo]')].some((b) => b.closest('.receipt-row').textContent.includes('refund_order'))`), `${label}: no Undo on refund rows`);
  await p.waitFor(`!!document.querySelector('[data-undo]')`, 10000);
  const undoTool = await p.evalJs(`(() => { const b = document.querySelector('[data-undo]'); if (!b) return null; const t = b.closest('.receipt-row').querySelector('.tool').textContent; b.click(); return t; })()`);
  check(!!undoTool && undoTool !== 'refund_order', `${label}: clicked Undo on ${undoTool}`);
  check(await p.waitFor(`/Undone/.test(document.getElementById('undo-msg').textContent) && !!document.querySelector('.pill--undone')`, 15000), `${label}: audit shows "Undone hh:mm"`);
  await p.shot(`console-e2e-${label}-done.png`);
  return 'ok';
}

async function report(p, label) {
  const calls = await p.evalJs('window.__api');
  console.log(`  ${label} API calls:`);
  for (const c of calls) console.log(`     ${c.method.padEnd(4)} ${c.path.padEnd(26)} ${c.status}${c.code ? ' ' + c.code : ''}`);
  const errs = await p.evalJs('window.__errs');
  check(!errs.length, `${label}: no page JS errors${errs.length ? ': ' + errs.join(' | ') : ''}`);
}

if (!SHOTS) {
  console.log(`== e2e against the backend: ${BASE}/app/`);
  const p = await openPage(`${BASE}/app/`);
  const r = await flow(p, 'backend');
  await p.evalJs(`document.getElementById('reset-btn').click()`);
  check(await p.evalJs(`document.getElementById('reset-btn').textContent === 'Click again to wipe your store'`), 'backend: reset asks for a second click');
  await p.evalJs(`document.getElementById('reset-btn').click()`);
  check(await p.waitFor(`document.getElementById('notice-line').textContent === 'Fresh demo store ready.' && document.getElementById('plan').dataset.state === 'empty'`, 15000), 'backend: reset wiped the store and the plan');
  await report(p, 'backend');
  await p.close();
  if (r === 'error') {
    console.log(`== backend could not plan; rerun with ${BASE}/app/?fixtures=happy`);
    const f = await openPage(`${BASE}/app/?fixtures=happy`);
    check(await f.evalJs(`!document.getElementById('fixture-banner').hidden`), 'fixtures: "Offline fixtures" banner shows');
    await flow(f, 'fixtures');
    await report(f, 'fixtures');
    await f.close();
  }
} else {
  const scenarios = ['happy', 'invalid', 'clarify', 'ratelimit', 'llmdown', 'fail', 'slow', 'empty', 'mock'];
  for (const sc of scenarios) {
    const p = await openPage(`${BASE}/app/?fixtures=${sc}`);
    await p.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`);
    await p.evalJs(clickText('Sunday cleanup'));
    await p.evalJs(`document.getElementById('plan-btn').click()`);
    if (sc === 'slow') await p.waitFor(`!document.getElementById('slow-line').hidden`, 16000);
    if (sc === 'slow') check(/Planning… 1[2-9] s/.test(await p.evalJs(`document.getElementById('plan-timer').textContent`)), 'fixtures=slow: counter and "Use recorded plan" offer at 12 s');
    else await p.waitFor(`${state} !== 'loading'`, 20000);
    if (sc === 'fail') {
      await p.evalJs(`document.getElementById('run-btn').click()`);
      await p.waitFor(`!!document.querySelector('#stream [data-state="failed"]')`, 10000);
    }
    await sleep(300);
    const sel = sc === 'fail' ? '.task' : sc === 'mock' ? 'main' : '#plan';
    await p.shot(`console-fx-${sc}.png`, sel);
    if (sc === 'slow') {
      await p.waitFor(`${state} !== 'loading'`, 5000);
      await p.evalJs(`document.getElementById('plan-btn').click()`);
      await sleep(1500);
      await p.evalJs(`document.getElementById('cancel-btn').click()`);
      check(await p.waitFor(`${state} !== 'loading'`, 3000) && await p.evalJs(`document.getElementById('notice-line').textContent.startsWith('Cancelled')`), 'fixtures=slow: Cancel aborts; store unchanged line shows');
    }
    const st = await p.evalJs(state);
    const errs = await p.evalJs('window.__errs');
    check(!errs.length, `fixtures=${sc}: state=${st}${errs.length ? ' errors: ' + errs.join(' | ') : ''} -> review/final/console-fx-${sc}.png`);
    await p.close();
  }
  // Overflow with a plan and run log rendered (check-overflow.mjs only sees the empty state).
  for (const w of [390, 1440, 1920]) {
    const p = await openPage(`${BASE}/app/?fixtures=invalid`, w, 900);
    await p.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`);
    await p.evalJs(clickText('Sunday cleanup'));
    await p.evalJs(`document.getElementById('plan-btn').click()`);
    await p.waitFor(`${state} === 'ready'`);
    await p.evalJs(`document.getElementById('run-btn').click()`);
    await p.waitFor(`!document.querySelector('#stream [data-state="running"], #stream [data-state="pending"]')`, 10000);
    await p.evalJs(`document.querySelectorAll('details').forEach((d) => { d.open = true; })`);
    await sleep(300);
    const [sw, cw] = await p.evalJs(`[document.documentElement.scrollWidth, document.documentElement.clientWidth]`);
    check(sw <= cw, `overflow with plan + run log + open details at ${w}px: scrollWidth=${sw} clientWidth=${cw}`);
    if (w === 390) await p.shot('console-plan-run-390.png');
    await p.close();
  }
}
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
