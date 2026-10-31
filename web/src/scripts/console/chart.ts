// Stock forecast mini-chart (spec 06 §6, adapted to app/ml/forecast.py):
// projected stock = on_hand minus cumulative demand, 80% band stock.lo..stock.hi, stockout at 0.
const NS = 'http://www.w3.org/2000/svg';
const W = 280, H = 120, L = 16, R = 264, TOP = 16, BOT = 100;

export interface Forecast {
  name: string; sku?: string; on_hand: number; on_order?: number;
  days_to_stockout: number | null; stockout_range: [number, number] | null;
  stock: { mean: number[]; lo: number[]; hi: number[] };
}

export const isForecast = (f: any): f is Forecast =>
  !!f && typeof f.on_hand === 'number' && Array.isArray(f.stock?.mean) && f.stock.mean.length > 1
  && Array.isArray(f.stock.lo) && Array.isArray(f.stock.hi);

function svg(tag: string, attrs: Record<string, string | number>, text?: string) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  if (text !== undefined) n.textContent = text;
  return n;
}

export function caption(f: Forecast): string {
  const days = f.stock.mean.length;
  const onOrder = f.on_order ? `, ${f.on_order} on order` : '';
  if (f.days_to_stockout == null) return `Does not run out in the next ${days} days. ${f.on_hand} on hand${onOrder}.`;
  const [a, b] = f.stockout_range ?? [f.days_to_stockout, f.days_to_stockout];
  return `Runs out in about ${f.days_to_stockout} days (range ${a} to ${b}). ${f.on_hand} on hand${onOrder}.`;
}

export function drawForecast(f: Forecast, id: string): HTMLElement {
  const n = f.stock.mean.length; // day 1..n; day 0 = on_hand
  const mean = [f.on_hand, ...f.stock.mean], lo = [f.on_hand, ...f.stock.lo], hi = [f.on_hand, ...f.stock.hi];
  const yMax = Math.max(f.on_hand, ...hi), yMin = Math.min(0, ...lo);
  const x = (d: number) => L + ((R - L) * d) / n;
  const y = (v: number) => TOP + ((BOT - TOP) * (yMax - v)) / (yMax - yMin || 1);
  const line = (vs: number[]) => vs.map((v, d) => `${d ? 'L' : 'M'}${x(d).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const band = `${line(hi)} ${lo.map((v, d) => `L${x(d).toFixed(1)} ${y(v).toFixed(1)}`).reverse().join(' ')} Z`;
  const text = caption(f);

  const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-labelledby': `${id}-t ${id}-d` });
  root.append(
    svg('title', { id: `${id}-t` }, `Stock forecast for ${f.name}`),
    svg('desc', { id: `${id}-d` }, text),
    svg('path', { class: 'chart-band', d: band }),
    svg('line', { class: 'chart-zero', x1: L, x2: R, y1: y(0), y2: y(0) }),
    svg('path', { class: 'chart-p50', d: line(mean) }),
    svg('circle', { class: 'chart-dot', cx: x(0), cy: y(f.on_hand), r: 3 }),
    svg('text', { class: 'chart-lbl chart-lbl--hi', x: x(0) + 6, y: y(f.on_hand) - 5 }, `${f.on_hand} on hand`),
    svg('text', { class: 'chart-lbl chart-lbl--bad', x: R, y: y(0) - 4, 'text-anchor': 'end' }, 'Out of stock'),
  );
  if (f.days_to_stockout != null && f.days_to_stockout <= n) {
    const mx = x(f.days_to_stockout);
    root.append(
      svg('line', { class: 'chart-marker', x1: mx, x2: mx, y1: TOP - 4, y2: BOT }),
      svg('text', { class: 'chart-lbl', x: Math.min(mx + 4, R - 70), y: TOP + 2 }, `Runs out ~day ${f.days_to_stockout}`),
    );
  }
  const mid = Math.round(n / 2);
  root.append(
    svg('text', { class: 'chart-lbl', x: L, y: H - 4 }, 'Today'),
    svg('text', { class: 'chart-lbl', x: x(mid), y: H - 4, 'text-anchor': 'middle' }, `Day ${mid}`),
    svg('text', { class: 'chart-lbl', x: R, y: H - 4, 'text-anchor': 'end' }, `Day ${n}`),
  );
  const fig = document.createElement('figure');
  fig.className = 'chart';
  const cap = document.createElement('figcaption');
  cap.textContent = `${text} Shaded: 80% range.`;
  fig.append(root, cap);
  return fig;
}
