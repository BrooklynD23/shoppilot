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
const OUT = fileURLToPath(new URL(`../review/${process.env.SHOTS_DIR || 'final'}/`, import.meta.url));
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
  // Real key events (Puppeteer's shapes), so :focus-visible and default actions behave as for a person.
  const KEYS = { Tab: { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 }, Enter: { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' },
    Space: { key: ' ', code: 'Space', windowsVirtualKeyCode: 32, text: ' ' } };
  const key = async (name) => {
    const k = KEYS[name];
    await send('Input.dispatchKeyEvent', { type: k.text ? 'keyDown' : 'rawKeyDown', ...k }, sessionId);
    await send('Input.dispatchKeyEvent', { type: 'keyUp', ...k }, sessionId);
  };
  await send('Page.bringToFront', {}, sessionId);
  return { evalJs, waitFor, shot, close, key };
}

const clickText = (text) => `(() => { const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === ${JSON.stringify(text)}); if (!b) return false; b.click(); return true; })()`;
const state = `document.getElementById('plan').dataset.state`;
const word = (agent) => `document.querySelector('#crew [data-agent="${agent}"] [data-word]').textContent`;
const mood = (agent) => `document.querySelector('#crew [data-agent="${agent}"]').dataset.mood`;

async function flow(p, label) {
  check(await p.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`), `${label}: boot shows the store name`);
  check(await p.evalJs(`document.querySelectorAll('#crew .member').length === 7`), `${label}: team stage has 7 teammates (mode ${await p.evalJs(`document.getElementById('stage').dataset.mode`)})`);
  check(await p.waitFor(`${word('guard')} !== 'Ready'`, 10000), `${label}: Guard reports the inbox screen: "${await p.evalJs(word('guard'))}"`);
  await p.waitFor(`!document.getElementById('inbox-list').hasAttribute('aria-busy')`, 10000);
  const inbox = await p.evalJs(`({ bar: document.querySelector('.cbar [data-count="inbox"]').textContent, guard: ${word('guard')},
    blocked: document.querySelectorAll('#inbox-list .stamp:not(.stamp--held)').length, held: document.querySelectorAll('#inbox-list .stamp--held').length })`);
  const counted = [inbox.blocked && `${inbox.blocked} blocked`, inbox.held && `${inbox.held} held`].filter(Boolean).join(', ');
  check((inbox.bar === counted || (!counted && /^\d+$/.test(inbox.bar)))
    && inbox.guard === (inbox.blocked ? `Blocked ${inbox.blocked}` : inbox.held ? `Held ${inbox.held}` : 'All clear'),
    `${label}: one inbox count: bar "${inbox.bar}", stamps ${inbox.blocked} BLOCKED + ${inbox.held} HELD, Guard "${inbox.guard}"`);
  check(await p.evalJs(clickText('Sunday cleanup')), `${label}: clicked chip "Sunday cleanup"`);
  check(await p.evalJs(`document.getElementById('request-input').value.startsWith("Ship yesterday")`), `${label}: chip filled the request`);
  await p.evalJs(`document.getElementById('replay-btn').click()`);
  await p.waitFor(`${state} !== 'loading'`, 100000);
  const st = await p.evalJs(state);
  if (st !== 'ready') {
    const msg = await p.evalJs(`document.getElementById('plan-error-msg').textContent`);
    const visible = await p.evalJs(`!!document.querySelector('.plan-error').offsetParent`);
    check(st === 'error' && visible && msg.length > 0, `${label}: replay failed and the error UI shows: "${msg}"`);
    check(!/python|tests\.eval/.test(msg + await p.evalJs(`document.getElementById('speech-line').textContent`)), `${label}: no developer command in the error box or the bubble`);
    check(await p.evalJs(`${mood('planner')} === 'alarm' && document.getElementById('speech-line').textContent.length > 0`), `${label}: Planner shows the failure on stage`);
    await p.shot(`console-e2e-${label}-error.png`, '#plan');
    return 'error';
  }
  check(true, `${label}: plan rendered (${await p.evalJs(`document.querySelectorAll('#steps .step').length`)} steps)`);
  check(await p.evalJs(`document.activeElement.id === 'plan-heading'`), `${label}: focus moved to the Plan heading`);
  check(await p.waitFor(`!document.querySelector('#steps [data-enter]') && ${word('executor')} === 'Waiting for you'`, 20000), `${label}: team replay ends at the approval moment (Executor: "${await p.evalJs(word('executor'))}")`);
  check(await p.evalJs(`${word('router')} === 'In scope' && document.querySelectorAll('#team-log li').length >= 5`), `${label}: Router "${await p.evalJs(word('router'))}", team log ${await p.evalJs(`document.querySelectorAll('#team-log li').length`)} lines`);
  check(await p.evalJs(`document.querySelector('#speech .money')?.textContent === '$26.00' && !!document.querySelector('#crew [data-agent="executor"][data-money]')`), `${label}: Executor holds $26.00 in amber for approval`);
  await p.evalJs(`document.getElementById('see-it').click()`);
  check(await p.evalJs(`document.getElementById('drawer').open && document.activeElement.id.startsWith('mail-') && document.getElementById('tab-inbox').getAttribute('aria-selected') === 'true'`), `${label}: "See it" opens the drawer on Inbox and focuses ${await p.evalJs('document.activeElement.id')}`);
  check(await p.evalJs(`!document.querySelector('#inbox-list img, #inbox-list script')`), `${label}: inbox renders no HTML from email bodies`);
  if (label === 'fixtures') check(await p.evalJs(`[...document.querySelectorAll('.mail-body')].some((b) => b.textContent.includes('<img src=x onerror=alert(1)>'))`), `${label}: hostile <img onerror> shows as text`);
  await p.evalJs(`document.getElementById('drawer-close').click()`);
  check(await p.evalJs(`!document.getElementById('drawer').open`), `${label}: Close shuts the drawer`);
  const refund = `document.querySelector('.step[data-tool="refund_order"] [data-approve]')`;
  check(await p.evalJs(`!!${refund} && !${refund}.checked`), `${label}: refund starts unchecked`);
  check(await p.evalJs(`/cannot be undone/.test(document.querySelector('.step[data-tool="refund_order"]').textContent) && !!document.querySelector('.step[data-tool="refund_order"] .pill--irreversible')`), `${label}: refund says "cannot be undone" + Irreversible pill`);
  check(await p.evalJs(`!document.getElementById('review-btn').hidden && document.getElementById('review-btn').textContent === 'Review the $26.00 refund'`), `${label}: run bar offers "${await p.evalJs(`document.getElementById('review-btn').textContent`)}"`);
  await p.evalJs(`document.getElementById('review-btn').click()`);
  check(await p.evalJs(`document.activeElement === ${refund}`), `${label}: Review focuses the refund checkbox`);
  check(await p.evalJs(`(() => { const b = document.querySelector('.step:not(.step--approval) [data-approve]'); return !b || getComputedStyle(b).accentColor !== 'auto'; })()`), `${label}: plain checkboxes use the ink accent, not the browser blue`);
  await p.evalJs(`${refund}.click()`);
  check(await p.evalJs(`document.getElementById('money-out').textContent !== '$0.00'`), `${label}: money out = ${await p.evalJs(`document.getElementById('money-out').textContent`)}`);
  check(await p.evalJs(`document.getElementById('review-btn').hidden`), `${label}: nothing waits, so the Review button hides`);
  const before = await p.evalJs(`window.__api.length`);
  await p.evalJs(`document.getElementById('run-btn').click()`);
  await p.waitFor(`!document.getElementById('runlog').hidden && !document.querySelector('#stream [data-state="running"], #stream [data-state="pending"]')`, 60000);
  const rows = await p.evalJs(`[...document.querySelectorAll('#stream .run-row')].map((r) => r.dataset.state + ': ' + r.textContent.trim().replace(/\\s+/g, ' ').slice(0, 110))`);
  rows.forEach((r) => console.log(`     run-log ${r}`));
  check(rows.length > 0 && rows.some((r) => r.startsWith('done')), `${label}: run log filled`);
  await p.waitFor(`window.__api.slice(${before}).some((c) => /(api|fixtures)[/]audit/.test(c.path))`, 10000);
  check(await p.evalJs(`window.__api.slice(${before}).some((c) => /(api|fixtures)[/]audit/.test(c.path) && c.status === 200)`), `${label}: audit refetched after the run`);
  check(await p.waitFor(`${word('executor')} === 'All done'`, 5000), `${label}: Executor shows "All done" after the run`);
  const inView = `(() => { const r = document.getElementById('stage').getBoundingClientRect(); return r.top >= document.querySelector('.site-header').getBoundingClientRect().bottom - 1 && r.bottom <= innerHeight; })()`;
  check(await p.waitFor(inView, 5000), `${label}: Run brought the team into view (stage top ${await p.evalJs(`Math.round(document.getElementById('stage').getBoundingClientRect().top)`)} px)`);
  await p.evalJs(`scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })`);
  check(await p.waitFor(`document.getElementById('strip').hasAttribute('data-on')`, 4000), `${label}: scrolled away while the team cheers, the mini team strip shows under the header`);
  check(await p.evalJs(`document.getElementById('run-bar').hasAttribute('data-done') && document.getElementById('run-btn').hidden && !document.getElementById('audit-btn').hidden && getComputedStyle(document.getElementById('run-bar')).position === 'static'`),
    `${label}: run bar now reads "${await p.evalJs(`[document.getElementById('out-label').textContent, document.getElementById('money-out').textContent, document.getElementById('money-note').textContent].join(' ')`)}" with Open audit, no longer floating`);
  if (label === 'fixtures') check(await p.evalJs(`document.getElementById('money-note').textContent === '(Stripe mock)' && document.getElementById('stripe-tag').textContent === 'Stripe mock'`), `${label}: the bar says Stripe mock, like the [MOCK] receipt`);
  await p.evalJs(`document.querySelector('[data-open="audit"]').click()`);
  check(await p.evalJs(`document.getElementById('drawer').open && document.getElementById('tab-audit').getAttribute('aria-selected') === 'true'`), `${label}: Audit button opens the drawer on Audit`);
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
  console.log(`== proposed agent trace: ${BASE}/app/?fixtures=trace`);
  const t = await openPage(`${BASE}/app/?fixtures=trace`);
  await t.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`);
  await t.evalJs(clickText('Sunday cleanup'));
  await t.evalJs(`document.getElementById('plan-btn').click()`);
  check(await t.waitFor(`${state} === 'ready' && !document.querySelector('#steps [data-enter]') && ${word('executor')} === 'Waiting for you'`, 25000), 'trace: replay reaches the approval moment');
  const src = await t.evalJs(`document.getElementById('team-log-src').textContent`);
  check(src.startsWith('From the agent trace'), `trace: team log source says "${src}"`);
  check(await t.evalJs(`[...document.querySelectorAll('#team-log li')].some((l) => l.textContent.includes('Rejected: tracking email before the order is shipped.'))`), 'trace: in-loop validator rejection is in the team log');
  await report(t, 'trace');
  await t.close();
  // The backend may send up to 60 events (spec 09); the UI keeps 40: the first 37 and the last 3.
  const t2 = await openPage(`${BASE}/app/?fixtures=trace`);
  await t2.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`);
  await t2.evalJs(`(() => { const f = window.fetch; window.fetch = async (input, init) => { const res = await f(input, init); const url = typeof input === 'string' ? input : input.url;
    if (!url.includes('/fixtures/plan-trace.json')) return res; const j = await res.json(); const t = j.trace;
    j.trace = [...t.slice(0, 6), ...Array.from({ length: 29 }, (_, i) => ({ agent: 'planner', event: 'read', detail: 'Extra read ' + i + '.', t_ms: t[5].t_ms, step_id: null })), ...t.slice(6)];
    return new Response(JSON.stringify(j), { status: 200, headers: { 'content-type': 'application/json' } }); }; })()`);
  await t2.evalJs(clickText('Sunday cleanup'));
  await t2.evalJs(`document.getElementById('plan-btn').click()`);
  // Executor says "Waiting for you" as soon as the money box renders, so wait for the Judge's own line instead.
  check(await t2.waitFor(`document.getElementById('team-log-src').textContent.includes('40 events') && [...document.querySelectorAll('#team-log li')].some((l) => l.textContent.includes('Pass. It covers the request'))`, 40000),
    `trace: a 50-event trace keeps 40 and still ends on the Judge's verdict ("${await t2.evalJs(`document.getElementById('team-log-src').textContent`)}")`);
  await report(t2, 'trace-50');
  await t2.close();
  console.log(`== validator tally: ${BASE}/app/?fixtures=invalid with the blocked step moved to position 2`);
  const v = await openPage(`${BASE}/app/?fixtures=invalid`);
  await v.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`);
  await v.evalJs(`(() => { const f = window.fetch; window.fetch = async (input, init) => { const res = await f(input, init); const url = typeof input === 'string' ? input : input.url;
    if (!url.includes('/fixtures/plan-invalid.json')) return res; const j = await res.json(); const s = j.plan.steps; s.splice(1, 0, s.splice(s.findIndex((x) => !j.validations.find((y) => y.step_id === x.id).ok), 1)[0]);
    return new Response(JSON.stringify(j), { status: 200, headers: { 'content-type': 'application/json' } }); }; })()`);
  await v.evalJs(clickText('Sunday cleanup'));
  await v.evalJs(`document.getElementById('plan-btn').click()`);
  check(await v.waitFor(`${state} === 'ready' && ${word('executor')} === 'Waiting for you'`, 25000), 'invalid: replay reaches the approval moment');
  const val = await v.evalJs(`(() => { const li = document.querySelector('#crew [data-agent="validator"]'); return { word: li.querySelector('[data-word]').textContent, flag: li.dataset.flag, second: document.querySelectorAll('#steps .step')[1].classList.contains('step--invalid') }; })()`);
  check(val.second && val.word === '1 of 5 blocked' && val.flag === 'blocked', `invalid: Validator ends on the plan's count, not the last step's ("${val.word}", flag ${val.flag}, step 2 blocked: ${val.second})`);
  await report(v, 'invalid');
  await v.close();
  for (const [w, h] of [[390, 844], [768, 1024]]) {
    console.log(`== narrow: ${BASE}/app/?fixtures=happy at ${w} px`);
    const ph = await openPage(`${BASE}/app/?fixtures=happy`, w, h);
    await ph.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`);
    await sleep(3000); // past boot and the idle callback that would load the 3D on a wide stage
    const phone = await ph.evalJs(`({ mode: document.getElementById('stage').dataset.mode, canvas: !!document.querySelector('.stage-canvas'),
      chunks: performance.getEntriesByType('resource').filter((e) => /stage3d/.test(e.name)).length,
      rows: new Set([...document.querySelectorAll('#crew .portrait')].map((p) => Math.round(p.getBoundingClientRect().top))).size })`);
    check(phone.mode === '2d' && !phone.canvas && !phone.chunks && phone.rows === 2, `${w}: stage under 800 px keeps the 2D portraits in 4 + 3, 3D chunk never fetched (${JSON.stringify(phone)})`);
    await report(ph, `${w}`);
    await ph.close();
  }
  // Keyboard only: Tab from the top of /app/ to a chip, Plan it, the refund checkbox and Run, each with a visible ring.
  console.log(`== keyboard: ${BASE}/app/?fixtures=happy, Tab, Enter and Space only`);
  const k = await openPage(`${BASE}/app/?fixtures=happy`);
  await k.waitFor(`document.getElementById('store-name').textContent !== 'Loading store'`);
  const here = `(() => { const a = document.activeElement; if (!a || a === document.body) return { name: 'body', ring: false };
    const cs = getComputedStyle(a), r = a.getBoundingClientRect();
    const name = a.id ? '#' + a.id : a.matches('[data-approve]') ? 'approve:' + a.closest('.step').dataset.tool : a.tagName.toLowerCase() + ':' + (a.textContent || '').trim().slice(0, 20);
    return { name, ring: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2, seen: r.width > 0 && r.height > 0 }; })()`;
  const path = [];
  const tabTo = async (pred, max = 60) => {
    for (let i = 1; i <= max; i++) {
      await k.key('Tab');
      const h = await k.evalJs(here); path.push(h);
      if (await k.evalJs(pred)) return i;
    }
    return 0;
  };
  const first = (await tabTo('true', 1), path[0]);
  check(first.name.startsWith('a:Skip'), `keyboard: first Tab is the skip link (${first.name})`);
  const toChip = await tabTo(`document.activeElement.textContent.trim() === 'Sunday cleanup'`);
  await k.key('Enter');
  check(toChip > 0 && await k.evalJs(`document.getElementById('request-input').value.startsWith('Ship yesterday')`), `keyboard: ${toChip} more Tabs reach the "Sunday cleanup" chip, Enter fills the request`);
  const toPlan = await tabTo(`document.activeElement.id === 'plan-btn'`);
  await k.key('Enter');
  check(toPlan > 0 && await k.waitFor(`${state} === 'ready' && !document.querySelector('#steps [data-enter]') && ${word('executor')} === 'Waiting for you'`, 25000), `keyboard: ${toPlan} Tabs to Plan it, Enter plans (focus now ${await k.evalJs(`'#' + document.activeElement.id`)})`);
  const toApprove = await tabTo(`document.activeElement.matches('.step[data-tool="refund_order"] [data-approve]')`);
  await k.key('Space');
  check(toApprove > 0 && await k.evalJs(`document.activeElement.checked && document.getElementById('money-out').textContent === '$26.00'`), `keyboard: ${toApprove} Tabs from the plan to the refund checkbox, Space approves $26.00`);
  const toRun = await tabTo(`document.activeElement.id === 'run-btn'`);
  await k.key('Enter');
  check(toRun > 0 && await k.waitFor(`!document.getElementById('runlog').hidden && !document.querySelector('#stream [data-state="running"], #stream [data-state="pending"]')`, 30000), `keyboard: ${toRun} Tabs to Run approved steps, Enter runs`);
  const noRing = path.filter((h) => h.name !== 'body' && (!h.ring || !h.seen)).map((h) => h.name);
  check(!noRing.length, `keyboard: ${path.length} focus stops, every one visible with a 2 px ring${noRing.length ? '; missing on ' + [...new Set(noRing)].join(', ') : ''}`);
  console.log(`     tab order: ${path.map((h) => h.name).join(' > ')}`);
  await report(k, 'keyboard');
  await k.close();
} else {
  const scenarios = ['happy', 'invalid', 'clarify', 'ratelimit', 'llmdown', 'fail', 'slow', 'empty', 'mock', 'trace'];
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
    if (sc !== 'slow') await p.waitFor(`!document.querySelector('#steps [data-enter]')`, 15000);
    const sel = sc === 'mock' ? 'main' : sc === 'fail' || sc === 'trace' ? '.console-page' : '#plan';
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
    check(!errs.length, `fixtures=${sc}: state=${st}${errs.length ? ' errors: ' + errs.join(' | ') : ''} -> review/${process.env.SHOTS_DIR || 'final'}/console-fx-${sc}.png`);
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
