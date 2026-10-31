// Landing hero: replays the recorded /api/plan response and builds the plan
// row by row (createElement + textContent only; CSP-safe).
import { money, setPill, runRows, sleep, beat } from './run';

type Fixture = {
  plan: { steps: { id: string; tool: string; title: string }[]; blocked_inputs: unknown[] };
  validations: { step_id: string; ok: boolean }[];
  diff: { step_id: string; before: string; after: string; amount_cents: number | null }[];
  tools: Record<string, { moves_money: boolean }>;
};

const FIXTURE = '/v2/fixtures/plan.json';
const PLANNING_MS = 600;
const STAGGER_MS = 200;

const root = document.querySelector<HTMLElement>('[data-demo]');
if (root) init(root);

function h(tag: string, cls = '', text?: string) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

function arrow() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('class', 'icon diff-arrow');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', 'M2.5 8h11M9.5 4l4 4-4 4');
  svg.append(path);
  return svg;
}

async function load(): Promise<Fixture> {
  const res = await fetch(FIXTURE, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`plan fixture: HTTP ${res.status}`);
  const data = await res.json();
  if (!Array.isArray(data?.plan?.steps) || !Array.isArray(data?.diff)) throw new Error('plan fixture: bad shape');
  return data as Fixture;
}

function init(root: HTMLElement) {
  const q = <T extends HTMLElement>(sel: string) => root.querySelector<T>(sel)!;
  const form = q<HTMLFormElement>('[data-ask]');
  const input = q<HTMLTextAreaElement>('textarea');
  const planBtn = q<HTMLButtonElement>('[data-plan]');
  const list = q('[data-steps]');
  const meta = q('[data-meta]');
  const empty = q('[data-empty]');
  const emptyMsg = q('[data-empty-msg]');
  const notice = q('[data-notice]');
  const approveBox = q('[data-approve-box]');
  const approve = q<HTMLInputElement>('[data-approve]');
  const foot = q('[data-foot]');
  const out = q('[data-out]');
  const outNote = q('[data-out-note]');
  const runBtn = q<HTMLButtonElement>('[data-run]');
  const done = q('[data-done]');
  const doneMsg = q('[data-done-msg]');
  const error = q('[data-error]');
  const status = q('[data-status]');
  const idleMsg = emptyMsg.textContent ?? '';

  let pendingCents = 0;
  let busy = false;

  const say = (msg: string) => { status.textContent = msg; };
  const show = (el: HTMLElement) => { el.hidden = false; el.classList.add('is-new'); };
  const updateOut = () => {
    out.textContent = money(approve.checked ? pendingCents : 0);
    outNote.textContent = approve.checked
      ? 'Stripe test mode. Card refunds cannot be undone.'
      : `Stripe test mode. ${money(pendingCents)} waits for your approval.`;
  };

  function reset() {
    list.replaceChildren();
    for (const el of [meta, notice, approveBox, foot, done, error]) { el.hidden = true; el.classList.remove('is-new'); }
    empty.hidden = false;
    emptyMsg.textContent = idleMsg;
    approve.checked = false;
    approve.disabled = false;
    runBtn.disabled = false;
    pendingCents = 0;
    root.dataset.state = 'idle';
  }

  function row(step: Fixture['plan']['steps'][number], n: number, data: Fixture) {
    const diff = data.diff.find((d) => d.step_id === step.id);
    const ok = data.validations.find((v) => v.step_id === step.id)?.ok ?? false;
    const moves = Boolean(data.tools[step.tool]?.moves_money);

    const li = h('li', 'step step--compact is-new');
    li.dataset.step = step.id;
    if (moves) li.dataset.money = String(diff?.amount_cents ?? 0);
    const num = h('span', 'step-n', String(n));
    num.setAttribute('aria-hidden', 'true');

    const top = h('div', 'step-top');
    top.append(h('p', 'step-title', step.title));
    if (diff?.amount_cents != null) {
      const m = h('p', 'step-money');
      m.append(h('span', 'num', money(diff.amount_cents)), moves ? '' : ' est.');
      top.append(m);
      if (moves) pendingCents += diff.amount_cents;
    }
    const pill = h('span', '', '');
    pill.dataset.pill = '';
    top.append(pill);
    setPill(top, moves ? 'approval' : ok ? 'checked' : 'blocked', moves ? 'Needs approval' : ok ? 'Checked' : 'Blocked');

    const metaLine = h('p', 'step-meta');
    const d = h('span', 'diff');
    d.append(h('span', '', diff?.before ?? ''), arrow(), h('span', '', diff?.after ?? ''));
    metaLine.append(h('code', 'tool', step.tool), d);

    const body = h('div', 'step-body');
    body.append(top, metaLine);
    li.append(num, body);
    return li;
  }

  async function plan() {
    if (busy) return;
    busy = true;
    reset();
    root.dataset.state = 'planning';
    planBtn.disabled = true;
    emptyMsg.textContent = 'Planning';
    say('Planning');
    try {
      const [data] = await Promise.all([load(), sleep(PLANNING_MS)]);
      empty.hidden = true;
      root.dataset.state = 'ready';
      const steps = data.plan.steps;
      const gated = steps.filter((s) => data.tools[s.tool]?.moves_money).length;
      meta.textContent = `${steps.length} steps, ${gated} needs your approval`;
      show(meta);
      for (const [i, s] of steps.entries()) {
        list.append(row(s, i + 1, data));
        await beat(STAGGER_MS);
      }
      if (data.plan.blocked_inputs.length) { show(notice); await beat(STAGGER_MS); }
      show(approveBox);
      await beat(STAGGER_MS);
      updateOut();
      show(foot);
      say(`Plan ready: ${steps.length} steps, ${gated} needs your approval. Nothing has run yet.`);
    } catch (err) {
      console.error(err);
      empty.hidden = true;
      root.dataset.state = 'error';
      show(error);
      say('Could not load the recorded plan.');
    } finally {
      planBtn.disabled = false;
      busy = false;
    }
  }

  async function run() {
    if (busy) return;
    busy = true;
    root.dataset.state = 'running';
    runBtn.disabled = true;
    approve.disabled = true;
    planBtn.disabled = true;
    const rows = [...list.querySelectorAll<HTMLElement>('.step')];
    await runRows(rows, (r) => !r.dataset.money || approve.checked, say);
    foot.hidden = true;
    show(done);
    root.dataset.state = 'done';
    doneMsg.focus({ preventScroll: true });
    say('Done. Every step is in the audit log.');
    planBtn.disabled = false;
    busy = false;
  }

  form.addEventListener('submit', (e) => { e.preventDefault(); if (input.value.trim()) plan(); else input.focus(); });
  root.querySelectorAll<HTMLButtonElement>('[data-prompt]').forEach((chip) =>
    chip.addEventListener('click', () => { input.value = chip.dataset.prompt ?? ''; plan(); }));
  approve.addEventListener('change', updateOut);
  runBtn.addEventListener('click', run);
  q('[data-reset]').addEventListener('click', () => { reset(); planBtn.focus(); say('Demo reset.'); });
  q('[data-retry]').addEventListener('click', plan);

  // "Try the live demo" links land on the panel; put focus on its first action.
  document.querySelectorAll<HTMLAnchorElement>('a[href="#demo"]').forEach((a) =>
    a.addEventListener('click', () => requestAnimationFrame(() => planBtn.focus({ preventScroll: true }))));

  root.classList.add('js');
  // Build the recorded plan once on load, so the first screen always shows the $ gate.
  // Chips and "Plan it" rebuild it; Reset clears it.
  plan();
}
