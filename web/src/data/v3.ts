// Round 3 landing copy, shared by /v3/a, /v3/b, /v3/c. Word budget: <= 220 copy words per landing,
// excluding #pricing, #faq and product UI fragments marked [data-ui]. Count with scripts/count-words.mjs.
// Hero h1 <= 8 words, sub <= 16. Section headline <= 6 words + one line <= 15 words.
// Product facts (plan, inbox, forecast, money) stay in ./demo.ts; pricing and FAQ reuse ./v2.ts.

export const nav = { links: [{ label: 'Product', href: '#product' }, { label: 'Safety', href: '#safety' }, { label: 'Pricing', href: '#pricing' }], cta: 'Try the live demo' };

export const hero = {
  h1: 'Autopilot for your shop. You approve every dollar.', // 8 words
  sub: 'One sentence ships orders, emails buyers, restocks and refunds. Nothing moves money until you approve.', // 15
  cta: 'Try the live demo',
  note: 'No signup. Demo store, $0.', // 5
};

// Honest "built with" strip. No Shopify claim (no integration exists).
export const builtWith = {
  label: 'Built with',
  items: [
    { name: 'Claude', by: 'Anthropic' },
    { name: 'Stripe', by: 'test mode' },
    { name: 'FastAPI', by: 'in-house API' },
    { name: 'SQLite', by: 'audit log' },
  ],
};

export const proof = {
  h2: 'Measured, not promised.',
  line: 'Prototype numbers on synthetic demo data.',
  stats: [
    { value: '12%', label: 'lower forecast error', source: 'Prototype' },
    { value: '8 of 8', label: 'odd orders flagged', source: 'Prototype' },
    { value: '$0.014', label: 'per five-step plan', source: 'Demo store' },
  ],
};

export const how = {
  h2: 'One sentence. Five checked steps.',
  line: 'Plan, check, approve, run, undo. Watch the demo store do it.',
  steps: ['Plan', 'Check', 'Approve', 'Run', 'Undo'],
  loopLabel: 'Demo store walkthrough',
};

export const bento = {
  h2: 'Every guard, in plain sight.',
  line: 'Each tile is the real product running on the demo store.',
  tiles: [
    { key: 'approve', title: 'Approve every dollar' },
    { key: 'diff', title: 'Dry-run before it runs' },
    { key: 'guard', title: 'Injection guard' },
    { key: 'forecast', title: 'Demand forecast' },
    { key: 'anomaly', title: 'Odd order flags' },
    { key: 'audit', title: 'Audit log and undo' },
  ],
};

export const safety = {
  h2: 'It said refund everything. Blocked.',
  line: 'Every inbox email is screened before the planner ever sees it.',
  caps: ['$200 per order', '$500 per plan', '30-day window', 'Card refunds are final'],
};

export const quote = {
  text: "I'm spending 4 or 5 hours every single day just on packing and shipping.",
  source: 'r/ecommerce, Feb 2025',
};

export const pricingH2 = 'Planned pricing';
// Tiers: reuse pricing + pricingLabel from ./v2.ts (labelled simulation, <= 3 lines per tier).

export const faqH2 = 'Straight answers';
// Questions: reuse faq from ./v2.ts.

export const closing = {
  h2: 'Approve your first refund.',
  line: 'Open the demo store and run the Sunday cleanup.',
  cta: 'Try the live demo',
};

export const footer = {
  note: 'CS4680 course project. Student startup simulation; nothing is for sale.',
  links: [
    { label: 'App', href: 'app/' }, // prefix with /v3/<k>/
    { label: 'How it works', href: '/how-it-works/' },
    { label: 'Report', href: '/report/' },
  ],
};
