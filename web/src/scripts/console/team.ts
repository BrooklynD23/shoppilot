// Team director. Turns real API data into what each teammate does on the stage.
// It never invents an event: every line comes from a field in the response, or from the proposed
// `trace` (docs/specs/09-agent-trace.md). The DOM roster always updates (2D, reduced motion,
// screen readers); the 3D stage, when loaded, mirrors it.
import { AGENT_IDS, agentName, type AgentId } from './agents';
import { caption } from './chart';
import { clean, count, forecastOf, isMoneyOut, money, stepTitle, verdicts, type Diff, type Step, type ToolFlags, type Validation } from './render';

export type Mood = 'idle' | 'think' | 'talk' | 'pass' | 'alarm' | 'wait' | 'done' | 'cheer' | 'work';
type Part = string | { m: string }; // { m } = money: the one amber thing
export interface Beat {
  who: AgentId;
  mood: Mood;
  word?: string;         // state word under the name
  line?: Part[];         // speech bubble and team log
  to?: AgentId | 'you';  // hand a packet to (3D shows it travel)
  money?: boolean;       // that packet is money waiting for approval
  step?: string;         // reveal this plan row
  face?: boolean;        // the team turns to you
  flag?: 'blocked';      // the dot keeps this verdict through later moods (page-console.css [data-flag])
  t?: number;            // real ms since the request started, for the log
  gap?: number;          // ms before the next beat
}

/** Implemented by stage3d.ts. Every method is cosmetic; the DOM already carries the meaning. */
export interface Stage {
  mood(id: AgentId, m: Mood): void;
  toss(from: AgentId | 'you', to: AgentId | 'you', money: boolean): void;
  hold(id: AgentId, money: boolean | null): void;
  faceYou(on: boolean): void;
  receipt(n: number): void;
  anchor(id: AgentId): { x: number; y: number } | null;
  dispose(): void;
}

export interface TraceEvent { agent: AgentId; event: string; detail: string; t_ms: number; step_id?: string | null }
interface Call { stage?: string; ms?: number }
export interface PlanData {
  plan: { status: string; message: string; steps: Step[]; blocked_inputs: { source_id: string; allowed: boolean; label?: string; reason?: string }[];
    judge?: { verdict?: string; note?: string; checks?: { name?: string; note?: string; pass?: boolean }[] } | null };
  validations: Validation[]; diff: Diff[]; tools: Record<string, ToolFlags>;
  clarify: { question: string } | null;
  usage?: { calls?: Call[] };
  trace?: unknown;
}

const WORDS: Record<string, string> = { start: 'Working', read: 'Reading', staged: 'Drafted', pass: 'Passed', reject: 'Rejected', block: 'Blocked', warn: 'Warning', ask: 'Asking you', done: 'Done', error: 'Stopped' };
const MOODS: Record<string, Mood> = { start: 'think', read: 'talk', staged: 'pass', pass: 'done', reject: 'alarm', block: 'alarm', warn: 'alarm', ask: 'wait', done: 'done', error: 'alarm' };
const REST: Partial<Record<Mood, Mood>> = { talk: 'done', pass: 'done', think: 'done' };
const MAX_TRACE = 40;
const secs = (ms: number) => `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;

/** The proposed contract, checked field by field. Anything malformed means "no trace". */
export function readTrace(raw: unknown): TraceEvent[] | null {
  if (!Array.isArray(raw) || !raw.length) return null;
  // The backend may send up to 60 (spec 09): keep the last 3 (Judge, Planner done), so the replay ends where the plan does.
  const capped = raw.length > MAX_TRACE ? [...raw.slice(0, MAX_TRACE - 3), ...raw.slice(-3)] : raw;
  const ok = capped.filter((e): e is TraceEvent => !!e && typeof e === 'object'
    && AGENT_IDS.includes((e as TraceEvent).agent) && typeof (e as TraceEvent).event === 'string' && (e as TraceEvent).event in WORDS
    && typeof (e as TraceEvent).detail === 'string' && Number.isFinite((e as TraceEvent).t_ms));
  return ok.length ? ok.map((e) => ({ ...e, detail: clean(e.detail).slice(0, 160) })) : null;
}

function fromTrace(events: TraceEvent[]): Beat[] {
  const passes = new Map<AgentId, number>();
  // Real order and relative timing, compressed: a 9 s plan replays in about 6 s, every line readable.
  const span = Math.max(1, events[events.length - 1].t_ms - events[0].t_ms);
  const k = 3000 / span;
  return events.map((e, i) => {
    const next = events[i + 1];
    const n = (passes.get(e.agent) ?? 0) + (e.event === 'pass' || e.event === 'block' ? 1 : 0);
    passes.set(e.agent, n);
    const word = e.event === 'block' ? `Blocked ${n}`
      : e.event === 'pass' ? (e.agent === 'validator' ? `${n} passed` : e.agent === 'router' ? 'In scope' : 'Pass')
      : e.agent === 'router' && e.event === 'reject' ? 'Declined'
      : e.agent === 'forecaster' && e.event === 'read' ? 'Forecasted'
      : e.agent === 'planner' && (e.event === 'start' || e.event === 'staged') ? 'Drafting'
      : e.agent === 'judge' && e.event === 'start' ? 'Reviewing'
      : WORDS[e.event];
    return {
      who: e.agent, word, line: [e.detail], t: e.t_ms,
      mood: e.event !== 'pass' ? MOODS[e.event] : e.agent === 'router' ? 'pass' : e.agent === 'validator' || e.agent === 'judge' ? 'talk' : 'done',
      to: next && next.agent !== e.agent && next.agent !== 'guard' && e.agent !== 'guard' ? next.agent : undefined,
      step: e.agent === 'validator' && e.step_id ? String(e.step_id) : undefined,
      face: e.event === 'ask' || undefined,
      gap: next ? Math.min(800, Math.max(300, (next.t_ms - e.t_ms) * k)) : 700,
    };
  });
}

/** No trace yet: rebuild the story from fields the response already has. */
function derive(d: PlanData): Beat[] {
  const b: Beat[] = [];
  const calls = Array.isArray(d.usage?.calls) ? d.usage!.calls : [];
  const ms = (st: string) => calls.filter((c) => c.stage === st).reduce((t, c) => t + (Number(c.ms) || 0), 0);
  const turns = calls.filter((c) => c.stage === 'planner').length;
  const tRouter = ms('router'), tPlanner = tRouter + ms('planner');
  const p = d.plan, steps = Array.isArray(p.steps) ? p.steps : [];
  const msg = clean(p.message);

  const kept = (p.blocked_inputs ?? []).filter((x) => !x.allowed);
  const v = verdicts(kept);
  if (kept.length) b.push({ who: 'guard', mood: v.blocked ? 'alarm' : 'done', word: v.blocked ? `Blocked ${v.blocked}` : `Held ${v.held}`, t: 0,
    line: [`Kept ${count(kept.length, 'email', 'emails')} out of this plan${v.held ? ` (${v.text} for review)` : kept.length === 1 && kept[0].label ? ` (${clean(kept[0].label)})` : ''}.`] });

  if (calls.some((c) => c.stage === 'router')) {
    if (turns) b.push({ who: 'router', mood: 'pass', word: 'In scope', to: 'planner', t: tRouter, line: ['Shop work. Over to Planner.'] });
    else if (p.status === 'refused') b.push({ who: 'router', mood: 'alarm', word: 'Declined', t: tRouter, line: [msg || 'Not shop work, so I stopped here.'] });
  }

  const turnsText = turns ? ` in ${count(turns, 'turn', 'turns')}` : '';
  if (p.status === 'needs_clarification') {
    b.push({ who: 'planner', mood: 'wait', word: 'Asking you', face: true, t: tPlanner, line: [clean(d.clarify?.question) || msg || 'I need one answer first.'] });
    return b;
  }
  if (p.status === 'refused') {
    if (turns) b.push({ who: 'planner', mood: 'alarm', word: 'Declined', t: tPlanner, line: [msg || 'I will not do that request.'] });
    return b;
  }
  if (p.status === 'error') {
    b.push({ who: turns || !calls.length ? 'planner' : 'router', mood: 'alarm', word: 'Stopped', t: tPlanner, line: [msg || 'Something broke. Nothing was changed.'] });
    return b;
  }
  if (!steps.length) {
    b.push({ who: 'planner', mood: 'talk', word: 'Nothing to do', t: tPlanner, line: [msg || 'Nothing to do for that request.'] });
    return b;
  }

  const vById = new Map((d.validations ?? []).map((v) => [v.step_id, v]));
  const dById = new Map((d.diff ?? []).map((x) => [x.step_id, x]));
  b.push({ who: 'planner', mood: 'talk', word: count(steps.length, 'step', 'steps'), t: tPlanner, gap: 700,
    line: [`Read the store${turnsText}. Drafted ${count(steps.length, 'step', 'steps')}.`] });
  let passed = 0, failed = 0;
  steps.forEach((s, i) => {
    const f = forecastOf(dById.get(s.id));
    if (f) {
      b.push({ who: 'planner', mood: 'pass', to: 'forecaster', gap: 400, line: [`Step ${i + 1}: ${stepTitle(s)}. Over to Forecaster.`] });
      b.push({ who: 'forecaster', mood: 'talk', to: 'validator', gap: 800, word: f.days_to_stockout == null ? 'Holds up' : `Out in ~${f.days_to_stockout} d`,
        line: [`${clean(f.name)}: ${caption(f)}`] });
    } else {
      b.push({ who: 'planner', mood: 'pass', to: 'validator', gap: 360, line: [`Step ${i + 1}: ${stepTitle(s)}.`] });
    }
    const v = vById.get(s.id);
    if (v?.ok === false) {
      failed += 1;
      b.push({ who: 'validator', mood: 'alarm', step: s.id, word: `Blocked ${failed}`, gap: 900, line: [`Step ${i + 1} blocked: ${clean(v.reason) || 'it breaks a rule'}.`] });
    } else {
      passed += 1;
      b.push({ who: 'validator', mood: 'talk', step: s.id, word: `${passed} passed`, gap: 340, line: [`Step ${i + 1} passes.`] });
    }
  });

  const j = p.judge;
  if (j && typeof j === 'object') {
    const concern = (j.checks ?? []).find((c) => c && c.pass === false && c.note);
    const t = tPlanner + ms('judge');
    if (j.note === 'judge unavailable') b.push({ who: 'judge', mood: 'talk', word: 'No review', t, line: ['Review unavailable. Every step keeps its checks.'] });
    else if (j.verdict === 'pass') b.push({ who: 'judge', mood: 'talk', word: 'Pass', t, line: ['Reviewed. The plan matches your request.'] });
    else b.push({ who: 'judge', mood: 'alarm', word: j.verdict === 'fail' ? 'Fail' : 'Warning', t,
      line: [concern ? clean(concern.note) : 'I have a concern. Read the steps before you run.'] });
  }
  return b;
}

/** The Validator's last word counts the whole plan, so a blocked step 2 never ends the replay on "4 passed". */
function tally(d: PlanData): Beat | null {
  const steps = Array.isArray(d.plan.steps) ? d.plan.steps : [];
  const bad = new Set((d.validations ?? []).filter((v) => v.ok === false).map((v) => v.step_id));
  const blocked = steps.filter((s) => bad.has(s.id)).length;
  if (d.plan.status !== 'ready' || !blocked) return null;
  return { who: 'validator', mood: 'alarm', flag: 'blocked', word: `${blocked} of ${steps.length} blocked`, gap: 900, // "4 passed, 1 blocked" is 137 px: wider than a 3D label
    line: [`${steps.length - blocked} of ${steps.length} steps pass. ${count(blocked, 'blocked step', 'blocked steps')} cannot run.`] };
}

/** The approval moment, from the plan's own money data. */
function approvalBeat(d: PlanData): Beat | null {
  const steps = Array.isArray(d.plan.steps) ? d.plan.steps : [];
  if (d.plan.status !== 'ready' || !steps.length) return null;
  const vById = new Map((d.validations ?? []).map((v) => [v.step_id, v]));
  const valid = steps.filter((s) => vById.get(s.id)?.ok !== false);
  if (!valid.length) return { who: 'executor', mood: 'idle', word: 'Nothing to run', line: ['Nothing here is safe to run.'] };
  const out = valid.filter((s) => isMoneyOut(s, d.tools?.[s.tool]))
    .reduce((t, s) => t + (d.diff.find((x) => x.step_id === s.id)?.amount_cents ?? 0), 0);
  const gated = valid.filter((s) => d.tools?.[s.tool]?.moves_money).length;
  return {
    who: 'executor', mood: 'wait', word: 'Waiting for you', face: true, money: out > 0,
    line: out ? [{ m: money(out) }, ' waits for your approval.'] : gated ? [`${count(gated, 'step needs', 'steps need')} your approval.`] : ['Ready when you are.'],
  };
}

export function createTeam(root: HTMLElement) {
  const stageEl = root.querySelector<HTMLElement>('#stage')!;
  const members = new Map(AGENT_IDS.map((id) => [id, root.querySelector<HTMLElement>(`#crew [data-agent="${id}"]`)!]));
  const speech = root.querySelector<HTMLElement>('#speech')!;
  const whoEl = root.querySelector<HTMLElement>('#speech-who')!;
  const lineEl = root.querySelector<HTMLElement>('#speech-line')!;
  const logEl = document.getElementById('team-log')!;
  const logSrc = document.getElementById('team-log-src')!;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');

  let stage: Stage | null = null;
  const exLi = members.get('executor')!;
  /** true = amber money packet (waiting for you), false = approved paper packet, null = nothing held. */
  const hold = (v: boolean | null) => { holding = v; exLi.toggleAttribute('data-money', v === true); stage?.hold('executor', v); };
  let gen = 0;
  let timers: number[] = [];
  let hushT = 0;
  let speaker: AgentId | null = null;
  let receiptN = 0;
  let holding: boolean | null = null;
  let facing = false;

  const later = (ms: number, fn: () => void) => { const g = gen; timers.push(window.setTimeout(() => { if (g === gen) fn(); }, ms)); };
  const stop = () => { gen += 1; timers.forEach(clearTimeout); timers = []; };

  function set(id: AgentId, mood: Mood, word?: string) {
    const li = members.get(id)!;
    li.dataset.mood = mood;
    if (word !== undefined) li.querySelector('[data-word]')!.textContent = word;
    stage?.mood(id, mood);
  }
  const parts = (line: Part[]) => line.map((p) => {
    if (typeof p === 'string') return document.createTextNode(p);
    const s = document.createElement('span');
    s.className = 'money num';
    s.textContent = p.m;
    return s;
  });

  function place() {
    if (!speaker || speech.hidden) return;
    const a = stage?.anchor(speaker) ?? domAnchor(speaker);
    if (!a) return;
    const w = speech.offsetWidth, W = stageEl.clientWidth;
    const left = Math.max(8, Math.min(W - w - 8, a.x - w / 2));
    speech.style.setProperty('--bl', `${Math.round(left)}px`);
    speech.style.setProperty('--tx', `${Math.round(Math.max(16, Math.min(w - 16, a.x - left)))}px`);
  }
  function domAnchor(id: AgentId) {
    const p = members.get(id)!.querySelector('.portrait')!.getBoundingClientRect();
    const s = stageEl.getBoundingClientRect();
    return p.width ? { x: p.left - s.left + p.width / 2, y: p.top - s.top } : null;
  }
  function say(id: AgentId, line: Part[], holdMs = 4600) {
    speaker = id;
    whoEl.textContent = agentName(id);
    lineEl.replaceChildren(...parts(line));
    speech.hidden = false;
    speech.classList.remove('is-in');
    void speech.offsetWidth; // restart the enter transition
    speech.classList.add('is-in');
    place();
    if (strip) { document.getElementById('strip-who')!.textContent = agentName(id); document.getElementById('strip-line')!.replaceChildren(...parts(line)); }
    clearTimeout(hushT);
    if (holdMs) hushT = window.setTimeout(() => { speech.hidden = true; speaker = null; }, holdMs);
  }
  function log(id: AgentId, line: Part[], t?: number) {
    const li = document.createElement('li');
    const who = document.createElement('span');
    who.className = 'log-who';
    who.textContent = agentName(id);
    const text = document.createElement('span');
    text.className = 'log-line';
    text.append(...parts(line));
    li.append(who, text);
    if (t != null) {
      const ts = document.createElement('span');
      ts.className = 'log-t num';
      ts.textContent = secs(t);
      li.append(ts);
    }
    logEl.append(li);
  }

  new ResizeObserver(() => place()).observe(stageEl);

  // ---------- strip: a mini team under the header while the team works and the stage is scrolled away ----------
  // It copies the roster's state attributes (one observer, not a mirror in every setter) and the current line.
  // It appears once scrolling has settled for 700 ms, so the smooth scroll back to the team on Run never flashes it.
  const strip = document.getElementById('strip');
  const minis = new Map(AGENT_IDS.map((id) => [id, strip?.querySelector<HTMLElement>(`[data-agent="${id}"]`)]));
  let working = false, away = false, stripT = 0;
  const showStrip = () => {
    clearTimeout(stripT);
    if (!(working && away)) strip?.removeAttribute('data-on');
    else stripT = window.setTimeout(() => strip?.setAttribute('data-on', ''), 700);
  };
  const work = (on: boolean) => { working = on; showStrip(); };
  const LINGER_MS = 2500; // the last line stays readable in the strip
  if (strip) {
    new IntersectionObserver(([e]) => { away = e.intersectionRatio < 0.4; showStrip(); },
      { rootMargin: '-65px 0px 0px 0px', threshold: [0, 0.4] }).observe(stageEl); // 65 px: the sticky site header
    new MutationObserver((recs) => recs.forEach(({ target, attributeName: a }) => {
      const v = (target as HTMLElement).getAttribute(a!), m = minis.get((target as HTMLElement).dataset.agent as AgentId);
      if (m) { if (v === null) m.removeAttribute(a!); else m.setAttribute(a!, v); }
    })).observe(root.querySelector('#crew')!, { subtree: true, attributes: true, attributeFilter: ['data-mood', 'data-flag', 'data-money'] });
    addEventListener('scroll', () => { if (!strip.hasAttribute('data-on')) showStrip(); }, { passive: true }); // restarts the 700 ms wait
  }

  function calm(except: AgentId[] = []) {
    for (const id of AGENT_IDS) {
      if (except.includes(id)) continue;
      delete members.get(id)!.dataset.flag;
      set(id, 'idle', id === 'guard' ? undefined : 'Ready');
    }
  }

  /** `lastSay` replaces only the closing bubble; the team log keeps the response's own words. */
  function play(beats: Beat[], onStep: (id: string) => void, done: () => void, lastSay?: Part[]) {
    stop();
    const animate = !reduce.matches;
    let prev: Beat | null = null;
    const lastLine = [...beats].reverse().find((b) => b.line);
    const bubble = (b: Beat) => (b === lastLine && lastSay) || b.line!;
    const apply = (b: Beat) => {
      if (prev && prev.who !== b.who && REST[prev.mood]) set(prev.who, REST[prev.mood]!);
      set(b.who, b.mood, b.word);
      if (b.flag) members.get(b.who)!.dataset.flag = b.flag;
      if (b.line) { log(b.who, b.line, b.t); if (animate) say(b.who, bubble(b), b === lastLine ? 0 : 4600); }
      if (b.to) stage?.toss(b.who, b.to, !!b.money);
      if (b.step) onStep(b.step);
      if (b.who === 'executor' && b.money !== undefined) hold(b.money || null);
      if (b.face) { facing = true; stage?.faceYou(true); }
      prev = b;
    };
    if (!animate) {
      beats.forEach(apply);
      if (lastLine) say(lastLine.who, bubble(lastLine), 0);
      done();
      work(false);
      return;
    }
    work(true);
    let t = 0;
    for (const b of beats) { later(t, () => apply(b)); t += b.gap ?? 620; }
    later(t, done);
    later(t + LINGER_MS, () => work(false));
  }

  return {
    attach(s: Stage) {
      stage = s;
      for (const [id, li] of members) s.mood(id, (li.dataset.mood as Mood) || 'idle');
      s.receipt(receiptN);
      if (holding !== null) s.hold('executor', holding);
      if (facing) s.faceYou(true);
      place();
    },
    detach() { stage = null; },

    /** GET /api/inbox verdicts: Guard has already screened every email. */
    guard(mails: { verdict?: { allowed?: boolean; label?: string } }[]) {
      const { blocked, held, text } = verdicts(mails.map((m) => m.verdict));
      // The dot keeps the verdict through every later mood: never a green OK next to "Blocked 1".
      const flag = blocked ? 'blocked' : held ? 'held' : null;
      if (flag) members.get('guard')!.dataset.flag = flag;
      else delete members.get('guard')!.dataset.flag;
      const said = `Screened ${count(mails.length, 'email', 'emails')}. ${text ? `${text}${held ? ' for review' : ''}` : 'All clear'}.`;
      if (blocked) {
        set('guard', 'alarm', `Blocked ${blocked}`);
        say('guard', [said]);
        later(1400, () => set('guard', 'done'));
      } else {
        set('guard', 'done', held ? `Held ${held}` : 'All clear');
        if (mails.length) say('guard', [said]);
      }
    },

    /** POST /api/plan in flight: Router reads, then Planner drafts. No claims, just the pipeline. */
    planStart() {
      stop();
      work(true);
      facing = false; stage?.faceYou(false);
      hold(null);
      calm(['guard']);
      set('router', 'think', 'Reading');
      stage?.toss('you', 'router', false);
      if (!reduce.matches) say('router', ['Reading your request.'], 0);
      later(1300, () => {
        set('router', 'idle');
        set('planner', 'think', 'Drafting');
        stage?.toss('router', 'planner', false);
        if (!reduce.matches) say('planner', ['Reading the store and drafting steps.'], 0);
      });
    },

    /** The plan came back: replay what it really contains, fast. `bubble`: friendlier closing words than the server's. */
    planEnd(d: PlanData, onStep: (id: string) => void, done: () => void, bubble?: string) {
      const trace = readTrace(d.trace);
      const beats = trace ? fromTrace(trace) : derive(d);
      const t = tally(d);
      if (t) beats.splice(beats.map((b) => b.who).lastIndexOf('validator') + 1 || beats.length, 0, t);
      const appr = approvalBeat(d);
      if (appr) beats.push(appr);
      logEl.replaceChildren();
      const calls = Array.isArray(d.usage?.calls) ? d.usage!.calls.length : 0;
      logSrc.textContent = trace
        ? `From the agent trace in this response: ${count(trace.length, 'event', 'events')}.`
        : `Rebuilt from this plan response: ${count(calls, 'model call', 'model calls')}, the checks and the dry run. Times are real.`;
      calm(['guard']);
      play(beats, onStep, done, bubble ? [bubble] : undefined);
    },

    planFail(msg: string) {
      stop();
      calm(['guard']);
      set('planner', 'alarm', 'Stopped');
      say('planner', [msg]);
      later(LINGER_MS, () => work(false));
    },
    cancel() {
      stop();
      calm(['guard']);
      say('planner', ['Cancelled. Your store is unchanged.']);
      later(LINGER_MS, () => work(false));
    },

    /** A money box changed: the amber packet means money still waiting for you. */
    approval(waitingCents: number, anyApproved: boolean) {
      const li = members.get('executor')!;
      if (li.dataset.mood !== 'wait' && li.dataset.mood !== 'idle') return;
      hold(waitingCents > 0 ? true : anyApproved ? false : null);
      // Words stay short: at an 800 px stage, Judge and Executor labels have ~98 px between centres.
      set('executor', 'wait', waitingCents ? 'Waiting for you' : anyApproved ? 'Ready to run' : 'None approved');
    },

    execStart(i: number, total: number, s: Step) {
      stop();
      work(true);
      facing = false; stage?.faceYou(false);
      hold(null);
      set('executor', 'work', `Running ${i} of ${total}`);
      stage?.toss('you', 'executor', false);
      say('executor', [`Step ${i} of ${total}: ${stepTitle(s)}.`], 0);
    },
    execEnd(r: { ok: boolean; summary: string; error?: string | null }, k: number, total: number) {
      if (r.ok) {
        receiptN += 1;
        stage?.receipt(receiptN);
        set('executor', 'talk', `Done ${k} of ${total}`);
        say('executor', [clean(r.summary) || 'Done.'], 0);
        log('executor', [clean(r.summary) || 'Done.']);
        return;
      }
      if (r.error === 'invalid') {
        set('validator', 'alarm', 'Stopped it');
        set('executor', 'idle', 'Stopped');
        say('validator', [clean(r.summary) || 'Not run: it no longer passes the checks.']);
        log('validator', [clean(r.summary) || 'Not run: it no longer passes the checks.']);
      } else {
        set('executor', 'alarm', 'Failed');
        say('executor', [clean(r.summary) || 'This step failed. Nothing else ran.']);
        log('executor', [clean(r.summary) || 'This step failed. Nothing else ran.']);
      }
    },
    runEnd(allOk: boolean, done: number) {
      later(allOk ? 2600 + LINGER_MS : LINGER_MS, () => work(false));
      if (!allOk) return;
      set('executor', 'cheer', 'All done');
      say('executor', [`Run complete. ${count(done, 'step', 'steps')} done, each one in the audit log.`], 0);
      AGENT_IDS.forEach((id, i) => { if (id !== 'executor') later(90 * i, () => set(id, 'cheer')); });
      later(2600, () => AGENT_IDS.forEach((id) => set(id, 'done')));
    },

    reset() {
      stop();
      work(false);
      receiptN = 0; stage?.receipt(0);
      hold(null);
      facing = false; stage?.faceYou(false);
      members.forEach((li) => { delete li.dataset.flag; }); // the fresh inbox sets Guard's again
      for (const id of AGENT_IDS) set(id, 'idle', 'Ready');
      speech.hidden = true; speaker = null;
      logEl.replaceChildren();
      logSrc.textContent = 'Nothing yet. Ask for something and the team log fills in here.';
    },
  };
}
export type Team = ReturnType<typeof createTeam>;
