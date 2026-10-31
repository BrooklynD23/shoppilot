// Forecast chart geometry (src/scripts/console/chart.ts forecastParts) on the recorded fixture and a no-stockout case.
// Usage: node scripts/check-chart.mts   (exits 1 on a failed assert)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { forecastParts, type Forecast, type Part } from '../src/scripts/console/chart.ts';

const BOT = 124; // chart.ts: the 0 line
const plan = JSON.parse(readFileSync(new URL('../public/fixtures/plan.json', import.meta.url), 'utf8'));
const f: Forecast = plan.diff.map((d: any) => d.before?.forecast).find(Boolean);
const pairs = (p: Part) => [...String(p.attrs.d).matchAll(/([\d.]+) ([\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
const by = (ps: Part[], cls: string) => ps.filter((p) => String(p.attrs.class).split(' ').includes(cls));
const text = (ps: Part[]) => ps.map((p) => p.text).filter(Boolean);

// Fixture: 31 on hand, runs out ~day 4 (range 3 to 5); unclamped, the mean reaches -77 by day 14.
const a = forecastParts(f);
const [band] = by(a.plot, 'chart-band'), [line] = by(a.plot, 'chart-p50'), [marker] = by(a.plot, 'chart-marker');
assert.ok(pairs(band).every(([, y]) => y <= BOT) && pairs(line).every(([, y]) => y <= BOT), 'nothing below 0 stock');
assert.ok(text(a.marks).includes('Day 7'), 'plot stops 2 days after the range end (day 5)');
const last = pairs(line).at(-1)!;
assert.equal(last[1], BOT, 'the line ends on the 0 line');
assert.ok(pairs(line).every(([, y], i, ps) => i === 0 || y > ps[i - 1][1]), 'the line only falls: no flat run on 0');
assert.equal(Number(marker.attrs.x1).toFixed(1), last[0].toFixed(1), 'the marker sits where the line ends');
assert.equal(by(a.marks, 'chart-dot--out').length, 1);
assert.ok(text(a.marks).includes('Runs out ~day 4'));

// No stockout: the full horizon, no marker, no red dot.
const b = forecastParts({ ...f, days_to_stockout: null, stockout_range: null,
  stock: { mean: f.stock.mean.map((_, i) => 30 - i), lo: f.stock.mean.map((_, i) => 28 - i), hi: f.stock.mean.map((_, i) => 32 - i) } });
assert.ok(text(b.marks).includes(`Day ${f.stock.mean.length}`));
assert.equal(by(b.plot, 'chart-marker').length + by(b.marks, 'chart-dot--out').length, 0);
console.log('check-chart: 9 of 9 pass');
