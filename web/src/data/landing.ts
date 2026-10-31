// Final landing copy that is new on "/" (night to morning). Hero, how, safety, bento, closing
// and the quote come from ./v3.ts; pricing and FAQ from ./v2.ts; product facts from ./demo.ts.
// Budget: <= 220 copy words outside #pricing, #faq and [data-ui] (scripts/count-words.mjs).

export const builtWith = [
  { name: 'Claude', by: 'Anthropic' },
  { name: 'Stripe', by: 'test mode' },
  { name: 'FastAPI' },
  { name: 'SQLite' },
];

export const problem = {
  h2: 'Why we built it', // sr-only
  // Demo-store inbox at night (synthetic). Timestamps are Sunday night.
  inbox: [
    { ts: '21:06', from: 'jo.p@example.com', subject: 'Can I change my shipping address?' },
    { ts: '22:14', from: 'lee.m@example.com', subject: 'Will the lavender tin be back?' },
    { ts: '22:58', from: 'dana@example.com', subject: 'Box arrived crushed' },
    { ts: '23:41', from: 'sam.k@example.com', subject: 'Where is my order?' },
  ],
};

export const how = { line: 'Watch the demo store do it.' };
export const safety = { line: 'Every email is screened before the planner sees it.' };

export const morning = {
  h2: 'Monday morning: done.', // 3 words
  line: 'One approval at 21:52. Every step checked, run and logged.', // 10 words
  videoLabel: 'Packed orders on a shelf, morning light',
};

export const bentoLine = 'Real product, demo store.';

export const proof = {
  h2: 'Measured, not promised.',
  stats: [
    { value: '12%', label: 'lower forecast error', source: 'Prototype, synthetic data' },
    { value: '8 of 8', label: 'odd orders flagged', source: 'Prototype, synthetic data' },
    { value: '$0.014', label: 'per five-step plan', source: 'Demo store' },
  ],
};

export const closingLine = 'Run the Sunday cleanup on the demo store.';
