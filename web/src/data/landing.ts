// Every line of copy on "/" lives here. Product facts (plan, inbox, forecast, money, receipts) come from
// ./run.ts, which reads the console's own recorded fixture, so the landing and the demo always agree.
// Voice: web/BRAND.md §6. h1 <= 8 words, sub <= 16, h2 <= 6 (+ grey line <= 10), button <= 3.
// Budget: <= 180 copy words on the page outside #pricing, #faq and [data-ui], nav and footer
// included (node scripts/count-words.mjs landing=http://127.0.0.1:4321/).
// Honesty: no logos, testimonials or metrics we do not have. Demo data says "Demo store".
import { AGENTS } from '../scripts/console/agents';
import * as run from './run';

// Counts follow the console roster, so the copy never disagrees with the demo. "Agent" would overclaim:
// only the members whose kind names a Claude model use one; the rest are plain code (agents.ts `kind`).
const WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];
const word = (k: number) => WORDS[k] ?? String(k);
const onClaude = AGENTS.filter((a) => /Haiku|Sonnet|Opus/.test(a.kind)).length;
const crewWord = word(AGENTS.length);

export const hero = {
  title: 'ShopPilot+: autopilot for your shop',
  h1: ['Autopilot for your shop.', 'You approve every dollar.'], // 8 words
  sub: `${crewWord} specialists ship orders, email buyers and draft restocks. They stop at the money.`, // 14
  cta: 'Try the demo',
  note: 'No signup. Runs on a seeded demo store.',
};

export const problem = {
  h2: 'Sunday night', // sr-only
  quote: 'I’m spending 4 or 5 hours every single day just on packing and shipping.',
  source: 'r/ecommerce, Feb 2025',
};

// The team is the console's roster (src/scripts/console/agents.ts): one mascot per real backend module.
// Here: each one's state at 21:52:02, the moment the plan waits for you. `tone` picks the pill.
type AgentId = (typeof AGENTS)[number]['id'];

// Words and numbers come from the recorded run (./run.ts); only the clock times are the story's.
const f = run.forecast;
const [lo, hi] = f.stockout_range ?? [f.days_to_stockout, f.days_to_stockout];
const steps = run.steps.length;

export const states: Record<AgentId, { word: string; tone: 'ok' | 'bad' | 'money' }> = {
  guard: { word: `Blocked ${run.blockedCount}`, tone: 'bad' },
  router: { word: 'In scope', tone: 'ok' },
  planner: { word: `${steps} steps`, tone: 'ok' },
  forecaster: { word: `${f.days_to_stockout} days left`, tone: 'ok' },
  validator: { word: `${run.passed} passed`, tone: 'ok' },
  judge: { word: run.judgePass ? 'All clear' : 'Warning', tone: run.judgePass ? 'ok' : 'bad' },
  executor: { word: 'Needs you', tone: 'money' },
};

export const team = {
  h2: `${crewWord} specialists. One approver.`,
  line: `${word(onClaude)} use Claude. ${word(AGENTS.length - onClaude)} are plain code.`, // 7
  room: 'Night shift',
  span: '21:51:57 to 21:52:02',
};

// One plan on the demo store, as the team hands it along. Money is in cents, set only where money waits.
export const thread: { ts: string; from: AgentId; to: AgentId | 'you'; text: string; money?: number; after?: string; code?: string }[] = [
  { ts: '21:51:57', from: 'guard', to: 'planner', text: `${run.inbox.length - run.blockedCount} emails passed. ${run.blockedCount} blocked.`, code: `${run.blocked.label} ${run.blocked.score}` },
  { ts: '21:51:57', from: 'router', to: 'planner', text: 'Shop work. In scope.' },
  { ts: '21:51:58', from: 'planner', to: 'forecaster', text: `${f.name}, next ${f.stock.mean.length} days?` },
  { ts: '21:51:59', from: 'forecaster', to: 'planner', text: `Runs out in about ${f.days_to_stockout} days. Range ${lo} to ${hi}.` },
  { ts: '21:52:00', from: 'planner', to: 'validator', text: `${steps} steps. Restock ${run.restockQty} units.` },
  { ts: '21:52:01', from: 'validator', to: 'judge', text: `${run.passed} of ${steps} pass your caps.` },
  { ts: '21:52:02', from: 'judge', to: 'executor', text: run.judgePass ? 'Matches your request. No warnings.' : 'One warning. Read before you run.' },
  { ts: '21:52:02', from: 'executor', to: 'you', text: '', money: run.refund.cents, after: 'refund waits for your approval.' },
];

export const safety = {
  h2: 'It said refund everything. Blocked.',
  line: 'Every email is screened before the planner reads it.', // 9
  // Mirrors app/safety/policy.py. Enforced in code at plan time and again at run time.
  caps: [
    { name: 'Refund per order', value: '$200.00' },
    { name: 'Refund total per plan', value: '$500.00' },
    { name: 'Refunds per plan', value: '3 max' },
    { name: 'Refund window', value: '30 days' },
  ],
  capsNote: 'Hard caps, checked in code outside the model',
  capsSource: 'app/safety/policy.py',
};

export const morning = {
  h2: 'Monday morning: done.',
  approvedAt: '21:52:03',
  runAt: ['21:52:04', '21:52:06', '21:52:09', '21:52:11'], // story clock, one per receipt
  line: 'One approval at 21:52. Every step checked, run and logged.', // 10
};

// No cost tile: no plan cost has been measured yet (web/src/data/report.ts `costs`, "pending W3").
// Both tiles are the Forecaster's work (agents.ts: "Forecasts demand and flags odd orders").
export const product = {
  h2: 'The Forecaster shows its work.', // 5
  tiles: {
    forecast: 'Demand forecast',
    flags: 'Odd order flags',
  },
  // Prototype results on synthetic data (docs/specs/03-ml-actions.md §6), the same numbers as /report/, with the
  // caveat that spec says to show: MAE 1.55 vs seasonal-naive 1.77 (it repeats last week) vs 28-day mean 1.56.
  forecastStat: { text: '12% lower error than last week’s pattern. Ties a 28-day average.', source: 'Prototype, synthetic data' },
  flagStat: { text: '8 of 8 planted orders flagged, 0 false alarms in 2,700.', source: 'Prototype, synthetic data' },
};

// Planned pricing: a student startup simulation. The label must show wherever prices show.
export const pricing = {
  h2: 'Planned pricing',
  label: 'Planned prices for a student startup simulation. Nothing is for sale.',
  tiers: [
    { name: 'Demo', price: '$0', period: '', features: ['Recorded plans, no signup', 'No real money moves', 'Reset the store any time'], cta: 'Try the demo', live: true },
    { name: 'Solo shop', price: '$19', period: 'a month, planned', features: ['300 plans a month', 'Refund cap you set', 'Audit log and undo, 90 days'], cta: 'Planned', live: false },
    { name: 'Growing shop', price: '$49', period: 'a month, planned', features: ['1,500 plans a month', 'Approval limits per person', 'Audit export, 1 year'], cta: 'Planned', live: false },
  ],
};

export const faq = {
  h2: 'Straight answers',
  items: [
    { q: 'Can it spend money without me?', a: 'No. A step that moves money waits for your checkbox. Refunds over $200 an order or $500 a plan cannot be planned at all.' },
    { q: 'What if I approve by mistake?', a: 'Undo it from the audit log. Shipping marks, Outbox emails and restock orders reverse. Card refunds cannot, and the checkbox says so first.' },
    { q: 'Does it connect to my store?', a: 'Not yet. The demo runs on a seeded store. Refunds go to Stripe test mode, or a mock when no test key is set, and emails stay in an in-app Outbox.' },
    { q: 'How does it size a restock?', a: 'A forecast per product with a low, middle and high range. The order covers the high end plus lead time.' },
    { q: 'What are the limits?', a: 'A student project built in two weeks. No Shopify or Etsy link, English only, and the numbers here come from synthetic data.' },
  ],
};

export const closing = {
  h2: 'Approve your first refund.',
  cta: 'Try the demo',
};
