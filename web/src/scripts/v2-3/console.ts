// Console behaviour for /v2/3/app/ (replay demo, no network).
// CSP-safe: textContent + createElement only.
import { plan } from '../../data/demo';
import { safety } from '../../data/v2';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const input = $<HTMLTextAreaElement>('request-input');
const msg = $('request-msg');
const runBtn = $<HTMLButtonElement>('run-btn');
const resetBtn = $<HTMLButtonElement>('reset-btn');
const boxes = () => [...document.querySelectorAll<HTMLInputElement>('input[name="approve"]')];

const el = (tag: string, cls: string, text = '') => {
  const n = document.createElement(tag);
  n.className = cls;
  n.textContent = text;
  return n;
};

// Request box: chips fill the textarea; "Plan it" shows the recorded plan honestly.
document.querySelectorAll<HTMLButtonElement>('.chip').forEach((b) =>
  b.addEventListener('click', () => { input.value = b.dataset.prompt ?? ''; input.focus(); }),
);
$('request-form').addEventListener('submit', (ev) => {
  ev.preventDefault();
  if (!input.value.trim()) { msg.textContent = 'Type a request first, or pick one of the suggestions.'; input.focus(); return; }
  msg.textContent = 'This demo replays a recorded plan. It is shown below.';
  $('plan-h').focus();
});
input.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) $<HTMLFormElement>('request-form').requestSubmit();
});

// Tabs (Inbox / Outbox / Audit).
const tabs = [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
const selectTab = (t: HTMLButtonElement) => {
  tabs.forEach((x) => {
    const on = x === t;
    x.setAttribute('aria-selected', String(on));
    x.tabIndex = on ? 0 : -1;
    $(x.getAttribute('aria-controls') ?? '').hidden = !on;
  });
};
tabs.forEach((t, i) => {
  t.addEventListener('click', () => selectTab(t));
  t.addEventListener('keydown', (ev) => {
    const d = ev.key === 'ArrowRight' ? 1 : ev.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    const next = tabs[(i + d + tabs.length) % tabs.length];
    selectTab(next); next.focus();
  });
});
document.querySelector('.blocked-note a')?.addEventListener('click', () => selectTab(tabs[0]));

// Run: one pass over the plan, guarded against double submit.
runBtn.addEventListener('click', () => {
  runBtn.disabled = true;
  runBtn.textContent = 'Ran approved steps';
  const approved = new Set(boxes().filter((b) => b.checked).map((b) => b.value));
  boxes().forEach((b) => { b.disabled = true; });
  const log = $('runlog');
  $('log-empty').hidden = true;
  const audit = $('audit-list');
  for (const s of plan.steps) {
    const ran = approved.has(s.id);
    const receipt = safety.auditReceipt.find((r) => r.tool === s.tool);
    const li = document.createElement('li');
    li.append(el('span', 'step-n', String(s.n)), el('span', 'runlog-title', s.title));
    li.append(ran && receipt ? el('span', 'id', receipt.id) : el('span', 'runlog-note', ran ? 'read only' : 'not approved'));
    li.append(el('span', `pill pill-${ran ? 'done' : 'undone'}`, ran ? 'Done' : 'Skipped'));
    log.append(li);
    if (ran && receipt) {
      const row = el('li', 'rail-row');
      row.append(el('span', 'tool', receipt.tool), el('span', '', receipt.summary), el('span', 'id', receipt.id));
      row.append(el('span', receipt.undo ? 'rail-undo' : 'pill pill-irreversible', receipt.undo ? 'Undo available' : 'Irreversible, no undo'));
      audit.prepend(row);
    }
  }
  if (audit.childElementCount) $('audit-empty').hidden = true;
  if (approved.has('s2')) {
    $('outbox-empty').hidden = true;
    $('outbox-list').append(el('li', 'rail-row', '3 tracking emails for orders 1041, 1042, 1043. Saved here, never sent.'));
  }
  log.append(el('li', 'runlog-end', 'Done. Every step logged.'));
});

// Reset: two clicks within 4 s, then reload the seeded state.
let armed = 0;
resetBtn.addEventListener('click', () => {
  if (armed) { window.location.reload(); return; }
  resetBtn.textContent = 'Click again to reset';
  armed = window.setTimeout(() => { armed = 0; resetBtn.textContent = 'Reset demo store'; }, 4000);
});
