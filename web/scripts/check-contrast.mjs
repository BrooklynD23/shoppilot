// WCAG 2.1 contrast gate for src/styles/tokens.css. Exit 1 if any pair fails.
// Usage: node scripts/check-contrast.mjs
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8');
const tok = Object.fromEntries([...css.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));

// "#rrggbb" or "rgb(r g b / a)" -> [r, g, b, a] in 0..1
function parse(name) {
  const v = tok[name];
  if (!v) throw new Error(`missing token --${name}`);
  if (v.startsWith('#')) return [...v.slice(1).match(/\w\w/g).map((x) => parseInt(x, 16) / 255), 1];
  const m = v.match(/rgb\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+))?\s*\)/);
  if (!m) throw new Error(`cannot parse --${name}: ${v}`);
  return [m[1] / 255, m[2] / 255, m[3] / 255, m[4] === undefined ? 1 : Number(m[4])];
}
const flat = (fg, bg) => fg.slice(0, 3).map((c, i) => c * fg[3] + bg[i] * (1 - fg[3])); // composite over an opaque base
const lum = (rgb) => rgb.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)).reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0);
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// [foreground, background, minimum, opaque base under a translucent background]
const pairs = [];
for (const s of ['n', 'm']) {
  for (const surf of ['bg', 's1', 's2']) for (const ink of ['ink', 'ink-2', 'ink-3', 'money', 'ok', 'bad', 'run']) pairs.push([`${s}-${ink}`, `${s}-${surf}`, 4.5]);
  pairs.push([`${s}-ink-3`, `${s}-s3`, 4.5]);
  for (const k of ['money', 'ok', 'bad', 'run']) pairs.push([`${s}-${k}`, `${s}-${k}-bg`, 4.5, `${s}-s1`]);
  pairs.push([`${s}-ink-2`, `${s}-muted-bg`, 4.5, `${s}-s1`]);
  pairs.push([`${s}-line-ctl`, `${s}-bg`, 3]); // control edges (WCAG 1.4.11)
}
pairs.push(['on-money', 'money-fill', 4.5]);

let fails = 0;
for (const [fgName, bgName, min, baseName] of pairs) {
  const bg = baseName ? flat(parse(bgName), parse(baseName)) : flat(parse(bgName), [1, 1, 1]);
  const r = ratio(flat(parse(fgName), bg), bg);
  const ok = r >= min;
  if (!ok) fails++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${r.toFixed(2).padStart(5)} >= ${min}  --${fgName} on --${bgName}${baseName ? ` (over --${baseName})` : ''}`);
}
console.log(fails ? `\n${fails} pair(s) below WCAG AA` : `\nall ${pairs.length} pairs pass`);
process.exit(fails ? 1 : 0);
