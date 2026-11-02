# ShopPilot+

Agentic store-ops assistant (stub).

## Stripe Connect sample (optional, sandbox only)

A separate Stripe Connect integration at `/connect/`: create a connected account (Accounts v2), onboard, add products, sell them from a storefront with a platform fee, and subscribe to a platform plan. It is off unless `CONNECT_ENABLED=1`; when off, every `/api/connect/*` route returns 404 and the demo is unchanged. Code: `app/connect/`. Setup and test steps: `docs/connect-setup.md`. Design: `docs/specs/10-stripe-connect.md`.

## Known limits

- Image size and idle RSS: not yet measured (no Docker locally; CI builds the image).
