# Stripe Connect integration brief (user-provided, 2026-11-02, binding)

Saved verbatim from the user's request; table cell padding was collapsed, wording unchanged. User context: "We're currently running on Sandbox with a test user account. Connect to Stripe and setup the environment, that way we can retrieve the relevant information in our dev locally on this machine, then test it on Render."

---

I am adding a Stripe Connect integration to my application. Please create a sample integration and add detailed code comments explaining each step. If a value needs to be filled in (like an API key), please mark it with a placeholder comment and provide a helpful error if the value is not present.

The sample integration should onboard users to Connect, create products, and have a simple storefront for their customers to make purchases.

For any UI, please use clean, simple HTML with basic styling. If relevant, use the current style of my application.

The latest version of the Stripe API is `2026-10-28.endive` but this will be used automatically by the SDK.

Use the latest version of the SDK package. You can find the latest version of the SDK package at https://github.com/stripe/stripe-$LANG/releases.

Please set up flows for the following:

## Use a "Stripe Client" for all requests

```python
stripeClient = StripeClient("sk_***")
```

use the `stripeClient` for all stripe related requests.

The stripe version does not need to be set since it will be used automatically by the SDK.

## Creating Connected Accounts
When creating connected accounts, use the V2 API with the following properties:

```js
const account = await stripeClient.v2.core.accounts.create({
  display_name: {From User},
  contact_email: {From User},
  identity: {
    country: 'us',
  },
  dashboard: 'full',
  defaults: {
      responsibilities: {
        fees_collector: 'stripe',
        losses_collector: 'stripe',
      },
   },
  configuration: {
    customer: {},
    merchant: {
       capabilities: {
         card_payments: {
           requested: true,
         },
       },
    },
  },
});
```

Only use the above properties when creating accounts. Never pass type at the top level. **Do not use top level type: 'express' or type: 'standard' or type 'custom'.**

If there is a DB already setup, store a mapping from the user object to the account ID.

The full V2 object can be seen at https://docs.stripe.com/api/v2/core/accounts/object

## Onboarding Connected Accounts

Onboard the connected accounts using Stripe Account Links.
Please make a UI where the user can click "Onboard to collect payments" and also see the current status of onboarding. You should use the accounts API directly to get the status of the account. For this demo, always get the account status from the API directly (Do not store in a database).

Use the V2 account links API to create an account link:

```js
const accountLink = await stripeClient.v2.core.accountLinks.create({
  account: accountId,
  use_case: {
    type: 'account_onboarding',
    account_onboarding: {
      configurations: ['merchant', 'customer'],
      refresh_url: 'https://example.com',
      return_url: `https://example.com?accountId=${accountId}`,
    },
  },
});
```

(This is just an example, code could be different depending on programming language.)
```js
const account = await stripeClient.v2.core.accounts.retrieve(stripeAccountId, {
  include: ["configuration.merchant", "requirements"],
});

const readyToProcessPayments = account?.configuration
?.merchant?.capabilities?.card_payments?.status === "active"
const requirementsStatus =
      account.requirements?.summary?.minimum_deadline?.status;
const onboardingComplete = requirementsStatus !== "currently_due" && requirementsStatus !== "past_due";
```

## Listen for requirements changes on your connected account

Account requirements can change, often due to changes implemented by financial regulators, card networks, and other financial institutions. To set up webhook notifications of requirement changes, create an event destination to listen for Account v2 update events.

1. In your [Stripe Dashboard](https://dashboard.stripe.com), open the Developers menu by clicking **Developers** in the navigation menu footer, then select **Webhooks**.
1. Click **+ Add destination**.
1. In the Events from section, select **Connected accounts**.
1. Select **Show advanced options**. In the Payload style section, select **Thin**.
1. In the Events field, type "v2" to search for v2 event types. Select **v2.account[requirements].updated** and the **v2.account[configuration.configuration_type].capability_status_updated** type for each configuration type used by your connected accounts.

Configure your application to respond to update events by collecting any updated requirements.

Use the following docs to help you parse 'thin' events. You must use thin events for V2 accounts: https://docs.stripe.com/webhooks.md?snapshot-or-thin=thin

You can start a local listener by using the Stripe CLI: https://docs.stripe.com/cli/listen

```bash
stripe listen --thin-events 'v2.core.account[requirements].updated,v2.core.account[.recipient].capability_status_updated,v2.core.account[configuration.merchant].capability_status_updated,v2.core.account[configuration.customer].capability_status_updated' --forward-thin-to <YOUR_LOCAL_ENDPOINT>
```

### Sample code for parsing 'thin' events

```js
const thinEvent = client.parseThinEvent(req.body, sig, webhookSecret);

// Fetch the event data to understand the failure
const event = await client.v2.core.events.retrieve(thinEvent.id);

// Use event.type to determine which event to handle
```

setup handlers for each event type.

## Create Products
Please set up a sample endpoint and user interface to create Stripe products. This should use the `Stripe-Account` header to create products on the connected account.

```
stripeClient.products.create({
    name: name,
    description: description,
    default_price_data: {
        unit_amount: priceInCents,
        currency: currency,
    },
}, {
    stripeAccount: accountId, // Use stripeAccount for the Stripe-Account header
});
```

## Display Products

Please create a sample UI (a storefront) that displays the products and allows a connected account's customers to buy a product. There should be one page per connected account (you can use the connected account's ID in the URL, but add a comment telling the user they should use a different identifier in the future).

Make sure to use the connected account header when retrieving products.

```
stripeClient.products.list({
    limit: 20,
    active: true,
    expand: ['data.default_price'],
}, {
    stripeAccount: accountId,
});
```

## Process Charges to connected account

Use a Direct Charge with an application fee to monetize the transaction.

Use hosted checkout for simplicity.

```
stripeClient.checkout.sessions.create(
  {
    line_items: [
      {
        price_data: <Price Data>
        quantity: <Quantity>,
      },
    ],
    payment_intent_data:  {
      // Sample Application Fee
      application_fee_amount: 123,
    },
    mode: 'payment',
    success_url: '<Root URL>/success?session_id={CHECKOUT_SESSION_ID}',
  },
  {
    stripeAccount: <Connected Account ID>,
  }
)
```

Python connected-account header:

```python
stripeClient = StripeClient("sk_***")

products = stripeClient.v1.products.list(
  {"limit": 5},
  {"stripe_account": '{{CONNECTED_ACCOUNT_ID}}'},
)
```

Make sure to use the Stripe Client for all requests.

## Charge subscription to Connected Account
### Create and charge the subscription
We want to charge a subscription to the connected account. With V2 accounts we can use one ID for both the customer and the connected account.

If you have access to tools, create an example subscription at the platform level. If you don't have access add a placeholder ID.

Add some basic UI on the users dashboard that will allow a connected account to subscribe.

You can create the subscription using a hosted checkout. Use the following code
```
stripe.checkout.sessions.create({
      customer_account: "acct_..." (The connected account ID),
      mode: 'subscription',
      line_items: [
        { price: process.env.PRICE_ID, quantity: 1 },
      ],
      success_url: <SUCCESS_URL>?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: <CANCEL_URL>,
    });
```

### Add a billing portal
Add a billing portal where the user can manage their subscription.
```
const session = await stripe.billingPortal.sessions.create({
  customer_account: '{{Connected account ID}}',
  return_url: '{{Dashboard URL}}',
});
```

### Webhooks
Listen to webhooks [Server-side]. When subscriptions are upgraded, downgraded, or canceled, make sure customers receive only the products or services they're actively subscribed to. Stripe also sends notifications if an invoice is paid. In the Event object, look at the ID for the subscription or the customer to determine which customer the event applies to. Use https://docs.stripe.com/webhooks.md to get started.

Setup webhooks for subscriptions and store the users subscription status in the database if one is setup. If one is not setup add TODO's of where the DB should be written to.

These webhooks do not use thin events.

| Event | Description |
|---|---|
| customer.subscription.updated | Monitor upgrades and downgrades: check `subscription.items.data[0].price` and grant or revoke access. With a trial, switching price in the portal ends the trial immediately. |
| customer.subscription.updated | Monitor quantity changes: check `subscription.items.data[0].quantity` and grant access to the new quantity. |
| customer.subscription.deleted | Monitor cancellations and revoke access. If the portal cancels at period end, watch `customer.subscription.updated` for `cancel_at_period_end`; `false` again means the customer reactivated. |
| customer.subscription.updated | Paused collection: empty `subscription.pause_collection` means resumed; otherwise `pause_collection.resumes_at` says when; `pause_collection.behavior` is always `'void'` when paused from the portal. |
| payment_method.attached | A customer adds a payment method. |
| payment_method.detached | A customer removes a payment method. |
| customer.updated | Check `invoice_settings.default_payment_method` for a new default; check the subscription's `default_payment_method` override. Treat as billing-information changes only; never use the billing email as a login credential. |
| customer.tax_id.created | Customers manage tax IDs (see the tax IDs guide). |
| customer.tax_id.deleted | Customers manage tax IDs. |
| customer.tax_id.updated | Tax ID validation updates. |
| billing_portal.configuration.created | A portal configuration is created. |
| billing_portal.configuration.updated | A portal configuration is updated. |
| billing_portal.session.created | A portal session is created. |

## General Tips
Do not use .customer id's for V2 accounts; you can get the ID from .customer_account.

```
// This will have shape acct_
account_id = subscription.customer_account
```
When in doubt reference the stripe docs.
