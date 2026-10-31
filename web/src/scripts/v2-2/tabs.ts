// Console rail tabs (Inbox / Outbox / Audit). Arrow keys move between tabs.
document.querySelectorAll<HTMLElement>('[role=tablist]').forEach((list) => {
  const tabs = [...list.querySelectorAll<HTMLButtonElement>('[role=tab]')];
  const pick = (t: HTMLButtonElement) =>
    tabs.forEach((x) => {
      const on = x === t;
      x.setAttribute('aria-selected', String(on));
      x.tabIndex = on ? 0 : -1;
      document.getElementById(x.getAttribute('aria-controls')!)!.hidden = !on;
    });
  list.addEventListener('click', (e) => {
    const t = (e.target as Element).closest<HTMLButtonElement>('[role=tab]');
    if (t) pick(t);
  });
  list.addEventListener('keydown', (e) => {
    const i = tabs.indexOf(document.activeElement as HTMLButtonElement);
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (i < 0 || !d) return;
    const t = tabs[(i + d + tabs.length) % tabs.length];
    pick(t);
    t.focus();
  });
});
