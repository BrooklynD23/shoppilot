# ShopPilot+ frontend: 5 new approaches (2026-10-30)

Synthesis of `01-similar-products.md` (21 products, 8 landing teardowns), `02-motion-tools.md` (Higgsfield and motion tools) and `03-design-audit.md` (why Carton, Label and Build Book fail; skills; 70 DESIGN.md references). Those three files hold the evidence and every source URL.

## What every approach shares (non-negotiable)

1. **Two surfaces.** `/` is a landing page that persuades. `/app` is the console that does the work. They are never mixed in one view (ui-unified mode split). `/how-it-works` and `/report` are secondary pages, linked from the footer and the nav.
2. **Product-first hero.** The real plan card is the hero: steps, a $ dry-run, Approve, Undo. No metaphor costume (box, label, manual).
3. **Positioning:** *"Safe autopilot for your shop: see every dollar before it moves."* No competitor leads with approve-every-dollar plus undo (`01` §4). Shopify's own Aug 2026 security guide names the fear: an agent manipulated into a $500 refund.
4. **Honesty floor.** No fake logos, testimonials or metrics. Proof is real: the live demo, measured cost per run, injections blocked in the eval set, ML backtest error, and the one labelled Reddit quote ("4 or 5 hours every single day"). Seeded numbers are labelled "Demo store".
5. **Hero limits:** headline of 2 lines or fewer, subhead of 20 words or fewer, one primary CTA, "Try the live demo", which needs no signup and runs replay mode, so it costs $0 in LLM fees.
6. **CSP-safe:** self-hosted fonts, video and JS only. No Arcade, Supademo or Spline embeds; export them to MP4 instead.

## The 5 approaches

| # | Name | Hero | Steal from | Motion | $ | Build effort | Risk |
|---|---|---|---|---|---|---|---|
| 1 | **Approval-first, Stripe-clean** | Real plan card ticks through steps 1→5 and stops on "$24.00 awaiting approval"; Approve glows | stripe.com (layout, tabular $), cursor.com (state pills), linear.app (product sells, one accent), lindy.ai (approval buttons in hero) | One CSS sequence, ~2 s, reduced-motion = static final state | $0 | Low (1 day) | Looks familiar; needs sharp copy to stand out |
| 2 | **The demo *is* the landing** | A working request box with 3 prompt chips; the visitor clicks one and watches a real plan build (replay), then approves it, all above the fold | shopify.com/sidekick (prompt gallery), cursor.com (interactive hero), tidio.com (live demo CTA) | Real UI state changes only | $0 (replay) | Medium (needs `/api/plan` replay ready by 11-01) | Hero depends on the backend; latency hidden by replay |
| 3 | **One Sunday night, scroll story** | Headline over a quiet inbox; scrolling plays one story: inbox fills → plan → injection blocked → approve → "done in 90 s" | siena.cx (one story end to end), n8n.io (refund + approval flow), attio.com (input → agent → result split) | CSS scroll-driven animations (~88% support; static fallback) | $0 | Medium-high (2 days) | Scroll-jacking feel if overdone; Safari fallback must be solid |
| 4 | **Cinematic hero + product film** | 6–8 s AI-generated mood loop (a shop owner's desk at night, lights going off) behind the headline; below it a 30 s OBS recording of the real console | runwayml.com / Google Flow (Veo 3.1) for the loop; linear.app, raycast.com for the film framing | Video (≤1.5 MB hero, ≤5 MB film on click), poster + pause button | $0 (Google AI Pro student offer) to $19.99; Higgsfield not worth it (0 free credits, 720p on Starter) | Medium | Generic "AI video" look; bandwidth on Render free (5 GB/mo); must be labelled AI-generated |
| 5 | **Trust ledger, safety-first** | Split hero: left "Every dollar previewed. Every action undoable."; right the dry-run diff + audit receipt. Below: "Try to trick it" box where a visitor pastes an attack and sees it blocked live | ramp.com (AI + money + policy controls), lindy.ai ("Nothing irreversible happens without your approval"), yuma.ai (hard refund limits), shopify.com/blog/agentic-ai-security | CSS stamp/slide on the BLOCKED verdict | ~$0.0001 per guard check (Haiku); capped by budgets | Medium (needs a guard-only endpoint; resolves open question Q11) | Leads with fear; must still show the time saved |

## Recommendation: 2 + 1, framed by 5

- **Skin = Approach 1** (Stripe + Cursor + Linear blend, light theme for the projector).
- **Hero = Approach 2**: the visitor can run the real thing without signing up. It sells to customers and it is the 30% live-demo grade in one element.
- **Copy and second section = Approach 5**: the approve-every-dollar promise, the audit receipt, and the blocked injection with its reason.
- **Add Approach 4's product film only** (a real OBS recording, not AI video) if time remains after the 2026-11-02 freeze. It doubles as the 1–2 min demo video.

Landing section order: Hero (live demo) → three proof numbers (measured) → "How a request runs" (plan, check, approve, undo) → Safety (blocked injection, policy caps, audit) → Forecast + anomalies → FAQ / honest limits → final CTA → footer (repo, video, report, course note).

## Getting people to look (6-day, $0 plan)

| Channel | Action | When |
|---|---|---|
| Demo video | 60–90 s cut of the live demo, YouTube unlisted → public | 11-03 |
| Product Hunt "coming soon" / Show HN draft | Post after the demo with the live URL; honest "student startup simulation" note | after 11-05 |
| r/shopify, r/ecommerce | Ask for feedback on the approve-every-dollar idea, not a sales post; check each subreddit's self-promotion rules first | 11-04 |
| LinkedIn / X | Short clip of the injection being blocked (the most shareable moment) | 11-04 |
| Shopify dev forum thread on refund guardrails (`01` link 10) | Reply with what we built and the eval numbers, only if the thread rules allow it | after 11-05 |

Each of these posts publicly under a team member's name. Get team approval before posting anything.

## Decisions needed

1. Which approach (or the recommended 2 + 1 + 5 blend)?
2. Pricing section: none, or "planned pricing" clearly labelled as part of the simulation?
3. Approve the `/` landing and `/app` console split (overrides spec 06 §0/§1)?
4. Try the Google AI Pro student offer for a Veo hero loop (Approach 4), yes or no?

## User decisions (2026-10-30)

1. Mock up **all 5** approaches, plus a **6th**: the recommended blend (Approach 1 skin + Approach 2 live-demo hero + Approach 5 copy and safety section + Approach 4 product film if time allows). The user picks after seeing all 6 on localhost.
2. **Planned pricing**, clearly labelled as part of the startup simulation.
3. **Yes** to the split: `/` landing, `/app` console (overrides spec 06 §0/§1).
4. **Yes** to trying the Google AI Pro student offer for a Veo hero loop (a human generates the clip; agents write the prompts).
