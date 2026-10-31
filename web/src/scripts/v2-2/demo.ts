// Live replay of the recorded plan. No framework, no innerHTML: rows are cloned
// from a server-rendered <template> and filled with textContent.
import { stepView, money } from './view';

type Fx = {
  plan: { steps: { id: string; tool: string; title: string; target: string; rationale: string }[] };
  validations: { step_id: string; ok: boolean }[];
  diff: { step_id: string; before: string; after: string; amount_cents: number | null }[];
  tools: Record<string, { moves_money: boolean; undoable: boolean }>;
  execute: Record<string, { ok: boolean; summary: string; audit_id: string; data?: { refund_id?: string } }>;
};

const FIXTURE = '/v2/fixtures/plan.json';
const FAIL = 'Could not load the recorded plan. Open the console instead.';
const reduce = matchMedia('(prefers-reduced-motion: reduce)');
const wait = (ms: number) => new Promise((r) => setTimeout(r, reduce.matches ? 0 : ms));

let cached: Promise<Fx> | null = null;
const load = () =>
  (cached ??= fetch(FIXTURE)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    .then((d: Fx) => {
      if (!Array.isArray(d?.plan?.steps) || !d.execute || !d.tools) throw new Error('bad fixture');
      return d;
    })
    .catch((e) => {
      cached = null;
      throw e;
    }));

const code = (t: string) => {
  const c = document.createElement('code');
  c.textContent = t;
  return c;
};

function init(root: HTMLElement) {
  const q = <T extends Element = HTMLElement>(s: string) => root.querySelector(s) as T;
  const form = q<HTMLFormElement>('[data-ask]');
  const ta = form.querySelector('textarea')!;
  const list = q('[data-steps]');
  const tpl = q<HTMLTemplateElement>('template[data-tpl]');
  const live = q('[data-live]');
  const runBtn = q<HTMLButtonElement>('[data-run]');
  const out = q('[data-money-out]');
  const head = q('[data-plan-h]');
  const count = q('[data-count]');
  const audit = document.querySelector('[data-audit]');
  let token = 0; // bumps on plan/reset so a stale timer chain stops

  const say = (t: string) => (live.textContent = t);
  const boxes = () => [...list.querySelectorAll<HTMLInputElement>('input[type=checkbox]')];
  const sync = () => {
    const b = boxes();
    const ready = root.dataset.state === 'ready';
    out.textContent = money(b.filter((x) => x.checked).reduce((t, x) => t + Number(x.dataset.cents || 0), 0));
    runBtn.disabled = !ready || !b.some((x) => x.checked);
    b.forEach((x) => (x.disabled = !ready));
  };
  const set = (s: string) => {
    root.dataset.state = s;
    sync();
  };
  const fail = () => {
    set('error');
    say(FAIL);
  };

  function row(d: Fx, s: Fx['plan']['steps'][number], i: number) {
    const df = d.diff.find((x) => x.step_id === s.id);
    const t = d.tools[s.tool] ?? { moves_money: false, undoable: false };
    const v = stepView({ title: s.title, target: s.target, amountCents: df?.amount_cents ?? null, movesMoney: t.moves_money, undoable: t.undoable });
    const li = tpl.content.firstElementChild!.cloneNode(true) as HTMLElement;
    const f = (k: string) => li.querySelector<HTMLElement>(`[data-f="${k}"]`)!;
    const text: Record<string, string> = {
      n: String(i + 1), tool: s.tool, title: s.title, target: v.target, why: s.rationale,
      before: df?.before ?? '', after: df?.after ?? '', money: v.money, pill: v.pill, 'approve-label': v.approve,
    };
    for (const k in text) f(k).textContent = text[k];
    li.dataset.step = s.id;
    li.dataset.state = v.state;
    li.toggleAttribute('data-money', t.moves_money);
    li.classList.add('is-in');
    f('money').dataset.kind = v.moneyKind;
    f('irrev').hidden = !v.irreversible;
    f('valid').hidden = !d.validations.find((x) => x.step_id === s.id)?.ok;
    const box = f('approve') as HTMLInputElement;
    box.checked = v.checked;
    if (t.moves_money) box.dataset.cents = String(df?.amount_cents ?? 0);
    else delete box.dataset.cents;
    const chart = li.querySelector<HTMLElement>('[data-f="chart"]');
    if (chart) chart.hidden = s.tool !== 'forecast_demand';
    return li;
  }

  async function plan() {
    const my = ++token;
    list.replaceChildren();
    set('loading');
    say('Planning');
    try {
      const [d] = await Promise.all([load(), wait(600)]);
      if (my !== token) return;
      const steps = d.plan.steps;
      count.textContent = `${steps.length} steps, ${steps.filter((s) => d.tools[s.tool]?.moves_money).length} needs your approval`;
      list.setAttribute('aria-busy', 'true');
      set('building');
      for (const [i, s] of steps.entries()) {
        if (i) await wait(200);
        if (my !== token) return;
        list.append(row(d, s, i));
      }
      list.setAttribute('aria-busy', 'false');
      set('ready');
      say(`Plan ready. ${count.textContent}. 1 inbox email was blocked.`);
      head.focus({ preventScroll: true });
    } catch {
      if (my === token) fail();
    }
  }

  async function run() {
    const my = token;
    set('running');
    let d: Fx;
    try {
      d = await load();
    } catch {
      return fail();
    }
    const rows = [...list.children] as HTMLElement[];
    for (const [i, li] of rows.entries()) {
      const pill = li.querySelector('[data-f="pill"]')!;
      if (!li.querySelector('input')!.checked) {
        li.dataset.state = 'skipped';
        pill.textContent = 'Skipped, not approved';
        continue;
      }
      li.dataset.state = 'running';
      pill.textContent = 'Running';
      say(`Running step ${i + 1} of ${rows.length}`);
      await wait(300);
      if (my !== token) return;
      const ex = d.execute[li.dataset.step!];
      if (!ex?.ok) return fail();
      li.dataset.state = 'done';
      pill.textContent = 'Done';
      const res = li.querySelector<HTMLElement>('[data-f="result"]')!;
      const rt = res.querySelector('[data-f="result-text"]')!;
      rt.replaceChildren(ex.summary);
      if (ex.data?.refund_id) rt.append('. Refund ', code(ex.data.refund_id));
      res.hidden = false;
      if (audit) {
        const a = document.createElement('li');
        a.append(ex.summary, ' ', code(ex.audit_id));
        audit.prepend(a);
      }
    }
    set('done');
    say('Done. Every step is in the audit log.');
  }

  function reset(msg: string) {
    token++;
    list.replaceChildren();
    audit?.replaceChildren();
    set('empty');
    say(msg);
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    plan();
  });
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) form.requestSubmit();
  });
  root.addEventListener('click', (e) => {
    const t = e.target as HTMLElement;
    const chip = t.closest<HTMLElement>('[data-prompt]');
    if (chip) {
      ta.value = chip.dataset.prompt!;
      plan();
    } else if (t.closest('[data-run]')) run();
    else if (t.closest('[data-reset]')) {
      reset('Demo reset.');
      ta.focus();
    }
  });
  root.addEventListener('change', (e) => {
    if ((e.target as Element).matches('input[type=checkbox]')) sync();
  });
  document.querySelectorAll('[data-reset-store]').forEach((b) => b.addEventListener('click', () => reset('Demo store reset.')));

  if (root.dataset.start) {
    delete root.dataset.start;
    reset('');
  } else sync();
}

document.querySelectorAll<HTMLElement>('[data-demo]').forEach(init);

// Nav CTA: with JS on, the demo is right here, so scroll to it instead of leaving.
const demo = document.getElementById('demo');
if (demo)
  document.querySelectorAll('a[data-demo-cta]').forEach((a) =>
    a.addEventListener('click', (e) => {
      e.preventDefault();
      demo.scrollIntoView({ behavior: reduce.matches ? 'auto' : 'smooth', block: 'start' });
      demo.querySelector<HTMLElement>('.chip')?.focus({ preventScroll: true });
    }),
  );
