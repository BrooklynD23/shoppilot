// /connect/store/?account=acct_...: the storefront (spec 10 §12). Public: shoppers need no cookie.
// Demo: the shop is picked by its Stripe account ID (the brief allows this). In production use
// your own shop slug or ID in the URL, not the Stripe account ID.
import { ACCOUNT_ID, api, busy, byId, explain, goStripe, productCard, say, type Shop } from './api';

const notice = byId('notice');
const title = byId('shop-name');
const account = new URLSearchParams(location.search).get('account') ?? '';

// Buy: the server reads the price from Stripe and opens a hosted Checkout (a direct charge on
// the shop's account, with the platform fee), then the browser goes there.
async function buy(productId: string, button: HTMLButtonElement): Promise<void> {
  const body = { account_id: account, product_id: productId, quantity: 1 };
  const r = await busy(button, () => api<{ url: string }>('POST', '/api/connect/checkout', body));
  if (!r.ok) return say(notice, explain(r.error), 'bad');
  if (!goStripe(r.data.url)) say(notice, 'Stripe sent back an unexpected link. Try again.', 'bad');
}

async function load(): Promise<void> {
  if (!ACCOUNT_ID.test(account)) {
    title.textContent = 'No shop picked';
    say(notice, 'Open the storefront from the Connect dashboard.', 'bad');
    return;
  }
  const r = await api<Shop>('GET', `/api/connect/store/${account}`);
  if (!r.ok) {
    title.textContent = 'Shop unavailable';
    say(notice, explain(r.error), 'bad');
    return;
  }
  title.textContent = r.data.display_name;
  if (!r.data.products.length) say(notice, 'No products yet. The shop owner adds them on the dashboard.');
  const cards = r.data.products.map((p) => {
    const li = productCard(p);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-line btn-sm';
    button.textContent = 'Buy';
    button.setAttribute('aria-label', `Buy ${p.name}`);
    button.addEventListener('click', () => buy(p.id, button));
    li.append(button);
    return li;
  });
  byId('product-list').replaceChildren(...cards);
}

load();
