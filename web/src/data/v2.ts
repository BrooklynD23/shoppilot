// Shared landing copy and proof for the 6 v2 approaches.
// Product data (plan, inbox, forecast, money) stays in ./demo.ts.
// Honesty rules: no fake logos, testimonials or metrics. Seeded numbers say "Demo store".
// Prototype ML numbers come from docs/specs/03-ml-actions.md §6 (synthetic data).

export const positioning = 'Safe autopilot for your shop: see every dollar before it moves.';

export const hero = {
  // h1 <= 2 lines at desktop width. Approaches may reword but keep the positioning.
  h1: 'Safe autopilot for your shop. See every dollar before it moves.',
  // <= 20 words (18).
  sub: 'Ships orders, emails tracking, restocks and refunds from one sentence. Nothing that costs money runs until you approve.',
  cta: 'Try the live demo',
  ctaNote: 'No signup. Runs a recorded plan on a demo store, so it costs nothing.',
  secondary: 'Watch the 90 s demo',
};

export const chips = [
  { label: 'Sunday cleanup', prompt: "Ship yesterday's orders, email buyers tracking, restock what will run out this week, refund anything damaged." },
  { label: 'Stockout check', prompt: 'What will stock out in the next 14 days? Draft restock orders for those.' },
  { label: 'WISMO replies', prompt: 'Answer every "where is my order" email with tracking.' },
] as const;

export const problem = {
  quote: "I'm spending 4 or 5 hours every single day just on packing and shipping.",
  source: 'r/ecommerce, about Feb 2025. One of 3 threads in a small Reddit spot check.',
  fear: 'Agents that act need a gate and an undo. Most AI tools for shops do the work but hide the controls.',
};

// "Three proof numbers (measured)". All from the prototype or the demo store, labelled as such.
export const proof = [
  { value: '12%', label: 'lower forecast error than a seasonal-naive baseline', source: 'Prototype backtest, synthetic demo data' },
  { value: '8 of 8', label: 'planted suspicious orders flagged, 0 false alarms in 2,700', source: 'Prototype test, synthetic demo data' },
  { value: '$0.014', label: 'Claude cost for one five-step plan', source: 'Demo store run' },
] as const;
export const proofNote = 'Prototype numbers on synthetic data. Re-measured on the final build before launch.';

export const howSteps = [
  { key: 'plan', name: 'Plan', pill: 'Planned', text: 'You type one sentence. The AI turns it into typed steps: which tool, which orders, why.' },
  { key: 'check', name: 'Check', pill: 'Checked', text: 'A validator checks every step against your store and your rules before anything runs.' },
  { key: 'approve', name: 'Approve', pill: 'Needs approval', text: 'You see each change and every dollar. Steps that move money wait for your click.' },
  { key: 'run', name: 'Run', pill: 'Done', text: 'Approved steps run in order. Each one writes a receipt to the audit log.' },
  { key: 'undo', name: 'Undo', pill: 'Undone', text: 'Changed your mind? Undo shipping marks, emails and restock orders from the audit log. Card refunds are final, and the approve box says so.' },
] as const;

// Cursor-style agent state pills. Hex values are a suggestion; approaches tune them for AA.
export const pills = {
  planned: 'Planned', checked: 'Checked', approval: 'Needs approval', running: 'Running',
  done: 'Done', undone: 'Undone', blocked: 'Blocked',
} as const;

export const safety = {
  heading: 'One email tried to trick the agent. It never reached it.',
  body: 'Every inbox email is screened before the planner sees it. This one told the agent to ignore its rules and refund every order.',
  verdictPlain: 'Blocked: tries to make the agent ignore its rules and refund every order.',
  caps: [
    { name: 'Refund caps', text: 'Over $200 per order or $500 per plan, a refund cannot be planned at all, whatever an email says.' },
    { name: 'Refund window', text: 'Orders older than 30 days are refused by the validator, with the reason shown.' },
    { name: 'Approval gate', text: 'Every step that moves money waits for your checkbox.' },
    { name: 'Audit and undo', text: 'Every action is logged with a receipt. Everything except a card refund can be undone.' },
  ],
  auditReceipt: [
    { ts: '21:52:11', tool: 'refund_order', summary: 'Refunded $24.00 on order 1038', id: 're_test_3Nx8', undo: false },
    { ts: '21:52:09', tool: 'create_restock_po', summary: 'Drafted PO for 48 Lavender tins, est. $312.00', id: 'po_0007', undo: true },
    { ts: '21:52:06', tool: 'send_email', summary: '3 tracking emails to the Outbox', id: 'ob_0003', undo: true },
    { ts: '21:52:04', tool: 'mark_shipped', summary: 'Orders 1041, 1042, 1043 marked shipped', id: 'a_0011', undo: true },
  ],
  technical: 'Guard label prompt_injection, score 0.98. Screened by Claude Haiku before planning.',
};

export const anomalies = [
  { order: '1052', reason: 'Paid $3.00 for an item listed at $24.00 (12% of price)', score: 7.5 },
  { order: '1049', reason: '1 of 5 orders from this customer within an hour', score: 5.5 },
];
export const forecastCopy = {
  heading: 'Restock before you run out, not after.',
  body: 'Each product gets a demand forecast with a range, so a restock order is sized on what will sell, not a guess.',
  anomaliesHeading: 'Odd orders get flagged before you ship them.',
};

// Planned pricing. Must be labelled exactly with pricingLabel wherever it shows.
export const pricingLabel = 'Planned pricing, part of a student startup simulation; not for sale.';
export const pricing = [
  { name: 'Demo', price: '$0', period: '', blurb: 'Try it on a demo store.', features: ['Recorded plans, no signup', 'Stripe test mode only', 'Resets any time'], cta: 'Try the live demo' },
  { name: 'Solo shop', price: '$19', period: '/month planned', blurb: 'One store, one owner.', features: ['300 plans a month', 'Refund cap you set', 'Audit log and undo, 90 days'], cta: 'Planned' },
  { name: 'Growing shop', price: '$49', period: '/month planned', blurb: 'Up to 3 stores and 3 people.', features: ['1,500 plans a month', 'Per-person approval limits', 'Audit export, 1 year'], cta: 'Planned' },
] as const;

export const faq = [
  { q: 'Can it spend money without me?', a: 'No. Every step that moves money waits for your approval, and refunds above your cap cannot be planned at all.' },
  { q: 'What if I approve something by mistake?', a: 'Undo it from the audit log: restock orders are cancelled, shipping marks reverted, emails recalled from the Outbox. Card refunds cannot be reversed, so the refund checkbox says so before you tick it.' },
  { q: 'Does it connect to my real store?', a: 'Not yet. The demo runs on a seeded store and Stripe test mode. Emails stay in an in-app Outbox and never reach a real inbox.' },
  { q: 'How does it know what to restock?', a: 'A per-product demand forecast with a low and high range. The restock order covers the high end plus lead time.' },
  { q: 'What are the honest limits?', a: 'It is a student project built in two weeks. No Shopify or Etsy connection, English only, and the numbers on this page come from synthetic data.' },
] as const;

export const closing = {
  heading: 'See the plan before anything moves.',
  body: 'Open the demo store, ask for the Sunday cleanup, and approve the refund yourself.',
};

export const footer = {
  links: [
    { label: 'App', href: 'app/' }, // relative to the approach root, e.g. /v2/1/app/
    { label: 'How it works', href: '/how-it-works/' },
    { label: 'Report', href: '/report/' },
  ],
  course: 'ShopPilot+ is a CS4680 course project and a student startup simulation. Not a real company; nothing is for sale.',
};
