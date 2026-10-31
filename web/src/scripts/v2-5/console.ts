// Console mockup behaviour: rail tabs, request chips, honest replies for Plan it / Run, 2-step reset.
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T | null;

function initTabs(): void {
  const tabs = [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  const select = (tab: HTMLButtonElement, focus = true) => {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      const panel = $(t.getAttribute('aria-controls') ?? '');
      if (panel) panel.hidden = !on;
    });
    if (focus) tab.focus();
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', (e) => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (e.key === 'Home') select(tabs[0]);
      else if (e.key === 'End') select(tabs[tabs.length - 1]);
      else if (step) select(tabs[(i + step + tabs.length) % tabs.length]);
      else return;
      e.preventDefault();
    });
  });
  // "See it" in the blocked notice: open Inbox and focus the blocked email.
  document.querySelector('a[href="#inbox"]')?.addEventListener('click', (e) => {
    e.preventDefault();
    select(tabs[0], false);
    $('em_7')?.focus();
  });
}

export function initConsole(): void {
  initTabs();
  const input = $<HTMLTextAreaElement>('request-input');
  const status = $('request-status');
  const form = $<HTMLFormElement>('request-form');
  document.querySelectorAll<HTMLButtonElement>('[data-prompt]').forEach((chip) => {
    chip.addEventListener('click', () => { if (input) { input.value = chip.dataset.prompt ?? ''; input.focus(); } });
  });
  form?.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!input || !status) return;
    if (!input.value.trim()) { status.textContent = 'Type a request first, or pick a suggestion.'; input.focus(); return; }
    status.textContent = 'This mockup shows the recorded plan below. The live console plans on the server.';
    $('plan-h')?.focus();
  });

  $('run-btn')?.addEventListener('click', () => {
    const out = $('run-status');
    if (out) out.textContent = 'This mockup does not run steps. The live console runs approved steps on the server.';
  });

  const reset = $<HTMLButtonElement>('reset-btn');
  let armed = 0;
  reset?.addEventListener('click', () => {
    if (!armed) {
      reset.textContent = 'Click again to reset';
      armed = window.setTimeout(() => { armed = 0; reset.textContent = 'Reset demo store'; }, 4000);
      return;
    }
    window.location.reload();
  });
}
