// Console: replayed plan, live money-out, run loop, tabs, two-step reset.
import { money, setPill, runRows, sleep, type PillKind } from './run';

const root = document.querySelector<HTMLElement>('[data-console]');
if (root) init(root);

function init(root: HTMLElement) {
  const q = <T extends HTMLElement>(sel: string) => root.querySelector<T>(sel)!;
  const form = q<HTMLFormElement>('[data-ask]');
  const input = q<HTMLTextAreaElement>('textarea');
  const planBtn = q<HTMLButtonElement>('[data-plan]');
  const planEl = q('[data-plan-area]');
  const planHeading = q('#plan-heading');
  const rows = [...root.querySelectorAll<HTMLElement>('.step')];
  const boxes = rows.map((r) => r.querySelector<HTMLInputElement>('[data-approve]')!);
  const out = q('[data-out]');
  const outNote = q('[data-out-note]');
  const runBtn = q<HTMLButtonElement>('[data-run]');
  const status = q('[data-status]');
  const resetBtn = document.querySelector<HTMLButtonElement>('[data-reset]')!; // lives in the header
  const initial = rows.map((r) => {
    const p = r.querySelector('[data-pill]')!;
    return { kind: p.className.replace(/.*pill--/, '') as PillKind, text: p.textContent ?? '' };
  });
  const initialChecked = boxes.map((b) => b.checked);

  const say = (msg: string) => { status.textContent = msg; };
  const updateOut = () => {
    const cents = rows.reduce((t, r, i) => t + (boxes[i].checked ? Number(r.dataset.money ?? 0) : 0), 0);
    out.textContent = money(cents);
    const waiting = rows.reduce((t, r, i) => t + (boxes[i].checked ? 0 : Number(r.dataset.money ?? 0)), 0);
    outNote.textContent = waiting
      ? `Stripe test mode. ${money(waiting)} refund needs your approval.`
      : 'Stripe test mode. Card refunds cannot be undone.';
  };

  function restore() {
    rows.forEach((r, i) => { setPill(r, initial[i].kind, initial[i].text); delete r.dataset.run; });
    boxes.forEach((b, i) => { b.checked = initialChecked[i]; b.disabled = false; });
    root.querySelectorAll<HTMLElement>('[data-after-run]').forEach((el) => { el.hidden = true; });
    root.querySelectorAll<HTMLElement>('[data-before-run]').forEach((el) => { el.hidden = false; });
    runBtn.disabled = false;
    updateOut();
  }

  async function plan() {
    restore();
    planEl.dataset.state = 'loading';
    planBtn.disabled = true;
    say('Planning');
    await sleep(600);
    planEl.dataset.state = 'ready';
    planBtn.disabled = false;
    planHeading.focus();
    say('Plan ready: 5 steps, 1 needs your approval. Recorded plan (replay).');
  }

  async function run() {
    runBtn.disabled = true;
    planBtn.disabled = true;
    boxes.forEach((b) => { b.disabled = true; });
    await runRows(rows, (r) => boxes[rows.indexOf(r)].checked, say);
    // Reveal the receipts and outbox items for the steps that ran.
    const ran = new Set(rows.filter((r) => r.dataset.run === 'done').map((r) => r.dataset.tool));
    root.querySelectorAll<HTMLElement>('[data-after-run]').forEach((el) => {
      el.hidden = Boolean(el.dataset.tool) && !ran.has(el.dataset.tool);
    });
    root.querySelectorAll<HTMLElement>('[data-before-run]').forEach((el) => { el.hidden = true; });
    planBtn.disabled = false;
    say('Done. Every step is in the audit log.');
  }

  form.addEventListener('submit', (e) => { e.preventDefault(); if (input.value.trim()) plan(); else input.focus(); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) form.requestSubmit(); });
  root.querySelectorAll<HTMLButtonElement>('[data-prompt]').forEach((chip) =>
    chip.addEventListener('click', () => { input.value = chip.dataset.prompt ?? ''; form.requestSubmit(); }));
  boxes.forEach((b) => b.addEventListener('change', updateOut));
  runBtn.addEventListener('click', run);

  // Two-step reset: no native confirm(); the label asks once more for 4 s.
  let armed: number | undefined;
  const resetLabel = resetBtn.textContent;
  resetBtn.addEventListener('click', () => {
    if (armed) { window.location.reload(); return; }
    resetBtn.textContent = 'Click again to reset';
    resetBtn.dataset.armed = '';
    armed = window.setTimeout(() => { armed = undefined; resetBtn.textContent = resetLabel; delete resetBtn.dataset.armed; }, 4000);
  });

  // Tabs: click or arrow keys; one panel visible.
  const tabs = [...root.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  const select = (tab: HTMLButtonElement) => tabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute('aria-controls')!)!.hidden = !on;
  });
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => select(t));
    t.addEventListener('keydown', (e) => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      const next = tabs[(i + step + tabs.length) % tabs.length];
      select(next);
      next.focus();
    });
  });
  // "See it" on the blocked notice: make sure Inbox is showing.
  q('[data-see-inbox]').addEventListener('click', () => select(tabs[0]));

  // Arriving from the landing form (?q=...): prefill the request.
  const asked = new URLSearchParams(window.location.search).get('q');
  if (asked) input.value = asked.slice(0, 500);
  updateOut();
}
