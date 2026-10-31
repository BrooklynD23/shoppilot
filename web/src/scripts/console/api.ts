// Same-origin API client. Real shapes: REPO/app/main.py. Fixture mode swaps every call.
import { fixtureCall, SCENARIOS } from './fixtures';

export interface ApiError { status: number; code: string; message: string; retry_after_s?: number }
export type Res<T> = { ok: true; data: T } | { ok: false; error: ApiError };

const param = new URLSearchParams(location.search).get('fixtures');
export const scenario: string | null = param === null ? null : SCENARIOS.includes(param) ? param : 'happy';

/** Called when a 401 no_session was healed by a fresh session (spec §4 session copy). */
export const hooks = { onFreshSession: (_s: unknown) => {} };

async function raw<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<Res<T>> {
  if (scenario) return fixtureCall<T>(scenario, method, path, body, signal);
  try {
    const res = await fetch(path, {
      method,
      credentials: 'same-origin',
      signal,
      headers: method === 'POST' ? { 'X-ShopPilot': '1', 'Content-Type': 'application/json' } : undefined,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data: unknown = null;
    try { data = await res.json(); } catch { /* empty or non-JSON body */ }
    if (res.ok) return { ok: true, data: data as T };
    const e = (data as { error?: Partial<ApiError> } | null)?.error ?? {};
    return {
      ok: false,
      error: {
        status: res.status,
        code: typeof e.code === 'string' ? e.code : res.status >= 500 ? 'internal' : 'http_error',
        message: typeof e.message === 'string' ? e.message : '',
        retry_after_s: Number.isFinite(e.retry_after_s) ? Number(e.retry_after_s) : undefined,
      },
    };
  } catch (err) {
    const aborted = (err as Error)?.name === 'AbortError';
    return { ok: false, error: { status: 0, code: aborted ? 'aborted' : 'network', message: '' } };
  }
}

/** One self-heal: a 401 no_session re-creates the session once, then retries the call. */
export async function api<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<Res<T>> {
  const r = await raw<T>(method, path, body, signal);
  if (r.ok || r.error.code !== 'no_session' || path === '/api/session') return r;
  const s = await raw('POST', '/api/session', { reset: false });
  if (!s.ok) return r;
  hooks.onFreshSession(s.data);
  return raw<T>(method, path, body, signal);
}
