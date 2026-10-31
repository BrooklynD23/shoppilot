// Console wiring for the recorded demo: chips, Plan it, Run, Reset and the rail tabs.
// Nothing here calls a server; every message says it is a replay.
const form = document.querySelector<HTMLFormElement>('#console');
const ask = document.querySelector<HTMLTextAreaElement>('#ask');
const err = document.querySelector<HTMLElement>('#ask-err');
const status = document.querySelector<HTMLElement>('[data-status]');
const say = (msg: string) => { if (status) status.textContent = msg; };

document.querySelectorAll<HTMLButtonElement>('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    if (!ask) return;
    ask.value = chip.dataset.prompt ?? '';
    if (err) err.hidden = true;
    ask.removeAttribute('aria-invalid');
    ask.focus();
  });
});

form?.addEventListener('submit', (e) => {
  e.preventDefault();
  if (!ask || !err) return;
  const empty = ask.value.trim() === '';
  err.hidden = !empty;
  if (empty) {
    ask.setAttribute('aria-invalid', 'true');
    ask.focus();
    return;
  }
  ask.removeAttribute('aria-invalid');
  say('Showing the recorded plan for this request (replay).');
  document.querySelector<HTMLElement>('#app-title')?.focus();
});

form?.addEventListener('reset', () => {
  if (err) err.hidden = true;
  ask?.removeAttribute('aria-invalid');
  say('Demo store reset. The plan is back to its starting approvals.');
});

document.querySelector('[data-run]')?.addEventListener('click', () => {
  const boxes = [...document.querySelectorAll<HTMLInputElement>('input[name="approve"]')];
  const on = boxes.filter((b) => b.checked);
  const refund = boxes.find((b) => b.dataset.money);
  const refundNote = refund?.checked ? 'The refund is included and cannot be undone.' : 'The refund waits for its checkbox.';
  say(`Replay: ${on.length} of ${boxes.length} approved steps would run. ${refundNote}`);
});

const tabs = [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
const select = (tab: HTMLButtonElement) => {
  tabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    const panel = document.getElementById(t.getAttribute('aria-controls') ?? '');
    if (panel) panel.hidden = !on;
  });
};
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
