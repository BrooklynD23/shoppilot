// /connect/success/: Stripe Checkout's success_url (spec 10 §12). Shows the session id Stripe
// filled into {CHECKOUT_SESSION_ID}. Not proof of payment: a real shop fulfils orders from the
// checkout.session.completed webhook (spec 10 §17).
import { ACCOUNT_ID, api, byId, explain, isOff, say } from './api';

async function start(): Promise<void> {
  const params = new URLSearchParams(location.search);
  const session = params.get('session_id') ?? '';
  const account = params.get('account') ?? '';
  byId('session-id').textContent = session || 'None in this link';
  if (!session) byId('title').textContent = 'No payment to show';
  if (!ACCOUNT_ID.test(account)) return;
  const back = byId<HTMLAnchorElement>('back');
  back.href = `/connect/store/?account=${account}`;
  // Read the shop's name for the link; this also tells us if Connect is off on this server.
  const r = await api<{ display_name: string }>('GET', `/api/connect/store/${account}`);
  if (r.ok) {
    back.textContent = `Back to ${r.data.display_name}`;
    return;
  }
  if (isOff(r.error)) byId('title').textContent = 'Connect demo is disabled';
  say(byId('notice'), explain(r.error), 'bad');
}

start();
