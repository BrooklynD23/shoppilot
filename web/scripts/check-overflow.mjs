// Horizontal-scroll check: compares documentElement.scrollWidth to clientWidth
// at several widths, via headless Chrome + the DevTools protocol (no deps).
// Usage: node scripts/check-overflow.mjs http://127.0.0.1:4321/v2/1/ [more urls...]
// Exit 1 if any page overflows. Lists the widest offending elements.
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import os from 'node:os';

const CHROME = process.env.CHROME || `${os.homedir()}/.local/bin/google-chrome`;
const WIDTHS = (process.env.WIDTHS || '390,1440,1920').split(',').map(Number);
const urls = process.argv.slice(2);
if (!urls.length) { console.error('usage: check-overflow.mjs <url>...'); process.exit(2); }

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
  const d = document.documentElement, cw = d.clientWidth;
  const bad = [...document.querySelectorAll('body *')].filter((el) => el.getBoundingClientRect().right > cw + 1)
    .map((el) => ({ el: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : ''), right: Math.round(el.getBoundingClientRect().right) }))
    .sort((a, b) => b.right - a.right).slice(0, 5);
  return JSON.stringify({ sw: d.scrollWidth, cw, bad });
})()`;

let failed = 0;
for (const url of urls) {
  for (const w of WIDTHS) {
    const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
    const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Page.enable', {}, sessionId);
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 600 }, sessionId);
    const loaded = once((m) => m.method === 'Page.loadEventFired' && m.sessionId === sessionId);
    await send('Page.navigate', { url }, sessionId);
    await loaded; await sleep(400);
    const r = await send('Runtime.evaluate', { expression: probe, returnByValue: true }, sessionId);
    const { sw, cw, bad } = JSON.parse(r.result.result.value);
    const ok = sw <= cw;
    if (!ok) failed++;
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${w}px scrollWidth=${sw} clientWidth=${cw} ${url}${ok ? '' : '\n     ' + bad.map((b) => `${b.el} right=${b.right}`).join('\n     ')}`);
    await send('Target.closeTarget', { targetId });
  }
}
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
