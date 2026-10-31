// Shared by the landing hero and the console: money format, pills, the run loop.

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
export const money = (cents: number) => usd.format(cents / 100);

export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
/** A delay that exists only for motion: zero under reduced motion. */
export const beat = (ms: number) => sleep(reducedMotion() ? 0 : ms);

export type PillKind = 'planned' | 'checked' | 'approval' | 'running' | 'done' | 'undone' | 'blocked' | 'skipped';

export function setPill(row: Element, kind: PillKind, text: string) {
  const pill = row.querySelector('[data-pill]');
  if (!pill) return;
  pill.className = `pill pill--${kind}`;
  pill.textContent = text;
}

/** Approved rows go Running then Done, in order. The rest show "Skipped, not approved". */
export async function runRows(rows: HTMLElement[], approved: (row: HTMLElement) => boolean, say: (msg: string) => void) {
  for (const [i, row] of rows.entries()) {
    if (!approved(row)) {
      setPill(row, 'skipped', 'Skipped, not approved');
      row.dataset.run = 'skipped';
      continue;
    }
    setPill(row, 'running', 'Running');
    row.dataset.run = 'running';
    say(`Running step ${i + 1} of ${rows.length}`);
    await beat(450);
    setPill(row, 'done', 'Done');
    row.dataset.run = 'done';
  }
}
