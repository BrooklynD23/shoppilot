# 01 — Similar products and how their landing pages win customers

Research date: **2026-10-30**. Every URL below was fetched on 2026-10-30 unless it is marked otherwise.
Method: WebFetch (text extraction) and WebSearch. Text extraction cannot see images or motion, so "hero visual" comes from alt text, filenames, and page copy. Where the visual could not be confirmed, the table says so.

**Bottom line:** every close competitor sells **"AI that does the work"**. None leads with **"you approve every dollar before it moves."** Safety copy is buried below the fold, written as a compliance badge list. ShopPilot+ can own the hero itself: **a dry-run preview with $ amounts and an Approve button**.

---

## 1. Landscape (21 checked, 20 live, 1 dropped)

| # | Product | Category | URL | Status (2026-10-30) | Closest overlap with ShopPilot+ |
|---|---------|----------|-----|---------------------|-------------------------------|
| 1 | Shopify Sidekick | (a) e-com copilot | https://www.shopify.com/sidekick | Live. `/magic` now serves the Sidekick page | Plain-English requests that "take action in your admin"; stages changes as a draft for review |
| 2 | Gorgias AI Agent | (a) e-com CX agent | https://www.gorgias.com/ | Live. `/ai-agent` gave no body text, `/products/ai-agent` returned 404 | Shopify actions, "built-in guardrails", escalation |
| 3 | Siena AI | (a) e-com CX agent | https://www.siena.cx/ | Live | Hero demo shows the agent **refunding the difference** |
| 4 | Yuma AI | (a) e-com CX agent | https://www.yuma.ai/ | Live | **Hard limits on refunds/discounts**, review before automation expands |
| 5 | Rep AI | (a) e-com sales/support agent | https://www.hellorep.ai/ | Live. `rep.ai` returned 404 | Shopify-only; risk-reversal guarantee |
| 6 | Tidio Lyro | (a) SMB support agent | https://www.tidio.com/lyro/ | Live | SMB pricing, handoff rules, "no credit card" |
| 7 | Intercom Fin | (a) support agent | https://fin.ai/ (redirect from intercom.com/fin) | Live | Spending limits and alerts on outcome pricing; testing suite |
| 8 | Macha | (a) helpdesk refund agent | https://www.getmacha.com/blog/automating-shopify-refunds-safely-ai-confirmation | Live (blog dated 2026-07-23, updated 2026-09-28) | **Confirmation card before a real refund**: the nearest feature twin |
| 9 | Prediko | (b) inventory forecasting | https://www.prediko.io/ | Live | Demand forecast + purchase orders for Shopify |
| 10 | Inventory Planner (by Sage) | (b) inventory forecasting | https://www.inventory-planner.com/ | Live, now Sage-owned | Forecast-driven restock |
| 11 | Fabrikator | (b) inventory for SMB | https://www.fabrikator.io/ | Live (© 2026) | "Restock on time. Prevent stockouts." |
| 12 | ~~Cogsy~~ | (b) inventory | https://www.cogsy.com/ → https://mayple.ai/cogsy | **DEAD**: "Cogsy has been discontinued" | Dropped |
| 13 | Lindy | (c) general AI employee | https://www.lindy.ai/ | Live | **"Nothing irreversible happens without your approval."** Hero shows a "Refund the duplicate" button |
| 14 | n8n | (c) workflow + agents | https://n8n.io/ | Live | **Hero workflow = refund request → Slack approval → refund** |
| 15 | Zapier Agents | (c) general agents | https://zapier.com/agents | Live | Plain-English agents across 9,000+ apps; no approval copy |
| 16 | Relevance AI | (c) AI workforce | https://www.relevanceai.com/ | Live ("Invent 2.0") | L1–L4 autonomy framework, HITL approvals |
| 17 | Decagon | (c) enterprise CX agent | https://decagon.ai/ | Live | Action bubbles in the hero ("I've applied your membership perks.") |
| 18 | Sierra | (c) enterprise CX agent | https://sierra.ai/ | Live | Trust section with a certification wall |
| 19 | Manus | (c) general agent | https://manus.im/ | Live ("Manus 2.0") | Prompt-box-as-hero |
| 20 | gotoHuman | (d) HITL approvals | https://www.gotohuman.com/ | Live | "Custom human reviews to approve and edit any action" |
| 21 | HumanLayer | (d) HITL, **pivoted** | https://www.humanlayer.dev/ | Live but now a coding-agent IDE | "Every phase is a place to push back"; no longer an approvals API |

Adjacent reference (not a competitor): **Ramp** https://ramp.com/ is the best example of selling *AI + money + policy controls* ("Policy Agents", approval thresholds).

---

## 2. The 8 best landing pages, dissected

### 2.1 Lindy — https://www.lindy.ai/
| Field | Value |
|---|---|
| Hero headline | "Hire Lindy, get it done." |
| Subhead | "Lindy is the AI employee that plugs into your tools, learns how you work, and takes real work off your plate." |
| Primary CTA | "Try for free" (closing: "Start with $50 in free credits.") |
| Hero visual | **Live product UI**: a Slack-style #growth channel. A teammate @mentions Lindy, Lindy replies with completed steps (each tagged with a tool logo), then a result card with action buttons ("Pause the campaign", "Refund the duplicate") |
| Social proof | G2 4.9; logo wall (Shopify, NVIDIA, Airbnb, Stanford…); "Wall of love" testimonials |
| Trust/approval | "Security by design" section: Compliant / Private / **In your control: "Nothing irreversible happens without your approval."** FAQ: write/send actions can wait for approval; SOC 2 Type II, GDPR, HIPAA |
| Section order | Nav → Hero + demo → Logo wall → "Why Lindy feels like a real teammate" → Integrations → Meeting library → Routines/skills/memory → Use cases → Channel search demo → Where it lives → Wall of love → Security → Pricing → FAQ → Final CTA |
| **Steal** | The hero chat ends in **approval buttons**. The product's safety model is the hero, not a footnote. ShopPilot+ should do this with $ amounts. |

### 2.2 n8n — https://n8n.io/
| Field | Value |
|---|---|
| Hero headline | "Build the agent. Understand its workflow." |
| Subhead | "n8n is the platform for agents and workflows you can follow." |
| Primary CTA | "Get Started" |
| Hero visual | **Prompt → generated workflow diagram**: a plain-language refund-handling request becomes nodes: order lookup → **Slack approval request** → refund-or-ticket branch → customer confirmation → DB record |
| Social proof | 209.1k GitHub stars (Top 50 project), G2 4.7/5, 250k+ community, Huel (1,000 hours saved), Vodafone (£2.2M) |
| Trust/approval | Section "See + understand + trust your agents"; human approvals in workflows, guardrails, evaluations, audit logs, SIEM streaming, RBAC, self-hosting |
| Section order | Hero → Logo bar → Use-case stories → Integrations ("USB-C for your AI stack") → Observability/AI control → "Built by you + readable by anyone" → "Move fast + break nothing" → Enterprise → Case studies → CTA |
| **Steal** | **Show the plan as a readable graph** before anything runs. That is ShopPilot+'s "typed tool-call plan" made visual. Two-part headline: "Build X. Understand Y." |

### 2.3 Siena AI — https://www.siena.cx/
| Field | Value |
|---|---|
| Hero headline | "The AI CX operating system for consumer brands" |
| Subhead | "One intelligence layer powering agents across every customer surface." |
| Primary CTA | "Book a demo" |
| Hero visual | **Scripted chat**: a shopper forgot a discount code. The agent applies it, **refunds the difference**, then upsells a serum at 10% off |
| Social proof | Quotes from Spanx, HexClad, Prose…; stats: up to 80% automated, 98% / 90% / +94.7% CSAT; case-study numbers (Terra Kaffe saves $3,000+/mo) |
| Trust/approval | "Enterprise-grade safety and brand control" section; guardrails; routing that **explains each handoff with a note**; trust center |
| Section order | Hero → Customer stories → "CX platform built for agents" → Brand intelligence → Brand voice → Stats → Results → Agentic commerce (6 features) → Integrations → CTA |
| **Steal** | Hero story is a **realistic money move resolved end to end** in 4 bubbles. Write ShopPilot+'s hero as one real owner request → plan → $ preview → done. |

### 2.4 Yuma AI — https://www.yuma.ai/
| Field | Value |
|---|---|
| Hero headline | "Ecommerce AI agents for every customer journey" |
| Subhead | "Automate ecommerce support, sales, social, and chat with AI agents that resolve tickets, grow revenue, and keep response…" (continues: low response times without added headcount) |
| Primary CTA | "book a demo on your own ticket data" (exact button label not in extracted text) |
| Hero visual | Not confirmed by text extraction |
| Social proof | Hard numbers per brand: EvryJewels 89% automation / 63% cost cut; Javvy 24h → 12 min; Glossier 91% WISMO accuracy; Clove 3x ROI; YC-backed; 140+ brands; SOC 2 Type II |
| Trust/approval | **Hard limits on refunds, discounts, replacements**; gradual rollout on a narrow ticket set; **review AI replies before automation expands**; each playbook tested before going live; handoff with context for high-risk cases |
| Section order | Hero → Overview → What Yuma automates → Proof → **How deployment works** → **Integrations and control** → FAQ |
| **Steal** | **"Demo on your own data"** CTA, plus a "How deployment works" section that frames autonomy as *earned gradually*. |

### 2.5 Shopify Sidekick — https://www.shopify.com/sidekick
| Field | Value |
|---|---|
| Hero headline | "Starting a business? You've got backup." |
| Subhead | None; mascot card: "I'm Sidekick! Your AI Shopify expert." |
| Primary CTA | "Start for free" |
| Hero visual | **Mascot + chat UI** with example prompts ("help me pick a theme", "add product photos") and the resulting store design |
| Social proof | Brand logos (Tuckernuck, Jaded London…); "Hear from brands who made Sidekick part of their team"; a "Your story here" card |
| Trust/approval | "Respects access controls"; **stages storefront changes in a draft**, tests with AI-simulated shoppers (SimGym), shows a recommendation to review |
| Section order | Hero → Persona grid ("Your launch team in one tool") → Testimonials → Your story here → **Popular prompts (slash commands)** → Try it → Founder video → Updates → CTA → FAQ |
| **Steal** | **Popular-prompts gallery**: clickable example requests. ShopPilot+ should show 4–6 real owner sentences ("ship yesterday's orders…") as chips. |
| Threat note | This is ShopPilot+'s biggest incumbent. Its page **does not** promise per-action approval or undo. That is the opening. |

### 2.6 Prediko — https://www.prediko.io/
| Field | Value |
|---|---|
| Hero headline | "Restock on time, every time." |
| Subhead | "Prediko is a Shopify certified technology partner that helps D2C brands manage their inventory operations across all channels." |
| Primary CTA | "Get A Demo" |
| Hero visual | Decorative shapes (from filenames), plus a Shopify-partner badge, 5-star graphic, and a **"Works inside Claude, ChatGPT, Gemini"** row |
| Social proof | 3000+ merchants; 250+ 5-star App Store reviews; Victoria Beckham, Healf…; 75x ROI, ~60% fewer stockouts, ~70% less planning time; TechCrunch/Business Insider |
| Trust/approval | Borrowed authority: "Officially Recommended by Shopify", Stocky alternative, Shopify blog #1 listing |
| Section order | Hero → Features → Logos → Impact stats → Ops made simple → Press → Shopify endorsement → Testimonials → Results → 150+ integrations → FAQ → CTA |
| **Steal** | **Outcome headline in 5 words** with no AI jargon. Also: borrowed platform trust (Shopify badge) placed right in the hero. |

### 2.7 Gorgias — https://www.gorgias.com/
| Field | Value |
|---|---|
| Hero headline | "Deliver the best customer experience" |
| Subhead | "Bring your support team, customer data, workflows, and AI Agent together in one platform built for every stage of the customer journey." |
| Primary CTA | "Book a demo" (secondary "Discover pricing") |
| Hero visual | Not confirmed (decorative graphic, no alt text) |
| Social proof | 17,000+ brands; **$500M+ revenue driven**; 4.2x avg ROI; Bare Minerals 8.83x; Orthofeet 56% automation in < 2 months; OpenAI partner, Shopify-invested |
| Trust/approval | "Built-in guardrails"; AI "knows when to escalate" with context |
| Section order | Hero → Bento grid → "AI Agent + Helpdesk, built as one" → Customer stories → 50-in-50 program → Backed by the best |
| **Steal** | **Bento grid** right after the hero, and a big **$ number** as social proof ("$500M+ revenue driven"). |

### 2.8 Tidio Lyro — https://www.tidio.com/lyro/
| Field | Value |
|---|---|
| Hero headline | "The AI agent customers want to talk to" |
| Subhead | "Resolve more customer questions with helpful AI that learns from your data, speaks like your best agents and really cares." |
| Primary CTA | "Start for free" + "No credit card required" |
| Hero visual | **Product screenshot**: Lyro answering in the chat widget (responsive variants) |
| Social proof | Suitor CEO: 97% faster response; Under Armour, Stanley…; 75% resolution; G2 4.6 / Capterra 4.7 / Shopify 4.8 |
| Trust/approval | "Aligned with your brand, built for trust"; answers only from your content; **handoff rules for high-value customers or sensitive topics**; real-time monitoring |
| Section order | Hero → Integrations → Pain ("Struggle to scale?") → **Live demo agents** → Custom → Testimonial → Trust → 3-step onboarding → Logos → Pricing → **ROI calculator** → Setup → Stats → Features → FAQ → CTA |
| **Steal** | **ROI / savings calculator** plus a **live, try-it demo** on the page. Fits SMB owners who self-serve. |

Runner-up pages worth a glance: Rep AI (risk reversal, "5x ROI money-back guarantee"), Fin (99.8% SLA, **spend alerts and limits**), Decagon (action bubbles), Relevance AI (**L1–L4 autonomy ladder**), gotoHuman (approval inbox screenshot).

---

## 3. Visual inspiration: award-level SaaS pages that fit "AI agent / ops tool"

| # | Page | URL | Fetched? | Hero (verbatim where fetched) | Technique to borrow |
|---|------|-----|----------|-------------------------------|---------------------|
| 1 | Attio | https://attio.com/ | Yes | "Welcome to agentic revenue." | **Split hero**: source data (transcript) ↔ Slack thread where `@Attio` answers ↔ terminal panel writing results back. Shows input → agent → effect in one frame |
| 2 | Cursor | https://cursor.com/ | Yes | "Cursor is your coding agent for building ambitious software." | **Interactive product demo as the hero** over one flat brand color; task list with "In Progress / Ready for Review" states (= ShopPilot+'s Pending approval / Done) |
| 3 | Ramp | https://ramp.com/ | Yes | "Time is money. Save both." | Sells **AI + money + policy**: approval thresholds, "Policy Agents", email-field CTA, giant customer count |
| 4 | Stripe | https://stripe.com/ | Yes | "Financial infrastructure to grow your revenue." | Animated wave/gradient + **logo marquee** + hard stats band (99.999% uptime). The tone of "this moves money and is safe" |
| 5 | Clay | https://www.clay.com/ | Yes | "Build systems to grow revenue" | **Playful 3D toy-contraption illustrations** with one consistent style, plus a "What do you want to build?" prompt box |
| 6 | Granola | https://www.granola.ai/ | Yes | "The AI notepad for back-to-back meetings" | Calm real UI screenshot with a "My notes / Enhanced" **before/after toggle**. Use it as a "Your request / ShopPilot plan" toggle |
| 7 | Raycast | https://www.raycast.com/ | Yes | "Your shortcut to everything." | Big physical-object hero (keyboard) with **4 callouts incl. a reliability stat** ("99.8% crash-free") |
| 8 | Superhuman | https://superhuman.com/ | Yes | "Superpowers, everywhere you work" | Human photo + **layered UI mockup** where the AI proposes an action and the user accepts it |
| 9 | Vercel | https://vercel.com/ | Yes (text only) | "Agentic Infrastructure" | 2-word category-claim headline; segmented proof (one customer per audience) |
| 10 | Linear | https://linear.app/ | **No**: JS-only, fetch returned "Loading…" | Unverified | Known for dark UI, precise type, and product-UI-as-hero; check it in a browser before quoting |
| — | Resend | https://resend.com/ | Yes, but only an agent-facing markdown version came back | H1 "Resend" | Not assessable from text; open in a browser |
| — | Lovable | https://lovable.dev/ | **No**: 403 | — | Known for a prompt box as hero; open in a browser |

---

## 4. Positioning

### 4.1 What the field leads with (hero words)
| Theme | Who | Evidence (hero / near-hero copy) |
|---|---|---|
| "AI employee / teammate" | Lindy, Zapier, Sidekick | "Hire Lindy, get it done."; "Meet your new AI teammates"; "You've got backup." |
| CX / support resolution | Gorgias, Siena, Yuma, Fin, Lyro, Decagon, Sierra | "Deliver the best customer experience"; "AI CX operating system"; "AI concierge for every customer" |
| Automation % and ROI | Yuma, Siena, Rep, Gorgias | "89% automation", "5x+ ROI", "$500M+ revenue driven" |
| Restock outcome | Prediko, Fabrikator, Inventory Planner | "Restock on time, every time."; "Prevent stockouts. Improve your cash flow." |
| Understandable / controllable | n8n, Relevance AI, gotoHuman | "Understand its workflow"; L1–L4 autonomy; "AI Automation unlocked with human supervision" |

**Pains named:** too many tickets, slow response times, headcount cost, stockouts, planning time. **Pain nobody names in a hero:** *"I'm scared to let AI touch my money and my customers."*

### 4.2 The gap ShopPilot+ can own
**"Safe autopilot for your shop: see every dollar before it moves."** One request covers ops (ship, email), inventory (restock forecast), and money (refunds). Every money move is previewed as a $ diff, approved, logged, and undoable.

Evidence the gap is real and current:
1. **Fear is documented.** Shopify's own guide (Aug 19, 2026) says larger refunds "require human intervention for sign-off". It warns that an agent capped at small refunds can be manipulated into a $500 request, and it recommends screening incoming messages for prompt injection. https://www.shopify.com/blog/agentic-ai-security
2. **Builders are asking for it right now.** Shopify dev forum thread (replies on 2026-10-27 and 2026-10-30): enforce caps in the tool, not the prompt; idempotency keys; velocity limits; kill switches; audit receipts; test prompt-injection cases. https://community.shopify.dev/t/what-guardrails-are-truly-essential-for-safe-autonomous-refunds-up-to-200-in-ai-support-agents/31750
3. **Competitors hide it.** Yuma, Siena, Gorgias, Fin, and Sierra all have guardrails, but **below the fold** and as compliance lists. Zapier Agents' page has **no** approval copy at all. Sidekick promises drafts but not per-action approval or undo.
4. **The only hero-level approval story is horizontal, not e-commerce.** Lindy ("Nothing irreversible happens without your approval") and n8n (Slack approval node) are not Shopify-native. Macha has a refund confirmation card, but only in a blog post, scoped to helpdesk refunds.
5. **Nobody bundles ops + forecasting + money with approval.** CX agents don't forecast. Forecasting tools (Prediko, Fabrikator, Inventory Planner) don't execute refunds or emails. Cogsy, the "ops OS" attempt, is discontinued.

Candidate headlines (all grounded in the gap):
- "Run your shop in one sentence. Approve every dollar."
- "Autopilot for your store, with your hand on the brake."
- "Tell it what to do. See the $ before it happens. Undo anything."

### 4.3 What this means for the mockups (shipping-box / label / manual themes)
Every winning page above uses the **product UI as the hero**, not a metaphor illustration. The themed skins hide the product. Replace them with:
1. A hero showing **one owner sentence → plan steps → $ dry-run diff → Approve / Undo** (Lindy + n8n + Siena pattern).
2. Example-prompt chips (Sidekick).
3. A trust strip *in* the hero: "Refunds over $X need your OK · Every action logged · 1-click undo · Injection-guarded inbox".
4. Outcome stats (Prediko / Yuma style). Use honest demo numbers, labeled as demo data.
5. One playful illustration style for secondary sections only (Clay), if any theme survives.

---

## 5. All sources (fetched 2026-10-30)
Product pages: shopify.com/sidekick · shopify.com/magic · gorgias.com · gorgias.com/ai-agent (no body) · gorgias.com/products/ai-agent (404) · siena.cx · yuma.ai · hellorep.ai · rep.ai (404) · tidio.com/lyro · intercom.com/fin → fin.ai · prediko.io · inventory-planner.com · fabrikator.io · cogsy.com → mayple.ai/cogsy · lindy.ai · n8n.io · zapier.com/agents · relevanceai.com · decagon.ai · sierra.ai · manus.im · gotohuman.com · humanlayer.dev · ramp.com
Inspiration: attio.com · cursor.com · stripe.com · clay.com · granola.ai · raycast.com · superhuman.com · vercel.com · resend.com · linear.app (JS-only, not readable) · lovable.dev (403)
Evidence: shopify.com/blog/agentic-ai-security · community.shopify.dev thread 31750 · getmacha.com/blog/automating-shopify-refunds-safely-ai-confirmation
Search-only (not fetched): hellorep.ai background facts via WebSearch; emarketer.com/content/shopify-adds-ai-agent-guardrails (Oct 2026 Shopify agent-checkout approval rule, reported secondhand).
