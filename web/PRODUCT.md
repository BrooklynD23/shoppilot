# Product

<!-- impeccable:product-schema 1 -->

Assumptions: written by a subagent from the brief and specs (no interview possible). Source: `../docs/specs/06-ui-demo.md`, `../docs/specs/00-contract-resolutions.md`, `../../research/products/03-reddit-demand-signals.md`, `../../ASSIGNMENT.md`.

## Platform

web

## Stack

Astro, static build. Output is copied into `app/static/` and served by FastAPI on the same origin. Strict CSP `script-src 'self'`: no inline scripts, no third-party script CDNs. Cookie session + `X-ShopPilot: 1` CSRF header on every POST.

## Users

1. Small-shop owners (Etsy/Shopify scale, 10 to 150 orders a week) who lose hours a day to shipping, refunds, restock and "where is my order" emails.
2. CS4680 graders who open the deployed URL, run the whole task in about 60 seconds, and score UI (10%), problem (10%), demo (30%), prompt engineering (20%).

## Product Purpose

ShopPilot+ turns one sentence ("ship yesterday's orders, email buyers tracking, restock what will run out, refund anything damaged") into a typed plan of tool calls, validates each step, shows a dry-run diff with every dollar, waits for approval before money moves, runs the approved steps, logs everything, and offers undo. Success: a grader trusts an agent with a refund because they can see and stop it.

## Positioning

An ops agent with a safety gate: plan, check, approve, run, undo. A Haiku guard screens every inbox email before the planner sees it, so a prompt-injection email is visibly BLOCKED. Forecast-backed restock (p10/p50/p90 band).

## Operating Context

Demo store "Fern & Kiln" / "Fernhill Candle Co." (seeded, fake). Stripe test mode. Emails land in an in-app Outbox, never a real inbox. Live demo 2026-11-05, 90 s script; 1 to 2 min video.

## Capabilities and Constraints

Tools: mark_shipped, send_email, forecast_demand, create_restock_po, refund_order. Plan card, validator ticks, dry-run diff with amount_cents, approve checkboxes, run log, Inbox/Outbox/Audit rail, undo, cost/cache meter. Pages: Landing, Agent console, How it works, Report + links.

## Evidence on Hand

- Quote: "I'm spending 4 or 5 hours every single day just on packing and shipping." r/ecommerce, about Feb 2025 (small spot check, 3 threads).
- Trust gap: Reddit threads on agents deleting databases with no gate or undo.
- No customers, testimonials, pricing, or benchmarks exist. Never fabricate them. Do not quote "Sunday-night cleanup takes 2 hours" (fabricated).

## Product Principles

1. Nothing moves money without a visible approval.
2. Every claim on the page is true for the demo build.
3. The grader finishes the task without navigating.
4. Hostile input is shown as text and stamped, never executed.

## Accessibility & Inclusion

WCAG AA contrast, keyboard path, status never by colour alone, prefers-reduced-motion honoured, no horizontal scroll 320 to 1920 px.
