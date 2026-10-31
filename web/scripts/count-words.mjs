// Landing word count via headless Chrome + CDP (rendered text, after JS).
// Copy words = all visible text in <body> minus [data-ui] product fragments, #pricing, #faq and [aria-hidden=true].
// Usage: node scripts/count-words.mjs name=url ...
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import os from 'node:os';
import { writeFileSync } from 'node:fs';

const CHROME = process.env.CHROME || `${os.homedir()}/.local/bin/google-chrome`;
const WIDTHS = [1440];
const jobs = process.argv.slice(2).map((a) => a.split(/=(.*)/s).slice(0, 2));
const OUT = process.env.OUT || '.';
if (!jobs.length) { console.error('usage: shoot-full.mjs name=url...'); process.exit(2); }

const port = 9300 + Math.floor(Math.random() * 600);
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${os.tmpdir()}/ovf-${port}`, 'about:blank'], { stdio: 'ignore' });

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

const probe = `(() => {
  const words = (el) => (el.innerText || '').split(/\\s+/).filter((w) => /[A-Za-z0-9$]/.test(w)).length;
  const total = words(document.body);
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll('[data-ui], #pricing, #faq, [aria-hidden="true"], script, style, .sr-only, .visually-hidden').forEach((n) => n.remove());
  const host = document.createElement('div'); host.style.cssText = 'position:absolute;left:-99999px;width:1440px';
  host.appendChild(clone); document.documentElement.appendChild(host);
  const copy = words(clone); host.remove();
  const h1 = document.querySelector('h1'); const sub = document.querySelector('[data-hero-sub]');
  return JSON.stringify({ copy, total, h1: h1 ? words(h1) : 0, sub: sub ? words(sub) : null });
})()`;
for (const [name, url] of jobs) {
  const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
  const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
  await send('Page.enable', {}, sessionId);
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false }, sessionId);
  const loaded = once((m) => m.method === 'Page.loadEventFired' && m.sessionId === sessionId);
  await send('Page.navigate', { url }, sessionId);
  await loaded; await sleep(1500);
  const r = await send('Runtime.evaluate', { expression: probe, returnByValue: true }, sessionId);
  const v = JSON.parse(r.result.result.value);
  console.log(`${name}: copy=${v.copy} (budget 180) total_incl_ui_pricing_faq=${v.total} h1=${v.h1} (<=8) sub=${v.sub ?? 'no [data-hero-sub]'} (<=16) ${v.copy <= 180 ? 'OK' : 'OVER'}`);
  await send('Target.closeTarget', { targetId });
}
ws.close(); chrome.kill();
