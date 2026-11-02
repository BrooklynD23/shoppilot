// /connect/ dashboard (spec 10 §12): create an account, onboard, add products, plan, events.
// Status is read live from Stripe on every load (the server never stores it).
// Every value from the API or Stripe is set with textContent, never innerHTML.
import { api, busy, byId, explain, goStripe, money, productCard, say, type ApiError, type Shop } from './api';

interface Plan {
  status: string;
  price_id: string;
  quantity: number;
  cancel_at_period_end: boolean;
  paused: boolean;
  has_pro: boolean;
}
interface ConnectAccount {
  id: string;
  display_name: string | null;
  card_payments_status: string | null;
  requirements_status: string | null;
  ready_to_process_payments: boolean;
  onboarding_complete: boolean;
  products_created: number;
  product_limit: number;
  plan: Plan | null;
  storefront_path: string;
  events: { type: string; received_at: string }[];
}
interface AccountView { account: ConnectAccount | null; fee_cents: number; plan_available: boolean }

// Statuses that count as "has a plan to manage" (app/connect/stripe_calls.py OPEN).
const OPEN = ['active', 'trialing', 'past_due', 'unpaid', 'incomplete', 'paused'];
const SECTIONS = ['account', 'products', 'plan', 'events'];
const notice = byId('notice');
let feeCents = 123;

const words = (s: string | null, none: string) => (s ? s.replaceAll('_', ' ') : none);
const report = (e: ApiError) => say(notice, explain(e), 'bad');

function show(id: string, on: boolean): void {
  byId(id).hidden = !on;
}

function renderAccount(a: ConnectAccount): void {
  byId('acct-id').textContent = a.id;
  byId('acct-name').textContent = a.display_name ?? '';
  // Status is a word and a dot, never colour alone.
  const pay = byId('pill-pay');
  const payKind = a.ready_to_process_payments ? 'done' : a.card_payments_status === 'pending' ? 'running' : 'failed';
  pay.className = `pill pill--${payKind}`;
  pay.textContent = words(a.card_payments_status, 'not requested');
  const onb = byId('pill-onb');
  const onbKind = a.onboarding_complete ? 'done' : a.requirements_status === 'past_due' ? 'failed' : 'running';
  onb.className = `pill pill--${onbKind}`;
  onb.textContent = a.onboarding_complete ? 'complete' : words(a.requirements_status, 'not started');
  // The button stays until the account can take payments and nothing is due (brief).
  show('onboard', !(a.ready_to_process_payments && a.onboarding_complete));
}

function renderProducts(a: ConnectAccount, shop: Shop | null): void {
  byId('product-count').textContent =
    `${a.products_created} of ${a.product_limit} products used on your plan. Prices must be above the ${money(feeCents)} platform fee.`;
  byId<HTMLAnchorElement>('storefront-link').href = a.storefront_path;
  byId('product-list').replaceChildren(...(shop?.products ?? []).map(productCard));
}

function renderPlan(view: AccountView, a: ConnectAccount): void {
  const p = a.plan;
  let text: string;
  if (p) {
    text = `Status: ${words(p.status, '')}.`;
    if (p.paused) text += ' Payments are paused.';
    if (p.cancel_at_period_end) text += ' Cancels at the end of the billing period.';
    text += p.has_pro ? ' Pro is on: up to 20 products.' : ' Pro is off: up to 3 products.';
  } else if (view.plan_available) {
    text = 'No plan yet. ShopPilot+ Pro raises your product limit from 3 to 20.';
  } else {
    text = 'The platform plan is not set up on this server (STRIPE_PLATFORM_PRICE_ID).';
  }
  byId('plan-status').textContent = text;
  show('subscribe', view.plan_available && !(p && OPEN.includes(p.status)));
  show('manage', p !== null);
}

function renderEvents(a: ConnectAccount): void {
  const items = a.events.map((e) => {
    const li = document.createElement('li');
    const type = document.createElement('code');
    type.textContent = e.type;
    const time = document.createElement('time');
    time.dateTime = e.received_at;
    time.textContent = new Date(e.received_at).toLocaleString();
    li.append(type, time);
    return li;
  });
  byId('event-list').replaceChildren(...items);
  show('events-empty', items.length === 0);
}

async function load(): Promise<void> {
  const r = await api<AccountView>('GET', '/api/connect/account');
  if (!r.ok) {
    report(r.error); // includes "Connect demo is disabled on this server." when the flag is off
    return;
  }
  if (notice.textContent === 'Loading') say(notice, '');
  feeCents = r.data.fee_cents;
  const a = r.data.account;
  show('create', a === null);
  for (const id of SECTIONS) show(id, a !== null);
  if (!a) return;
  renderAccount(a);
  renderPlan(r.data, a);
  renderEvents(a);
  renderProducts(a, null);
  const shop = await api<Shop>('GET', `/api/connect/store/${encodeURIComponent(a.id)}`);
  if (shop.ok) renderProducts(a, shop.data);
}

// Ask the server for a Stripe URL, then go there (onboarding, Checkout, billing portal).
async function toStripe(button: HTMLButtonElement, path: string): Promise<void> {
  const r = await busy(button, () => api<{ url: string }>('POST', path));
  if (!r.ok) return report(r.error);
  if (!goStripe(r.data.url)) say(notice, 'Stripe sent back an unexpected link. Try again.', 'bad');
}

const onboardBtn = byId<HTMLButtonElement>('onboard');
onboardBtn.addEventListener('click', () => toStripe(onboardBtn, '/api/connect/onboard'));
const subscribeBtn = byId<HTMLButtonElement>('subscribe');
subscribeBtn.addEventListener('click', () => toStripe(subscribeBtn, '/api/connect/subscribe'));
const manageBtn = byId<HTMLButtonElement>('manage');
manageBtn.addEventListener('click', () => toStripe(manageBtn, '/api/connect/portal'));
const refreshBtn = byId<HTMLButtonElement>('refresh');
refreshBtn.addEventListener('click', () => busy(refreshBtn, load));

// Forms post with fetch (never a native form post): every POST must carry X-ShopPilot.
byId<HTMLFormElement>('create-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const form = ev.currentTarget as HTMLFormElement;
  const data = new FormData(form);
  const body = {
    display_name: String(data.get('display_name') ?? '').trim(),
    contact_email: String(data.get('contact_email') ?? '').trim(),
  };
  const r = await busy(form.querySelector('button')!, () =>
    api<{ account_id: string; created: boolean }>('POST', '/api/connect/accounts', body),
  );
  if (!r.ok) return report(r.error);
  say(notice, r.data.created ? 'Account created. Next: onboard to collect payments.' : 'This browser already has an account.');
  await load();
});

byId<HTMLFormElement>('product-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const form = ev.currentTarget as HTMLFormElement;
  const data = new FormData(form);
  const priceCents = Math.round(Number(data.get('price')) * 100); // dollars in, cents out
  if (!(priceCents > feeCents)) {
    say(notice, `Set a price above the ${money(feeCents)} platform fee.`, 'bad');
    return;
  }
  const body = {
    name: String(data.get('name') ?? '').trim(),
    description: String(data.get('description') ?? '').trim(),
    price_cents: priceCents,
    currency: String(data.get('currency') ?? 'usd'),
  };
  const r = await busy(form.querySelector('button')!, () =>
    api<{ id: string; products_created: number; product_limit: number }>('POST', '/api/connect/products', body),
  );
  if (!r.ok) return report(r.error);
  form.reset();
  say(notice, `Product created. ${r.data.products_created} of ${r.data.product_limit} used.`);
  await load();
});

async function start(): Promise<void> {
  const params = new URLSearchParams(location.search);
  // Drop the parameters first, so a reload never repeats what they asked for.
  if (location.search) history.replaceState(null, '', location.pathname);
  if (params.get('subscribed') === '1') {
    say(notice, "Checkout finished. Your plan updates here when Stripe's webhook arrives. Use Refresh status.");
  } else if (params.has('accountId')) {
    say(notice, 'Back from Stripe. The status below is live.');
  }
  await load();
  if (params.get('refresh') === '1') {
    // Stripe sends people here when an onboarding link expired or was already used.
    say(notice, 'That onboarding link expired. Opening a fresh one.');
    await toStripe(onboardBtn, '/api/connect/onboard');
  }
}

start();
