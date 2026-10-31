# ShopPilot+ landing approaches, round 2

Six product-first landings, each with its matching `/app` console. Built 2026-10-30 from `docs/research/04-five-approaches.md`. Static demo data from `src/data/demo.ts` and `src/data/v2.ts`. Round 1 (Carton, Label, Build Book) was rejected and stays linked on the index under "Rejected round 1".

- Review index: http://127.0.0.1:4321/
- Dev server command: `cd shoppilot/web && CHOKIDAR_USEPOLLING=1 npx astro dev --host 127.0.0.1 --port 4321 --ignore-lock`
- Ranking: **6 > 1 > 2 > 5 > 3 > 4**. Reasons are at the bottom.

## What all 6 share

- **Positioning:** "Safe autopilot for your shop. See every dollar before it moves."
- **Hero:**
  - an 18-word sub
  - one primary CTA, "Try the live demo"
  - "No signup. Runs a recorded plan on a demo store, so it costs nothing."
- **Section order:** 9 sections in 04's order, plus planned pricing before the FAQ. Exceptions:
  - 3 moves the quote up under the hero.
  - 5 moves Safety up to section 2.
- **Pricing:** labelled verbatim, at the heading: "Planned pricing, part of a student startup simulation; not for sale."
- **Honesty:** no logos, testimonials or invented metrics.
  - Proof uses the prototype ML numbers from spec 03 §6, labelled "Prototype, synthetic demo data", plus the demo-store cost, labelled "Demo store".
  - Refunds show "Irreversible" (spec 05 D6) everywhere.
- **CSP:** a production build (`npx astro build`, 21 pages) has:
  - 0 inline scripts, 0 `<style>` tags, 0 `style=` attributes
  - 0 external URLs, no `innerHTML`
  - only self-hosted fonts
- **Horizontal scroll:** `scripts/check-overflow.mjs` compares `scrollWidth` to `clientWidth`. All 12 routes pass at 390, 1440 and 1920 (36 of 36 OK).

## 6-way comparison

| | 1 Approval-first, Stripe-clean | 2 Demo is the landing | 3 Sunday-night scroll story | 4 Cinematic hero + film | 5 Trust ledger, safety-first | 6 Recommended blend |
|---|---|---|---|---|---|---|
| Hero product UI | Static plan card. Pills tick Checked 1 to 5, then stop on "$24.00 awaiting your approval" | Request box and chips. The plan builds only after a click | A real inbox (Sun 9:41 pm) ending in a "$24.00 Needs approval" row | Labelled dusk video placeholder, with the plan card overlapping its edge | The step-5 refund as a ledger (before, after, money out, Irreversible) plus the audit receipt | Live demo panel. The recorded plan builds once on load, and chips or Plan it rebuild it |
| Signature motion | One CSS sequence, about 2.5 s, plays once | The plan building in reply to a click, 200 ms stagger | Sticky stage cross-fade on `animation-timeline: view()`, with a static fallback | Hero copy and card slide up once. The video loop comes later | BLOCKED stamp in "Try to trick it" (220 ms) | The plan building on load and on click. Run goes Running then Done |
| Type | Mona Sans | Schibsted Grotesk | Bricolage Grotesque + Hanken Grotesk | Hubot Sans + Mona Sans | Public Sans | Mona Sans |
| Palette | White, navy #0a2540, indigo CTA #4338ca | Cool grey #f4f5f7, ink #111317, orange CTA #c2410c | Dusk-tinted #f4f2fb, ink #1d1b3a, indigo CTA #2f2a7a | White, ink #0f1419, teal CTA #0f766e, dusk hero | Paper #fbfbf8, green ink #0f2a22, green CTA #146c43 | Same as 1 |
| Landing JS (gz) | 0 (console 1.7 kB) | 2.7 kB | 0 (console 1.3 kB) | 1.1 kB (pause button, inactive until a video exists) | 2.0 kB | 3.2 kB |
| Works with no JS | Yes | Yes (server-rendered pending plan) | Yes | Yes | Yes. The trick box needs JS | Yes (server-rendered pending plan) |
| Depends on | Nothing | Nothing (fixture JSON now, `/api/plan` replay later) | Scroll-driven CSS (about 88% of browsers; the rest get stacked panels) | A Veo clip and a 30 s OBS film that don't exist yet | A guard-only endpoint to replace the sample verdicts | Fixture JSON now, `/api/plan` replay later. The OBS film is optional |
| Why a shop owner clicks | Within 1 s the hero shows their fear answered: a real refund stopped on an Approve button | They did it themselves. "Try the live demo" means do more of it | They see their own Sunday night told end to end | Emotional first frame, then the real gate | The fear is named, then answered with receipts and limits they can poke | Sees the gate in the first frame and can run it right there |
| Weakest point | Looks familiar. The copy and the $24 moment carry all the difference | Before any click the first screen is an empty box | The hero is an inbox, not a plan. The story needs scrolling; long chapters | The two biggest frames are placeholders and read unfinished on a projector | Leads with fear. Time saved shows only from section 3 | The densest page, and the replay always plays the same plan for every chip |
| Build risk for 11-05 | Low | Medium (backend replay needed for the real thing) | Medium-high (Safari and Firefox fallback) | Medium (assets plus 1.5 MB per view on Render free) | Medium (guard endpoint) | Medium (same as 2) |

## Screenshots (`shoppilot/web/review/v2/`)

| Set | Files | Notes |
|---|---|---|
| First screen as a visitor sees it | `N-hero-1440.png`, `N-hero-390.png` | 1440x900 and 390x844 |
| Full page (my review pass) | `full/N-landing-1440.png`, `full/N-landing-390.png`, `full/N-app-1440.png`, `full/N-app-390.png` | Captured beyond the viewport. Sticky elements (console run bar, approach 3's story stage) show mid-page in these shots, which is an artifact of full-page capture |
| Builder shots | `N-landing-1440.png`, `N-landing-390.png`, `N-app-1440.png`, `N-app-390.png` | Fixed window heights, so some cut off before the footer |
| Approach 3 story at a real viewport | `3-story-1440-plan.png`, `3-story-1440-approve.png`, `3-story-1440-done.png` | |
| Approach 6 console first screen | `6-app-first-1440.png` | Shows the sticky run bar placed correctly |

## Fixes I made after the builders finished

1. **6 hero:** it now builds the recorded plan on load, so the first screen always shows the $ gate. Before this fix it showed an empty skeleton until a click.
2. **1, 4, 6 tabular figures:** Mona Sans's `tnum` swaps in a slashed zero (`zero.tf`, with no alternate). Money uses proportional lining figures there instead.
3. **5 sample verdicts:** the label "Recorded verdicts" became "Sample verdicts written for this mockup (Demo store)". Those scores were never produced by a guard run.
4. **Shared data:**
   - Removed the ` · ` separators from `demo.ts` step targets.
   - Moved the audit receipt times to 21:52 to match the Sunday-night story.
   - Corrected copy that claimed refunds can be undone. They cannot (spec 05 D6). The caps now use the real limits ($200 per order, $500 per plan, 30 days).
5. **Approach 4 Veo prompts:** 3 prompts with negative prompts are in `shoppilot/web/VEO-PROMPTS.md`. No video was generated.

## Ranking and conversion reasoning

1. **6, Recommended blend.**
   - The visitor sees the product doing the risky thing (a $24.00 refund) and stopping for permission, in the first frame.
   - They can then run it themselves without leaving the page.
   - That one panel sells the product and is also the 30% live-demo grade.
   - The safety ledger and receipts answer "what if it goes wrong" before anyone asks, and the planned pricing shows the business model honestly.
   - Risk: it needs `/api/plan {replay:true}` working by the freeze, but the fixture covers the demo either way.
2. **1, Approval-first, Stripe-clean.**
   - The best static first screen, zero landing JS, and the lowest build risk.
   - Choose it if the backend replay slips: it converts on the same promise and only lacks interactivity.
3. **2, Demo is the landing.**
   - The purest "try it" page, and its orange CTA is the most distinctive of the six.
   - It loses to 6 only because its first screen is an empty request box until someone clicks. On a projector and in screenshots, that hides the gate.
4. **5, Trust ledger.**
   - The most differentiated message: nobody else in `01-similar-products.md` leads with the fear.
   - "Try to trick it" is the most shareable moment.
   - It ranks below because it leads with risk, not hours saved, and its best feature needs a guard endpoint we don't have yet.
5. **3, Sunday-night story.**
   - The best emotional fit with the 4 to 5 hours quote.
   - But the hero is an inbox, the proof needs scrolling, and the scroll stage needs a solid fallback for 12% of browsers.
6. **4, Cinematic.**
   - It could look best once the clips exist. Today its two largest frames are labelled placeholders.
   - It adds about 1.5 MB per view against Render free's 5 GB a month.
   - Keep its product-film slot (already in 6), not the hero.

## Open questions

1. Which approach? My pick is 6, with 1 as the fallback.
2. Approach 6 auto-builds its plan once on load. Keep that, or wait for a click like approach 2?
3. "Money out if you run": approaches 1, 2 and 6 show the true approved total ($0.00 until you tick the refund), while 3, 4 and 5 show $24.00 as spec 06 wrote it. Which rule should ship?
4. Pricing tiers ($0 Demo, $19 Solo, $49 Growing): OK as the simulation's planned prices?
5. Should "Try to trick it" ship in 6? It needs a guard-only endpoint (open question Q11 in 04).
