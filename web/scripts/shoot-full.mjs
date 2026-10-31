// Full-page screenshots via headless Chrome + DevTools protocol (no deps).
// Usage: OUT=dir node scripts/shoot-full.mjs name=url [name=url ...]  -> dir/<name>-<width>.png
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import os from 'node:os';
import { writeFileSync } from 'node:fs';

const CHROME = process.env.CHROME || `${os.homedir()}/.local/bin/google-chrome`;
const WIDTHS = (process.env.WIDTHS || '1440,390').split(',').map(Number);
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

for (const [name, url] of jobs) {
  for (const w of WIDTHS) {
    const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
    const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Page.enable', {}, sessionId);
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: w < 600 ? 844 : 900, deviceScaleFactor: 1, mobile: w < 600 }, sessionId);
    if (process.env.REDUCED) await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] }, sessionId);
    const loaded = once((m) => m.method === 'Page.loadEventFired' && m.sessionId === sessionId);
    await send('Page.navigate', { url }, sessionId);
    await loaded; await sleep(Number(process.env.WAIT || 3500));
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }, sessionId);
    const file = `${OUT}/${name}-${w}.png`;
    writeFileSync(file, Buffer.from(shot.result.data, 'base64'));
    console.log('wrote', file);
    await send('Target.closeTarget', { targetId });
  }
}
ws.close(); chrome.kill();
