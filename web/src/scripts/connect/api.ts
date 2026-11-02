// Same-origin fetch helper for the Stripe Connect sample (spec 10 §12). Not the console's api.ts:
// that one swaps in fixtures and re-creates demo sessions. Real shapes: app/connect/routes.py.
export interface ApiError { status: number; code: string; message: string }
export type Res<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export async function api<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<Res<T>> {
  try {
    const res = await fetch(path, {
      method,
      credentials: 'same-origin',
      // Every POST carries X-ShopPilot: 1, the app's CSRF check, and is sent as JSON.
      headers: method === 'POST' ? { 'X-ShopPilot': '1', 'Content-Type': 'application/json' } : undefined,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (res.ok) return { ok: true, data: data as T };
    const e = (data as { error?: Partial<ApiError> } | null)?.error ?? {};
    return {
      ok: false,
      error: {
        status: res.status,
        code: typeof e.code === 'string' ? e.code : 'http_error',
        message: typeof e.message === 'string' ? e.message : '',
      },
    };
  } catch {
    return { ok: false, error: { status: 0, code: 'network', message: '' } };
  }
}

// With CONNECT_ENABLED unset the server answers every /api/connect route with its normal
// "unknown route" 404 (app/connect/routes.py gate), so this is how a page tells it is off.
export function isOff(e: ApiError): boolean {
  return e.status === 404 && e.code === 'not_found' && e.message === 'Unknown API route.';
}

export function explain(e: ApiError): string {
  if (isOff(e)) return 'Connect demo is disabled on this server.';
  if (e.code === 'network') return 'Network error. Check your connection and try again.';
  return e.message || 'Something went wrong. Try again.';
}

// Stripe pages (onboarding, Checkout, billing portal) open as a top-level navigation after a
// fetch, so the CSP needs no change. Only https://stripe.com and its subdomains are followed:
// a bad response can never redirect the browser anywhere else.
export function goStripe(url: string): boolean {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  const host = u.hostname;
  if (u.protocol !== 'https:' || !(host === 'stripe.com' || host.endsWith('.stripe.com'))) return false;
  location.assign(u.href);
  return true;
}

export function money(cents: number, currency = 'usd'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency.toUpperCase() }).format(cents / 100);
}

// Disable a button while its request runs, so a double click can't send it twice.
export async function busy<T>(button: HTMLButtonElement, run: () => Promise<T>): Promise<T> {
  button.disabled = true;
  try {
    return await run();
  } finally {
    button.disabled = false;
  }
}

export const byId = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

export function say(el: HTMLElement, text: string, tone: 'info' | 'bad' = 'info'): void {
  el.textContent = text;
  el.dataset.tone = tone;
}

export const ACCOUNT_ID = /^acct_[A-Za-z0-9]{8,64}$/; // same rule as the server

export interface Product { id: string; name: string; description: string | null; unit_amount: number; currency: string }
export interface Shop { account_id: string; display_name: string; products: Product[] }

// Product names and descriptions are public user input: textContent only, never innerHTML.
export function productCard(p: Product): HTMLLIElement {
  const li = document.createElement('li');
  li.className = 'cx-product';
  const name = document.createElement('h3');
  name.textContent = p.name;
  const price = document.createElement('p');
  price.className = 'cx-price';
  price.textContent = money(p.unit_amount, p.currency);
  li.append(name);
  if (p.description) {
    const desc = document.createElement('p');
    desc.textContent = p.description;
    li.append(desc);
  }
  li.append(price);
  return li;
}
