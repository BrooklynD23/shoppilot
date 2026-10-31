// Console controller: boot, plan, clarify, approve, run, drawer, undo, reset, team stage.
// Shapes: REPO/app/main.py. Copy: REPO/docs/specs/06-ui-demo.md §4/§5. Team: ./team.ts.
import { STAGE_3D_MIN_PX } from './agents';
import { api, hooks, scenario, type ApiError } from './api';
import {
  auditItem, clean, count, el, isMoneyOut, mailItem, money, outboxItem, runRow, setRun, stepRow, verdicts,
  type AuditRow, type Diff, type Email, type OutboxRow, type Step, type ToolFlags, type Validation,
} from './render';
import { createTeam, type PlanData, type Stage } from './team';

const PLAN_TIMEOUT_MS = 95_000;
const SLOW_AFTER_S = 12;
const WAKE_AFTER_MS = 3000;
const RESET_ARM_MS = 4000;
const REVEAL_FAILSAFE_MS = 12_000;

interface Modes { store_name: string; llm_mode: string; stripe_mode: string }
interface PlanRes extends PlanData {
  plan_id: string; source: 'live' | 'replay';
  plan: PlanData['plan'] & { request: string; steps: Step[] };
  validations: Validation[]; diff: Diff[]; tools: Record<string, ToolFlags>;
  clarify: { question: string; options: string[] } | null;
  usage: { calls?: { stage?: string; ms?: number; input_tokens: number; cache_read_tokens: number; cache_write_tokens: number; output_tokens: number }[]; total_cost_usd?: number };
}
interface StepResult { ok: boolean; summary: string; data: Record<string, any>; error: string | null; step_id: string; audit_id: string | null }

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const root = document.querySelector<HTMLElement>('[data-console]');
if (root) init(root);

function init(root: HTMLElement) {
  const input = $<HTMLTextAreaElement>('request-input');
  const form = $<HTMLFormElement>('ask');
  const planBtn = $<HTMLButtonElement>('plan-btn');
  const replayBtn = $<HTMLButtonElement>('replay-btn');
  const planEl = $('plan');
  const heading = $('plan-heading');
  const planStatus = $('plan-status');
  const stepsEl = $('steps');
  const runBar = $('run-bar');
  const runBtn = $<HTMLButtonElement>('run-btn');
  const stream = $('stream');
  const stageEl = $('stage');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const team = createTeam(root);
  const notice = (msg: string) => { $('notice-line').textContent = msg; };
  const say = (msg: string) => { planStatus.textContent = msg; };

  const state = {
    modes: { store_name: 'Demo store', llm_mode: 'live', stripe_mode: 'mock' } as Modes,
    products: new Map<string, string>(),
    plan: null as PlanRes | null,
    ctl: null as AbortController | null,
    abortWhy: '' as '' | 'cancel' | 'timeout' | 'superseded',
    prevState: 'empty',
    lastReq: '', lastReplay: false, clarifyBase: '',
    running: false, ran: false,
    cooldown: 0,
    runIds: [] as string[],
  };

  // ---------- modes, meter ----------
  function applyModes(m: Partial<Modes>) {
    state.modes = { ...state.modes, ...m };
    $('store-name').textContent = clean(state.modes.store_name);
    $('stripe-tag').textContent = state.modes.stripe_mode === 'test' ? 'Stripe test mode' : 'Stripe mock';
    const mode = state.modes.llm_mode;
    const text = mode === 'live' ? ''
      : mode === 'replay' ? 'Recorded mode: plans come from saved recordings, not live Claude. Tools, guard and audit still run for real.'
      : mode === 'record' ? 'Record mode: live Claude plans are saved as recordings for replay.'
      : 'Mock mode: plans are canned, not from Claude. Tools, guard and audit still run.';
    $('mode-banner').hidden = !text;
    $('mode-text').textContent = text;
    updateOut();
  }

  const METER_KEY = 'sp-console-usage';
  function readMeter() {
    try { return JSON.parse(sessionStorage.getItem(METER_KEY) ?? '') as { cost: number; tok: number; cacheRead: number; inTok: number }; }
    catch { return { cost: 0, tok: 0, cacheRead: 0, inTok: 0 }; }
  }
  // "Label value" like Inbox and Audit, short enough to keep the console bar on one row; tokens live in the tooltip.
  function showMeter(m = readMeter()) {
    const meter = $('cost-meter');
    const cost = `$${m.cost.toFixed(4)}`, cached = m.inTok ? Math.round((100 * m.cacheRead) / m.inTok) : 0;
    meter.textContent = m.tok ? `AI ${cost} · ${cached}% cached` : 'No AI cost yet this session';
    meter.title = m.tok ? `AI cost this session: ${cost} for ${m.tok >= 1000 ? (m.tok / 1000).toFixed(1) + 'k' : m.tok} tokens, ${cached}% read from the prompt cache.` : '';
  }
  function addUsage(u: PlanRes['usage'] | undefined) {
    const calls = Array.isArray(u?.calls) ? u!.calls : [];
    const prev = readMeter();
    const inTok = calls.reduce((t, c) => t + (c.input_tokens || 0) + (c.cache_read_tokens || 0) + (c.cache_write_tokens || 0), 0);
    const next = {
      cost: prev.cost + (Number(u?.total_cost_usd) || 0),
      tok: prev.tok + inTok + calls.reduce((t, c) => t + (c.output_tokens || 0), 0),
      cacheRead: prev.cacheRead + calls.reduce((t, c) => t + (c.cache_read_tokens || 0), 0),
      inTok: prev.inTok + inTok,
    };
    try { sessionStorage.setItem(METER_KEY, JSON.stringify(next)); } catch { /* per-viewer convenience only */ }
    showMeter(next);
  }

  // ---------- global error ----------
  function globalError(msg: string, retry?: () => void) {
    $('error').hidden = !msg;
    $('error-text').textContent = msg;
    const b = $<HTMLButtonElement>('error-retry');
    b.hidden = !retry;
    b.onclick = retry ? () => { $('error').hidden = true; retry(); } : null;
  }

  // ---------- drawer: team log, inbox, outbox, audit, guide ----------
  const drawer = $<HTMLDialogElement>('drawer');
  const tabs = [...drawer.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  const tabOf = (kind: string) => tabs.find((t) => t.id === `tab-${kind}`) ?? tabs[1];
  function selectTab(tab: HTMLButtonElement) {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute('aria-controls')!).hidden = !on;
    }
  }
  function openDrawer(kind: string, focus?: HTMLElement | null) {
    const tab = tabOf(kind);
    selectTab(tab);
    if (!drawer.open) drawer.showModal();
    (focus ?? tab).focus();
  }
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => selectTab(t));
    t.addEventListener('keydown', (e) => {
      const to = e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowLeft' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : null;
      if (to === null) return;
      e.preventDefault();
      const next = tabs[(to + tabs.length) % tabs.length];
      selectTab(next);
      next.focus();
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-open]').forEach((b) => b.addEventListener('click', () => openDrawer(b.dataset.open!)));
  $('drawer-close').addEventListener('click', () => drawer.close());
  drawer.addEventListener('click', (e) => { if (e.target === drawer) drawer.close(); }); // the backdrop
  const setCount = (kind: string, text: string) => document.querySelectorAll(`[data-count="${kind}"]`).forEach((n) => { n.textContent = text; });

  const lists = { inbox: $('inbox-list'), outbox: $('outbox-list'), audit: $('audit-list') };
  function railError(kind: keyof typeof lists, label: string, reload: () => void) {
    const btn = el('button', { class: 'btn btn-line btn-sm', type: 'button' }, 'Retry');
    btn.addEventListener('click', reload);
    lists[kind].replaceChildren(el('p', { class: 'empty' }, `${label} did not load. `, btn));
    lists[kind].removeAttribute('aria-busy');
  }
  async function loadStore() {
    const r = await api<Modes & { products: { id: string; name: string }[]; orders_total: number }>('GET', '/api/store');
    if (!r.ok) return;
    applyModes(r.data);
    state.products = new Map((r.data.products ?? []).map((p) => [p.id, clean(p.name)]));
    $('store-stats').textContent = `${count(r.data.orders_total ?? 0, 'order', 'orders')}, ${count(state.products.size, 'product', 'products')}`;
  }
  async function loadInbox() {
    const r = await api<Email[]>('GET', '/api/inbox');
    if (!r.ok) return railError('inbox', 'Inbox', loadInbox);
    const mails = Array.isArray(r.data) ? r.data : [];
    lists.inbox.replaceChildren(...(mails.length ? mails.map(mailItem) : [el('p', { class: 'empty' }, 'No customer emails yet.')]));
    lists.inbox.removeAttribute('aria-busy');
    setCount('inbox', verdicts(mails.map((m) => m.verdict)).text || String(mails.length)); // "1 blocked, 3 held", as Guard says it
    team.guard(mails);
  }
  async function loadOutbox() {
    const r = await api<OutboxRow[]>('GET', '/api/outbox');
    if (!r.ok) return railError('outbox', 'Outbox', loadOutbox);
    const rows = Array.isArray(r.data) ? r.data : [];
    lists.outbox.replaceChildren(...(rows.length ? rows.map(outboxItem)
      : [el('p', { class: 'empty' }, 'Nothing sent yet. Emails the agent writes land here, never in a real inbox.')]));
    lists.outbox.removeAttribute('aria-busy');
    setCount('outbox', rows.length ? String(rows.length) : '');
  }
  async function loadAudit() {
    const r = await api<{ chain_ok: boolean; actions: AuditRow[] }>('GET', '/api/audit');
    if (!r.ok) return railError('audit', 'Audit log', loadAudit);
    const rows = Array.isArray(r.data.actions) ? r.data.actions : [];
    const chain = $('chain-line');
    chain.lastChild!.textContent = r.data.chain_ok
      ? ` Hash chain verified: ${count(rows.length, 'entry', 'entries')}, none edited.`
      : ' Hash chain check failed. The log may have been edited.';
    chain.classList.toggle('bad', !r.data.chain_ok);
    lists.audit.replaceChildren(rows.length ? el('ol', { class: 'receipt' }, ...rows.map(auditItem))
      : el('p', { class: 'empty' }, 'No actions yet. Every action you approve is logged here with an undo button.'));
    lists.audit.removeAttribute('aria-busy');
    setCount('audit', rows.length ? String(rows.length) : '');
  }
  const refreshAfterChange = () => Promise.all([loadAudit(), loadOutbox(), loadStore()]);

  // Undo (event delegation; buttons are rebuilt on every audit refresh).
  lists.audit.addEventListener('click', async (e) => {
    const b = (e.target as Element).closest<HTMLButtonElement>('[data-undo]');
    if (!b) return;
    const id = b.dataset.undo!;
    const errEl = lists.audit.querySelector<HTMLElement>(`[data-undo-err="${id}"]`);
    b.disabled = true;
    b.lastChild!.textContent = 'Undoing…';
    const r = await api<{ ok: boolean; summary: string }>('POST', `/api/undo/${encodeURIComponent(id)}`);
    if (r.ok) {
      $('undo-msg').textContent = `Undone. ${clean(r.data.summary)}`;
      await refreshAfterChange();
      $('panel-audit').focus(); // the Undo button is gone; keep focus in the panel
      return;
    }
    if (errEl) errEl.textContent = `Could not undo: ${errorCopy(r.error)}`;
    b.disabled = false;
    b.lastChild!.textContent = 'Undo';
  });

  // ---------- plan states ----------
  function setState(s: string) { planEl.dataset.state = s; }
  let timer = 0;
  function startTimer() {
    const t0 = Date.now();
    $('slow-line').hidden = true;
    const tick = () => {
      const s = Math.floor((Date.now() - t0) / 1000);
      $('plan-timer').textContent = `Planning… ${s} s`;
      if (s >= SLOW_AFTER_S) $('slow-line').hidden = false;
    };
    tick();
    timer = window.setInterval(tick, 1000);
  }
  const stopTimer = () => { clearInterval(timer); timer = 0; };
  function busyButtons(planning: boolean) {
    planBtn.disabled = planning || state.running || state.cooldown > 0;
    replayBtn.disabled = state.running || state.cooldown > 0;
    $<HTMLButtonElement>('err-replay').disabled = state.cooldown > 0;
    $<HTMLButtonElement>('err-retry').disabled = state.cooldown > 0;
  }
  // Frame the team and the top of the plan together while the team works.
  const brief = root.querySelector<HTMLElement>('.brief')!;
  const showTeam = () => brief.scrollIntoView({ block: 'start', behavior: reduce.matches ? 'auto' : 'smooth' });
  // Planning: leave a reader who already scrolled past alone (the mini team strip covers them).
  const frameTeam = () => { if (brief.getBoundingClientRect().top >= 56) showTeam(); };
  // Run and "Retry from here" always call showTeam: the run is the moment to watch, even from the receipt. Not
  // "only if off screen": that check races a Review scroll still in flight. The sticky run bar stays below it.

  async function plan(raw: string, replay: boolean) {
    const request = raw.trim();
    if (!request) { input.focus(); say('Type a request first.'); return; }
    if (state.ctl) { state.abortWhy = 'superseded'; state.ctl.abort(); }
    const ctl = new AbortController();
    Object.assign(state, { ctl, abortWhy: '', lastReq: request, lastReplay: replay });
    if (planEl.dataset.state !== 'loading') state.prevState = planEl.dataset.state ?? 'empty';
    setState('loading');
    $('plan-meta').textContent = '';
    $('replay-banner').hidden = true;
    runBar.hidden = true;
    startTimer();
    busyButtons(true);
    say(replay ? 'Loading the recorded plan' : 'Planning');
    team.planStart();
    frameTeam();
    const to = window.setTimeout(() => { state.abortWhy = 'timeout'; ctl.abort(); }, PLAN_TIMEOUT_MS);
    const r = await api<PlanRes>('POST', '/api/plan', { request, replay }, ctl.signal);
    clearTimeout(to);
    if (state.ctl !== ctl) return; // superseded by a newer request
    state.ctl = null;
    stopTimer();
    busyButtons(false);
    if (!r.ok) {
      if (r.error.code === 'aborted' && state.abortWhy === 'cancel') {
        setState(state.plan && state.prevState === 'ready' ? 'ready' : 'empty');
        if (state.plan && state.prevState === 'ready') runBar.hidden = false;
        say('Cancelled. Your store is unchanged.');
        notice('Cancelled. Your store is unchanged.');
        team.cancel();
        return;
      }
      return planError(r.error.code === 'aborted' ? { status: 0, code: 'timeout', message: '' } : r.error);
    }
    showPlan(r.data, request);
  }

  function errorCopy(e: ApiError): string {
    const m = clean(e.message);
    switch (e.code) {
      case 'rate_limited': return `Too many requests. You can try again in ${dur(e.retry_after_s ?? 10)}.`;
      case 'demo_budget_reached': return `Today's demo budget is used up. Planning opens again in ${dur(e.retry_after_s ?? 3600)}. Offline fixtures still work.`;
      case 'replay_miss': return state.modes.llm_mode === 'replay' ? replayOnly()
        : 'No recorded plan for this request yet. Try Plan it for a live plan, or open the offline fixtures.';
      case 'timeout': return 'Claude did not answer in time. Your store is unchanged.';
      case 'bad_request': return 'ShopPilot+ could not read that request. Keep it between 1 and 500 characters.';
      case 'too_large': return 'That request is too long. Shorten it and try again.';
      case 'bad_content_type': case 'csrf': return 'The request was blocked by a safety check. Reload the page and try again.';
      case 'no_session': return 'Your demo store expired. Reload the page to get a fresh one.';
      case 'plan_invalid': return 'This plan cannot run as approved. Plan it again.';
      case 'plan_not_found': return 'That plan is gone, maybe after a reset. Plan it again.';
      case 'plan_expired': return 'This plan expired after 15 minutes. Plan it again to get fresh checks.';
      case 'already_undone': return 'This action was already undone.';
      case 'not_undoable': return m || 'This action cannot be undone.';
      case 'changed_since': return 'This changed since, so undo would overwrite newer work.';
      case 'undo_failed': return m || 'The undo did not go through.';
      case 'not_built': return 'This part is not built yet.';
      case 'not_found': return m || 'Not found.';
      default: return 'Something broke on our side. Nothing was changed.';
    }
  }
  // A replay server plays recordings on both buttons, so a miss is never fixed by "Plan it" or "Try again".
  const isExample = (r: string) => [...document.querySelectorAll<HTMLElement>('[data-prompt]')].some((c) => c.dataset.prompt === r);
  const replayOnly = () => (isExample(state.lastReq)
    ? 'This demo server has no recording for this example yet. Open the offline fixtures to see the whole flow.'
    : 'This demo server only has recorded plans for the three examples. Pick one, or open the offline fixtures.');
  const dur = (s: number) => {
    const n = Math.max(0, Math.ceil(s));
    if (n < 90) return `${n} s`;
    const h = Math.floor(n / 3600), min = Math.ceil((n % 3600) / 60);
    return h ? `${h} h ${min} min` : `${min} min`;
  };

  let cdTimer = 0;
  function planError(e: ApiError) {
    setState('error');
    const msg = $('plan-error-msg');
    const showActions = (retry: boolean, replay: boolean, fixtures: boolean) => {
      $('err-retry').hidden = !retry; $('err-replay').hidden = !replay; $('err-fixtures').hidden = !fixtures || !!scenario;
    };
    clearInterval(cdTimer);
    if ((e.code === 'rate_limited' || e.code === 'demo_budget_reached') && e.retry_after_s) {
      const end = Date.now() + e.retry_after_s * 1000;
      const tick = () => {
        state.cooldown = Math.max(0, Math.ceil((end - Date.now()) / 1000));
        msg.textContent = state.cooldown ? errorCopy({ ...e, retry_after_s: state.cooldown }).replace('try again', 'plan again') : 'You can plan again now.';
        busyButtons(false);
        if (!state.cooldown) clearInterval(cdTimer);
      };
      tick();
      cdTimer = window.setInterval(tick, 1000);
      showActions(e.code === 'rate_limited', true, e.code === 'demo_budget_reached');
    } else {
      msg.textContent = errorCopy(e);
      const stuck = e.code === 'replay_miss' && state.modes.llm_mode === 'replay'; // both retries replay the same miss
      showActions(!stuck, !stuck, e.code === 'replay_miss');
    }
    if (e.code === 'bad_request' || e.code === 'too_large') input.focus();
    say(msg.textContent ?? '');
    team.planFail(msg.textContent ?? '');
  }

  // Rows and the run bar enter in step with the team replay; everything is in the DOM already.
  let revealT = 0;
  const reveal = (id: string) => stepsEl.querySelector(`[data-step="${CSS.escape(id)}"]`)?.removeAttribute('data-enter');
  const revealAll = () => {
    clearTimeout(revealT);
    stepsEl.querySelectorAll('[data-enter]').forEach((n) => n.removeAttribute('data-enter'));
    runBar.removeAttribute('data-enter');
    updateOut();
  };

  // Touching the plan mid-replay shows every row at once; the team keeps talking on stage.
  planEl.addEventListener('pointerdown', revealAll);
  planEl.addEventListener('keydown', revealAll);

  function showPlan(d: PlanRes, request: string) {
    addUsage(d.usage);
    const p = d.plan;
    $('replay-banner').hidden = d.source !== 'replay';
    if (p.status === 'needs_clarification') return showClarify(d, request);
    if (p.status !== 'ready') {
      setState('error');
      // Replay server: the planner's miss text ("Run: python -m tests.eval.record") is for developers. It stays in the team log.
      const stuck = p.status === 'error' && state.modes.llm_mode === 'replay';
      const text = stuck ? replayOnly()
        : clean(p.message) || (p.status === 'refused' ? 'ShopPilot+ will not do that request.' : 'Something broke on our side. Nothing was changed.');
      $('plan-error-msg').textContent = text;
      $('err-retry').hidden = p.status === 'refused' || stuck;
      $('err-replay').hidden = stuck;
      $('err-fixtures').hidden = !stuck || !!scenario;
      say(text);
      heading.focus({ preventScroll: true });
      team.planEnd(d, () => {}, () => {}, stuck ? text : undefined);
      return;
    }
    state.plan = d; state.ran = false; state.runIds = [];
    $('runlog').hidden = true;
    stream.replaceChildren();
    const vById = new Map(d.validations.map((v) => [v.step_id, v]));
    const dById = new Map(d.diff.map((x) => [x.step_id, x]));
    stepsEl.replaceChildren(...p.steps.map((s, i) => stepRow(i + 1, s, vById.get(s.id), dById.get(s.id), d.tools?.[s.tool], state.products)));
    const valid = p.steps.filter((s) => vById.get(s.id)?.ok !== false);
    const gated = valid.filter((s) => d.tools?.[s.tool]?.moves_money).length;
    $('plan-meta').textContent = p.steps.length ? `${count(p.steps.length, 'step', 'steps')}, ${gated} ${gated === 1 ? 'needs' : 'need'} your approval` : '';
    const blocked = (p.blocked_inputs ?? []).filter((b) => !b.allowed);
    $('plan-blocked').hidden = !blocked.length;
    $('plan-blocked-text').textContent = blocked.length === 1 ? 'Guard kept 1 inbox email out of this plan.' : `Guard kept ${blocked.length} inbox emails out of this plan.`;
    $('see-it').dataset.target = blocked[0] ? String(blocked[0].source_id).replace(/^email:/, '') : '';
    // The judge can only add friction (spec 02 D3): a concern is shown, and "fail" unticks every step.
    const j = p.judge;
    const concern = j && j.verdict !== 'pass' && j.note !== 'judge unavailable'
      ? (j.checks ?? []).filter((c) => c && c.pass === false && c.note).map((c) => clean(c.note)).join(' ') || 'Read every step before you run.' : '';
    $('plan-judge').hidden = !concern;
    $('plan-judge-text').textContent = concern ? `Judge${j?.verdict === 'fail' ? ' failed this plan' : ' has a concern'}: ${concern}` : '';
    if (j?.verdict === 'fail') stepsEl.querySelectorAll<HTMLInputElement>('[data-approve]').forEach((b) => { b.checked = false; });
    const nothing = $('plan-nothing');
    nothing.hidden = !!valid.length;
    nothing.textContent = p.steps.length ? 'Nothing here is safe to run. Edit the request and try again.'
      : 'ShopPilot+ found nothing to do for that request. Try one of the examples.';
    runBar.hidden = !p.steps.length;
    setState('ready');
    if (!reduce.matches) {
      stepsEl.querySelectorAll<HTMLElement>('.step').forEach((n) => n.setAttribute('data-enter', ''));
      runBar.setAttribute('data-enter', '');
      revealT = window.setTimeout(revealAll, REVEAL_FAILSAFE_MS);
    }
    updateOut();
    heading.focus({ preventScroll: true });
    say(`Plan ready: ${count(p.steps.length, 'step', 'steps')}, ${gated} ${gated === 1 ? 'needs' : 'need'} approval${blocked.length ? `. Guard kept ${count(blocked.length, 'email', 'emails')} out` : ''}.`);
    team.planEnd(d, reveal, revealAll);
  }

  function showClarify(d: PlanRes, request: string) {
    state.clarifyBase = request;
    $('clarify-q').textContent = clean(d.clarify?.question || d.plan.message || 'Can you say a bit more?');
    const opts = Array.isArray(d.clarify?.options) ? d.clarify!.options : [];
    $('clarify-options').replaceChildren(...opts.map((o) => {
      const b = el('button', { class: 'chip', type: 'button' }, clean(o));
      b.addEventListener('click', () => answer(String(o)));
      return b;
    }));
    $<HTMLInputElement>('clarify-input').value = '';
    setState('clarify');
    heading.focus({ preventScroll: true });
    say(`ShopPilot+ needs one answer: ${$('clarify-q').textContent}`);
    team.planEnd(d, () => {}, () => {});
  }
  const answer = (a: string) => { if (a.trim()) plan(`${state.clarifyBase}\n\nAnswer: ${a.trim()}`.slice(0, 2000), false); };
  $('clarify').addEventListener('submit', (e) => { e.preventDefault(); answer($<HTMLInputElement>('clarify-input').value); });

  // ---------- approve + money out ----------
  const boxes = () => [...stepsEl.querySelectorAll<HTMLInputElement>('[data-approve]')];
  const reviewBtn = $<HTMLButtonElement>('review-btn');
  let waitBoxes: HTMLInputElement[] = []; // money-out boxes still waiting for a tick, in plan order
  function updateOut() {
    const d = state.plan;
    const mode = state.modes.stripe_mode === 'test' ? 'Stripe test mode' : 'Stripe mock';
    if (!d) return;
    let out = 0, waiting = 0, approved = false;
    waitBoxes = [];
    for (const b of boxes()) {
      const s = d.plan.steps.find((x) => x.id === b.dataset.approve)!;
      const amt = d.diff.find((x) => x.step_id === s.id)?.amount_cents ?? 0;
      if (!isMoneyOut(s, d.tools?.[s.tool]) || b.closest('.step--invalid')) continue;
      if (b.checked) { out += amt; approved = true; } else if (!b.disabled) { waiting += amt; waitBoxes.push(b); }
    }
    // After a clean run the bar reports what happened, stops floating and points to the audit log.
    $('out-label').textContent = !state.ran ? 'Money out if you run' : out ? 'Run complete. Refunded' : 'Run complete. Money out';
    $('money-out').textContent = money(out);
    $('money-out').classList.toggle('money', out > 0);
    $('money-note').textContent = `(${mode})`;
    reviewBtn.hidden = state.ran || !waiting;
    reviewBtn.textContent = waitBoxes.length > 1 ? `Review ${waitBoxes.length} refunds, ${money(waiting)}` : `Review the ${money(waiting)} refund`;
    runBar.toggleAttribute('data-done', state.ran);
    runBtn.hidden = state.ran;
    $('audit-btn').hidden = !state.ran;
    runBtn.disabled = state.running || state.ran || !boxes().some((b) => b.checked && !b.disabled);
    if (!state.running && !state.runIds.length && !runBar.hasAttribute('data-enter')) team.approval(waiting, approved);
  }
  stepsEl.addEventListener('change', updateOut);
  // The approval moment, actionable from the bar: bring the money row to the middle and put focus on its box.
  reviewBtn.addEventListener('click', () => {
    const b = waitBoxes[0];
    if (!b) return;
    b.closest('.step')?.scrollIntoView({ block: 'center', behavior: reduce.matches ? 'auto' : 'smooth' });
    b.focus({ preventScroll: true });
  });

  // ---------- run ----------
  function setStepPill(id: string, kind: string, text: string) {
    const p = stepsEl.querySelector(`[data-step="${id}"] [data-pill]`);
    if (p) { p.className = `pill pill--${kind}`; p.textContent = text; }
    if (kind === 'done') stepsEl.querySelector(`[data-step="${id}"] .pill--approval`)?.remove();
  }
  async function run(from = 0) {
    const d = state.plan;
    if (!d || state.running) return;
    revealAll();
    showTeam();
    state.running = true;
    busyButtons(false);
    const bx = boxes();
    if (from === 0) {
      state.runIds = bx.filter((b) => b.checked && !b.disabled).map((b) => b.dataset.approve!);
      stream.replaceChildren(...d.plan.steps.map((s, i) => {
        const row = runRow(i + 1, s);
        if (!state.runIds.includes(s.id)) setRun(row, 'skipped');
        else setRun(row, 'pending');
        return row;
      }));
      $('runlog').hidden = false;
    }
    bx.forEach((b) => { b.disabled = true; });
    runBtn.disabled = true;
    const rowOf = (id: string) => stream.querySelector<HTMLElement>(`[data-run="${id}"]`)!;
    const total = state.runIds.length;
    let failedAt = -1;
    for (let i = from; i < total; i++) {
      const id = state.runIds[i];
      const row = rowOf(id);
      const step = d.plan.steps.find((s) => s.id === id)!;
      row.querySelector('.retry')?.remove();
      setRun(row, 'running');
      setStepPill(id, 'running', 'Running');
      team.execStart(i + 1, total, step);
      const r = await api<{ results: StepResult[] }>('POST', '/api/execute', { plan_id: d.plan_id, approved_step_ids: [id] });
      const res = r.ok ? r.data.results?.[0] : undefined;
      if (res?.ok) {
        const ref = res.data?.stripe_refund_id ?? res.data?.po_id ?? res.data?.link_id ?? res.audit_id ?? '';
        setRun(row, 'done', res.summary, String(ref));
        setStepPill(id, 'done', 'Done');
        team.execEnd(res, i + 1, total);
        continue;
      }
      failedAt = i;
      const why = r.ok ? (res?.summary || 'This step failed; nothing else ran.') : errorCopy(r.error);
      setRun(row, 'failed', why);
      setStepPill(id, 'failed', 'Failed');
      team.execEnd({ ok: false, summary: why, error: res?.error ?? null }, i + 1, total);
      const n = d.plan.steps.findIndex((s) => s.id === id) + 1;
      const retry = el('button', { class: 'btn btn-line btn-sm retry', type: 'button' }, 'Retry from here');
      retry.addEventListener('click', () => run(i));
      row.querySelector('.run-main')!.append(retry);
      for (const later of state.runIds.slice(i + 1)) {
        setRun(rowOf(later), 'notrun', `Stopped after step ${n} failed.`);
        setStepPill(later, 'planned', 'Not run');
      }
      break;
    }
    state.running = false;
    state.ran = failedAt === -1;
    busyButtons(false);
    updateOut();
    await refreshAfterChange();
    const done = stream.querySelectorAll('[data-state="done"]').length;
    team.runEnd(failedAt === -1, done);
    notice(failedAt === -1 ? `Run finished: ${count(done, 'step', 'steps')} done. Every action is in the audit log.`
      : `Run stopped: ${count(done, 'step', 'steps')} done, 1 failed. Fix it or retry from the failed step.`);
  }
  runBtn.addEventListener('click', () => run(0));

  // ---------- wiring ----------
  form.addEventListener('submit', (e) => { e.preventDefault(); plan(input.value, false); });
  replayBtn.addEventListener('click', () => plan(input.value, true));
  $('slow-replay').addEventListener('click', () => plan(state.lastReq, true));
  $('err-replay').addEventListener('click', () => plan(state.lastReq || input.value, true));
  $('err-retry').addEventListener('click', () => plan(state.lastReq || input.value, state.lastReplay));
  $('cancel-btn').addEventListener('click', () => { if (state.ctl) { state.abortWhy = 'cancel'; state.ctl.abort(); } });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); } });
  document.querySelectorAll<HTMLButtonElement>('[data-prompt]').forEach((chip) => chip.addEventListener('click', () => {
    input.value = chip.dataset.prompt ?? '';
    say(`Filled: ${chip.textContent}. Press Plan it or Use recorded plan.`);
  }));
  $('see-it').addEventListener('click', () => {
    const target = document.getElementById(`mail-${$('see-it').dataset.target}`);
    openDrawer('inbox', target ?? $('panel-inbox'));
  });

  // Two-step reset: "Reset demo store" -> "Click again to wipe your store" for 4 s.
  const resetBtn = $<HTMLButtonElement>('reset-btn');
  let armed = 0;
  resetBtn.addEventListener('click', async () => {
    if (!armed) {
      resetBtn.textContent = 'Click again to wipe your store';
      resetBtn.dataset.armed = '';
      armed = window.setTimeout(disarm, RESET_ARM_MS);
      return;
    }
    disarm();
    resetBtn.disabled = true;
    const r = await api<Modes>('POST', '/api/session', { reset: true });
    resetBtn.disabled = false;
    if (!r.ok) return globalError(`Reset failed. ${errorCopy(r.error)}`);
    state.plan = null; state.ran = false; state.runIds = [];
    stepsEl.replaceChildren(); stream.replaceChildren();
    $('runlog').hidden = true; runBar.hidden = true;
    $('replay-banner').hidden = true; $('plan-meta').textContent = '';
    setState('empty');
    team.reset();
    applyModes(r.data);
    await Promise.all([loadStore(), loadInbox().then(loadAudit), loadOutbox()]); // audit after the inbox: screening it logs guard_block
    notice('Fresh demo store ready.');
  });
  function disarm() {
    clearTimeout(armed); armed = 0;
    resetBtn.textContent = 'Reset demo store';
    delete resetBtn.dataset.armed;
  }

  hooks.onFreshSession = (s) => { applyModes(s as Modes); notice('Your demo store expired, so you have a fresh one.'); };

  if (scenario) {
    $('fixture-banner').hidden = false;
    $('fixture-text').textContent = `Offline fixtures (${scenario}). Nothing here touches a server.`;
    document.querySelectorAll<HTMLElement>('[data-export]').forEach((a) => a.closest('ul')!.setAttribute('hidden', ''));
    $('exports-off').hidden = false;
  }

  const asked = new URLSearchParams(location.search).get('q');
  if (asked) input.value = asked.slice(0, 500);
  showMeter();

  // ---------- 3D stage: WebGL2, motion allowed and a stage at least STAGE_3D_MIN_PX wide ----------
  // Otherwise the 2D portraits stay (phones never fetch the 590 kB chunk). stage3d.ts owns data-mode.
  let stage3d: Stage | null = null;
  let booted = false, loading = false, gl2: boolean | undefined;
  const canWebGL2 = () => {
    try {
      const gl = document.createElement('canvas').getContext('webgl2');
      gl?.getExtension('WEBGL_lose_context')?.loseContext();
      return !!gl;
    } catch { return false; }
  };
  function load3d() {
    // Unrounded width, like the CSS container query: clientWidth rounds 799.6 up to 800.
    if (!booted || stage3d || loading || reduce.matches || stageEl.getBoundingClientRect().width < STAGE_3D_MIN_PX) return;
    if (!(gl2 ??= canWebGL2())) return;
    loading = true;
    import('./stage3d').then((m) => {
      if (stage3d || reduce.matches) return;
      stage3d = m.mount(stageEl, drop3d);
      team.attach(stage3d);
    }).catch(() => { /* the chunk did not load: the 2D portraits stay */ })
      .finally(() => { loading = false; });
  }
  function drop3d() {
    team.detach();
    stage3d?.dispose();
    stage3d = null;
  }
  reduce.addEventListener('change', () => (reduce.matches ? drop3d() : load3d()));
  new ResizeObserver(() => load3d()).observe(stageEl); // a window widened past the gate gets the 3D too

  async function boot() {
    const wake = window.setTimeout(() => notice('Waking the server. Free hosting sleeps when idle; this can take up to a minute.'), WAKE_AFTER_MS);
    const s = await api<Modes>('POST', '/api/session', { reset: false });
    clearTimeout(wake);
    if (!s.ok) {
      notice('');
      return globalError('Cannot reach ShopPilot+. Check your connection, then try again.', boot);
    }
    notice('');
    applyModes(s.data);
    await Promise.all([loadStore(), loadInbox().then(loadAudit), loadOutbox()]); // audit after the inbox: screening it logs guard_block
  }
  // The 3D chunk waits until the API calls are done and the main thread is idle; the portraits hold the stage.
  boot().then(() => {
    booted = true;
    if ('requestIdleCallback' in window) requestIdleCallback(load3d, { timeout: 2000 });
    else setTimeout(load3d, 300); // Safari: no requestIdleCallback
  });
}
