// Stock forecast mini-chart (spec 06 §6, adapted to app/ml/forecast.py), one drawing for /app/ (drawForecast) and
// the landing (components/landing/ForecastChart.astro): projected stock = on_hand minus cumulative demand, 80% band
// stock.lo..stock.hi. Stock cannot go below 0, so every value clamps there: the line ends on the dashed
// "Out of stock" floor, and the plot stops 2 days after the latest likely stockout.
// Paths sit in a stretched viewBox (strokes are non-scaling); dots and labels sit on top in CSS px with x in %,
// so labels keep one size at every width.
const NS = 'http://www.w3.org/2000/svg';
const W = 280, H = 152, L = 16, R = 264, TOP = 28, BOT = 124;

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

export interface Part { tag: string; attrs: Record<string, string | number>; text?: string }

/** The chart as plain parts: `plot` goes in an <svg viewBox preserveAspectRatio="none">, `marks` on top of it. */
export function forecastParts(f: Forecast) {
  const dts = f.days_to_stockout;
  const n = dts == null ? f.stock.mean.length : Math.min(f.stock.mean.length, (f.stockout_range?.[1] ?? dts) + 2);
  // [day, stock] from day 0 (on hand), with the zero crossing added before clamping, so a line keeps its slope
  // down to the floor instead of bending at the last whole day.
  const pts = (vs: number[]) => [f.on_hand, ...vs.slice(0, n)].flatMap((v, d, a) =>
    [...(a[d - 1] > 0 && v < 0 ? [[d - 1 + a[d - 1] / (a[d - 1] - v), 0]] : []), [d, Math.max(0, v)]]);
  const mean = pts(f.stock.mean), lo = pts(f.stock.lo), hi = pts(f.stock.hi);
  const yMax = Math.max(...hi.map(([, v]) => v), 1);
  const x = (d: number) => L + ((R - L) * d) / n;
  const y = (v: number) => TOP + ((BOT - TOP) * (yMax - v)) / yMax;
  const xy = ([d, v]: number[]) => `${x(d).toFixed(1)} ${y(v).toFixed(1)}`;
  const pct = (d: number) => `${((100 * x(d)) / W).toFixed(2)}%`;
  const end = mean.findIndex(([d, v]) => d > 0 && v === 0); // the middle line stops where it reaches 0
  const out = end < 0 ? null : mean[end][0];
  const mx = dts == null ? null : out ?? (dts <= n ? dts : null); // the "Runs out" marker sits on that point
  const plot: Part[] = [
    { tag: 'path', attrs: { class: 'chart-band', d: `M${[...hi.map(xy), ...lo.map(xy).reverse()].join(' L')} Z` } },
    { tag: 'line', attrs: { class: 'chart-zero', x1: L, x2: R, y1: BOT, y2: BOT } },
    ...(mx == null ? [] : [{ tag: 'line', attrs: { class: 'chart-marker', x1: x(mx).toFixed(1), x2: x(mx).toFixed(1), y1: 8, y2: BOT } }]),
    { tag: 'path', attrs: { class: 'chart-p50', d: `M${(end < 0 ? mean : mean.slice(0, end + 1)).map(xy).join(' L')}` } },
  ];
  const marks: Part[] = [
    { tag: 'circle', attrs: { class: 'chart-dot', cx: pct(0), cy: y(f.on_hand), r: 3 } },
    ...(out == null ? [] : [{ tag: 'circle', attrs: { class: 'chart-dot chart-dot--out', cx: pct(out), cy: BOT, r: 3 } }]),
    { tag: 'text', attrs: { class: 'chart-lbl chart-lbl--hi', x: pct(0), dx: 7, y: y(f.on_hand) - 8 }, text: `${f.on_hand} on hand` },
    // ponytail: the 58% cap keeps "Runs out ~day N" inside a 250 px chart; past it the label leaves its marker.
    ...(mx == null ? [] : [{ tag: 'text', attrs: { class: 'chart-lbl', x: pct(Math.min(mx, 0.58 * n)), dx: 6, y: TOP - 8 }, text: `Runs out ~day ${dts}` }]),
    { tag: 'text', attrs: { class: 'chart-lbl chart-lbl--bad', x: pct(n), y: BOT - 7, 'text-anchor': 'end' }, text: 'Out of stock' },
    { tag: 'text', attrs: { class: 'chart-lbl', x: pct(0), y: H - 6 }, text: 'Today' },
    { tag: 'text', attrs: { class: 'chart-lbl', x: pct(n), y: H - 6, 'text-anchor': 'end' }, text: `Day ${n}` },
  ];
  return { viewBox: `0 0 ${W} ${H}`, height: H, plot, marks };
}

export function drawForecast(f: Forecast, id: string): HTMLElement {
  const p = forecastParts(f);
  const text = caption(f);
  const part = (e: Part) => svg(e.tag, e.attrs, e.text);
  const plot = svg('svg', { viewBox: p.viewBox, preserveAspectRatio: 'none' });
  plot.append(...p.plot.map(part));
  const root = svg('svg', { height: p.height, role: 'img', 'aria-labelledby': `${id}-t ${id}-d` });
  root.append(
    svg('title', { id: `${id}-t` }, `Stock forecast for ${f.name}`),
    svg('desc', { id: `${id}-d` }, text),
    plot,
    ...p.marks.map(part),
  );
  const fig = document.createElement('figure');
  fig.className = 'chart';
  const cap = document.createElement('figcaption');
  cap.textContent = `${text} Shaded: 80% range.`;
  fig.append(root, cap);
  return fig;
}
