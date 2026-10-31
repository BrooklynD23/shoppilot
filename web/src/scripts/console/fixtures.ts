// ?fixtures=<scenario>: every API call is answered from /fixtures/*.json (real response shapes,
// generated from the real FastAPI routes). 300 ms latency. In-memory state only.
import type { Res } from './api';

export const SCENARIOS = ['happy', 'invalid', 'clarify', 'ratelimit', 'llmdown', 'fail', 'slow', 'empty', 'mock'];
const LATENCY_MS = 300;
const SLOW_MS = 14000;

const files = new Map<string, Promise<unknown>>();
const load = (name: string): Promise<any> => {
  if (!files.has(name)) files.set(name, fetch(`/fixtures/${name}.json`).then((r) => r.json()));
  return files.get(name)!.then((d) => structuredClone(d));
};

const mem = { ran: false, planCalls: 0, failed: false, undone: new Map<string, string>() };

function wait(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('aborted', 'AbortError'));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('aborted', 'AbortError')); }, { once: true });
  });
}

const ok = <T>(data: unknown): Res<T> => ({ ok: true, data: data as T });
const fail = async <T>(name: string, status: number): Promise<Res<T>> => {
  const body = await load(name);
  return { ok: false, error: { status, ...body.error } };
};

async function plan<T>(sc: string, body: { request?: string; replay?: boolean }, signal?: AbortSignal): Promise<Res<T>> {
  mem.planCalls += 1;
  if (sc === 'slow' && !body.replay) await wait(SLOW_MS, signal);
  if (sc === 'ratelimit' && !body.replay) return fail('error-429', 429);
  if (sc === 'llmdown' && !body.replay) return ok(await load('plan-llmdown'));
  const name = sc === 'invalid' ? 'plan-invalid'
    : sc === 'empty' ? 'plan-empty'
    : sc === 'clarify' && mem.planCalls === 1 ? 'plan-clarify'
    : 'plan';
  const p = await load(name);
  p.source = p.plan.source = body.replay ? 'replay' : 'live';
  if (body.request) p.plan.request = body.request;
  return ok(p);
}

async function audit() {
  const a = await load(mem.ran ? 'audit-after' : 'audit');
  a.actions = a.actions.map((x: any) => {
    const at = mem.undone.get(x.id);
    return at ? { ...x, can_undo: false, undone: true, undone_at: at } : x;
  });
  return a;
}

export async function fixtureCall<T>(sc: string, method: string, path: string, body?: any, signal?: AbortSignal): Promise<Res<T>> {
  try {
    await wait(LATENCY_MS, signal);
    if (path === '/api/session') {
      if (body?.reset) Object.assign(mem, { ran: false, planCalls: 0, failed: false, undone: new Map() });
      const s = await load('session');
      return ok(sc === 'mock' ? { ...s, llm_mode: 'mock' } : s);
    }
    if (path === '/api/store') {
      const s = await load('store');
      return ok(sc === 'mock' ? { ...s, llm_mode: 'mock' } : s);
    }
    if (path === '/api/inbox') return ok(await load('inbox'));
    if (path === '/api/outbox') return ok(await load(mem.ran ? 'outbox-after' : 'outbox'));
    if (path === '/api/audit') return ok(await audit());
    if (path === '/api/plan' && method === 'POST') return await plan<T>(sc, body ?? {}, signal); // await: keep aborts inside this try
    if (path === '/api/execute' && method === 'POST') {
      const id = body?.approved_step_ids?.[0];
      if (sc === 'fail' && id === 's2' && !mem.failed) {
        mem.failed = true; // fail once, so "Retry from here" succeeds
        return ok(await load('execute-fail'));
      }
      const all = await load('execute');
      if (!all[id]) return fail('error-replay-miss', 404);
      mem.ran = true;
      return ok(all[id]);
    }
    const undo = path.match(/^\/api\/undo\/(aud_[0-9a-f]{12})$/);
    if (undo && method === 'POST') {
      const a = await audit();
      const row = a.actions.find((x: any) => x.id === undo[1]);
      if (row?.tool === 'refund_order') return { ok: false, error: { status: 409, ...(await load('undo-refund')).error } };
      if (!row?.can_undo) return { ok: false, error: { status: 409, code: 'already_undone', message: 'This action was already undone.' } };
      mem.undone.set(undo[1], new Date().toISOString().slice(0, 19) + 'Z');
      return ok(await load('undo'));
    }
    return { ok: false, error: { status: 404, code: 'not_found', message: 'Not in fixtures.' } };
  } catch (err) {
    const aborted = (err as Error)?.name === 'AbortError';
    return { ok: false, error: { status: 0, code: aborted ? 'aborted' : 'network', message: '' } };
  }
}
