// Console behaviour for approach 1. Replay only: no network calls.
// Renders with textContent/createElement (CSP: no innerHTML).
import { pills, safety } from '../../data/v2';
import { copy, money } from '../../data/demo';

type PillKey = keyof typeof pills;
const q = <T extends Element>(sel: string, root: ParentNode = document) => root.querySelector<T>(sel)!;
const qa = <T extends Element>(sel: string, root: ParentNode = document) => [...root.querySelectorAll<T>(sel)];
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

const form = q<HTMLFormElement>('#request-form');
const input = q<HTMLTextAreaElement>('#request-input');
const status = q<HTMLElement>('#request-status');
const heading = q<HTMLElement>('#plan-heading');
const boxes = qa<HTMLInputElement>('#plan input[name="approved"]');
const runBtn = q<HTMLButtonElement>('#run-btn');
const stream = q<HTMLOListElement>('#stream');

function setPill(stepId: string, state: PillKey) {
  const el = q<HTMLElement>(`[data-step="${stepId}"] [data-pill-slot] .pill`);
  el.className = `pill pill--${state}`;
  el.dataset.state = state;
  el.textContent = pills[state];
}

// Request box: chips fill the textarea; "Plan it" shows the recorded plan.
qa<HTMLButtonElement>('[data-prompt]').forEach((b) =>
  b.addEventListener('click', () => { input.value = b.dataset.prompt ?? ''; input.focus(); }));

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value.trim();
  input.setAttribute('aria-invalid', String(!text));
  if (!text) { status.textContent = 'Type a request first, or pick an example below.'; input.focus(); return; }
  status.textContent = text === copy.request
    ? 'Recorded plan (replay) for this request is below.'
    : 'This demo replays one recorded plan, the Sunday cleanup. It is shown below.';
  heading.focus();
});
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) form.requestSubmit();
});

// Money out follows the approve boxes, so the bar never shows money that will not move.
function updateMoney() {
  const cents = boxes.filter((b) => b.checked && b.dataset.money).reduce((t, b) => t + Number(b.dataset.money), 0);
  q('#money-out-amt').textContent = money(cents);
  q('#money-hint').textContent = cents
    ? 'Includes the refund on order 1038. Card refunds cannot be undone.'
    : 'Tick step 5 to add the $24.00 refund. Card refunds cannot be undone.';
  setPill('s5', q<HTMLInputElement>('input[value="s5"]').checked ? 'checked' : 'approval');
}
boxes.forEach((b) => b.addEventListener('change', updateMoney));

function logLine(text: string, state: 'done' | 'skipped') {
  const li = document.createElement('li');
  li.className = `runlog__row runlog__row--${state}`;
  li.textContent = text;
  stream.append(li);
}

// Run: approved steps run in order (replay), skipped ones say why. Each run writes a receipt.
runBtn.addEventListener('click', async () => {
  runBtn.disabled = true;
  boxes.forEach((b) => { b.disabled = true; });
  stream.replaceChildren();
  const ran = new Set<string>();
  for (const b of boxes) {
    const title = q(`[data-step="${b.value}"] .step__title`).textContent ?? b.value;
    if (!b.checked) { logLine(`Not run: ${title}. Not approved.`, 'skipped'); continue; }
    setPill(b.value, 'running');
    await wait(240);
    setPill(b.value, 'done');
    ran.add(b.value);
    logLine(`Done: ${title}`, 'done');
  }
  runBtn.textContent = 'Ran in replay';
  fillAudit(ran);
  if (ran.has('s2')) q('#outbox-empty').textContent = '3 tracking emails queued: dana@example.com and 2 more.';
});

const receiptStep: Record<string, string> = {
  refund_order: 's5', create_restock_po: 's4', send_email: 's2', mark_shipped: 's1',
};
function fillAudit(ran: Set<string>) {
  const list = q<HTMLOListElement>('#audit-list');
  list.replaceChildren();
  for (const r of safety.auditReceipt.filter((x) => ran.has(receiptStep[x.tool]))) {
    const li = document.createElement('li');
    const ts = document.createElement('span');
    ts.className = 'receipt__ts money';
    ts.textContent = r.ts;
    const what = document.createElement('span');
    what.className = 'receipt__what';
    const sum = document.createElement('span');
    sum.textContent = r.summary;
    const ids = document.createElement('code');
    ids.className = 'receipt__ids wrap-any';
    ids.textContent = `${r.tool} ${r.id}`;
    what.append(sum, ids);
    const undo = document.createElement('span');
    undo.className = 'receipt__undo';
    const tag = document.createElement('span');
    tag.className = r.undo ? 'can-undo' : 'pill pill--irreversible';
    tag.textContent = r.undo ? 'Can undo' : 'Irreversible';
    undo.append(tag);
    li.append(ts, what, undo);
    list.append(li);
  }
}

// Tabs: Inbox / Outbox / Audit, arrow keys move between them.
const tabs = qa<HTMLButtonElement>('[role="tab"]');
function selectTab(tab: HTMLButtonElement) {
  tabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    q<HTMLElement>(`#${t.getAttribute('aria-controls')}`).hidden = !on;
  });
}
tabs.forEach((t, i) => {
  t.addEventListener('click', () => selectTab(t));
  t.addEventListener('keydown', (e) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    const next = tabs[(i + step + tabs.length) % tabs.length];
    selectTab(next);
    next.focus();
  });
});
q<HTMLAnchorElement>('#plan-blocked a').addEventListener('click', () => selectTab(tabs[0]));

// Reset: two-step inline confirm, then reload the seeded state.
const resetBtn = q<HTMLButtonElement>('#reset-btn');
let armed: number | undefined;
resetBtn.addEventListener('click', () => {
  if (armed) { location.reload(); return; }
  resetBtn.textContent = 'Click again to reset';
  armed = window.setTimeout(() => { armed = undefined; resetBtn.textContent = 'Reset demo store'; }, 4000);
});
