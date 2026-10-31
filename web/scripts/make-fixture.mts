// Writes public/v2/fixtures/plan.json in the /api/plan response shape (spec 00 §7) from src/data/demo.ts.
import { writeFileSync } from 'node:fs';
import { plan, inbox, forecast } from '../src/data/demo.ts';
const out = {
  plan_id: plan.planId, source: 'replay',
  plan: {
    status: 'ok', request: "Ship yesterday's orders, email buyers tracking, restock what will run out this week, refund anything damaged.",
    steps: plan.steps.map((s) => ({ id: s.id, tool: s.tool, title: s.title, target: s.target, rationale: s.why })),
    blocked_inputs: inbox.filter((e) => !e.allowed).map((e) => ({ source_id: e.id, allowed: false, label: e.label, reason: e.reason, score: e.score, subject: e.subject, from: e.from })),
  },
  validations: plan.steps.map((s) => ({ step_id: s.id, ok: s.valid, reason: null })),
  diff: plan.steps.map((s) => ({ step_id: s.id, before: s.before, after: s.after, amount_cents: s.amountCents,
    ...(s.tool === 'forecast_demand' ? { forecast: { on_hand: forecast.onHand, days_to_stockout: forecast.daysToStockout, range: forecast.range, band: { p10: forecast.p10, p50: forecast.p50, p90: forecast.p90 } } } : {}) })),
  tools: Object.fromEntries(plan.steps.map((s) => [s.tool, { destructive: s.movesMoney, moves_money: s.movesMoney, undoable: s.undoable }])),
  clarify: null,
  usage: { total_cost_usd: plan.usage.costUsd, cache_hit_pct: plan.usage.cacheHitPct, input_tokens: 1840, output_tokens: 620, ms: 8400 },
  execute: Object.fromEntries(plan.steps.map((s) => [s.id, { ok: true, summary: s.tool === 'refund_order' ? 'Refunded $24.00 on order 1038' : `${s.title}: done`, audit_id: `a_${s.id}`, data: s.tool === 'refund_order' ? { refund_id: 're_test_fixture01' } : {} }])),
};
writeFileSync(new URL('../public/v2/fixtures/plan.json', import.meta.url), JSON.stringify(out, null, 2));
console.log('wrote plan.json', out.plan.steps.length, 'steps');
