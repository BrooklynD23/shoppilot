# ShopPilot+ landing, round 3: one page, three skins

Built 2026-10-30. Round 2 was rejected as "too wordy, lacks content and visuals, doesn't feel like a SaaS". Round 3 keeps approach 6's content model:
- the live plan card hero
- approve every dollar
- safety
- forecast
- planned pricing

Each variant re-composes that content around layered real product UI.

- Review index: http://127.0.0.1:4321/ (round 3 is listed first)
- Ranking: **C > A > B**. Reasons are at the bottom.
- Shared copy, word-budgeted: `src/data/v3.ts`. Product data: `src/data/demo.ts`. Pricing and FAQ: `src/data/v2.ts`.

## Reference lessons (real screenshots, `review/refs/*-stack.png`, hero plus 2 scrolls at 1440)

| Site | What makes it feel like a SaaS |
|---|---|
| lindy.ai | 1. Hero copy is 5 words plus 2 lines, centred, then a huge real product window (Slack-style chat) that ends in action buttons ("Pause the campaign"). 2. Integration icons float around the hero as atmosphere. 3. A logo row comes right after the product, and each feature section pairs one short claim with a framed UI or illustration card. |
| attio.com | 1. A tight centred headline plus a 2-line sub, with 2 CTAs. 2. The product window bleeds into a soft blue gradient band, so it has depth without decoration. 3. The logo grid uses bordered cells, then a left tab list drives a large real data table. |
| linear.app | 1. Near-black ground, a left-aligned 2-line headline and a one-line sub. 2. A huge product screenshot with an agent side panel layered over it: overlapping panes read as "real software". 3. Section heads are a bright sentence plus a grey continuation, and feature figures are numbered line illustrations. |
| stripe.com | 1. An animated colour ribbon in the top right. The headline is a dark sentence that continues in a grey one. 2. The logo row sits straight under the hero. 3. Bento feature cards each hold layered UI fragments (phone checkout, billing chart, card) over a tinted gradient floor. |
| resend.com | 1. Black ground, serif display and a single 3D object: one strong visual, very few words. 2. A faint top glow and a hairline panel edge give depth. 3. Integration icon tiles sit above a real code block, so the product is shown in its native form. |
| raycast.com | 1. The hero atmosphere is dramatic red light stripes, with a centred 2-line headline and one CTA. 2. The product window sits on a red glow, with a dock-like control row under it. 3. Copy is tiny: a white sentence plus a grey line per feature. |
| cursor.com | 1. Warm neutral canvas, a small left headline, then an enormous product window over a painted landscape backdrop. 2. Logos sit in grey tiles. 3. Sections alternate short text with large real product windows on soft backdrops, and multi-pane windows (app plus CLI) overlap. |

Common rule I drew from all 7: a large layered real-product composition, atmosphere behind the product (not behind the text), headlines of 9 words or fewer, a proof strip under the hero, and feature cards that hold UI, not paragraphs.

## The 3 variants

| | A Dark premium | B Vibrant light | C Bento product-led |
|---|---|---|---|
| URL | /v3/a/ and /v3/a/app/ | /v3/b/ and /v3/b/app/ | /v3/c/ and /v3/c/app/ |
| Feel | Linear, Vercel, Raycast | Stripe, Lindy | Attio, Cursor |
| Ground | #07080a near-black, raised #0f1115 / #15181d, hairlines rgba(255,255,255,.08) | White #ffffff, bands #f6f8fb, soft 2-layer shadows | Cool neutral #eef0f2, white tiles, hairline #dfe3e8 |
| Accent | Approval amber #f5b544 (money, glow, focus). Light pill CTA | Warm multi-hue mesh (tangerine, rose, saffron, aqua). Ink pill CTA #0d1b2a | Agent-state pills carry the colour. Ink pill CTA #121417 |
| Type | Mona Sans 580, h1 about 70 px; JetBrains Mono for IDs | Bricolage Grotesque 650 to 700 + Hanken Grotesk | Schibsted Grotesk 700 |
| Hero composition | Plan card in 3D tilt, audit-log pane behind it like Linear's side panel, BLOCKED chip, forecast chip and $24.00 badge floating at depth, amber + teal glow, masked dot grid | Tilted plan card over the mesh, BLOCKED chip, forecast card, receipt and saffron $24.00 badge, overlapping into the built-with band | A bento cluster: tilted plan card as the big tile, with $24.00 badge, forecast, BLOCKED and receipt tiles breaking its edges, on an aqua-to-amber backdrop |
| Signature | Pills tick Checked 1 to 5, step 5 lands on Needs approval, amber badge lands with one pulse | Same | Same |
| Ambient | Glow drift, 20 s | Mesh drift and rotate, 28 s | Backdrop drift, 24 s |
| Walkthrough (replaces the film placeholder) | 5-scene CSS loop, 11 s, with a Pause control | 5-scene loop, 12 s, with Pause | 5-scene loop, 12 s, with Pause |
| Copy words (budget 220) | **204** | **199** | **207** |
| h1 / sub words | 8 / 15 | 8 / 15 | 8 / 15 |
| Landing JS | 0 | 0 | 0 |
| Projector risk | Highest: dark grounds go muddy on washed-out projectors | Low | Lowest |
| Weakest point | Amber is also used for "flagged" pills, which dilutes "amber = money". The walkthrough tile has dead space mid-cycle | The mesh is softer than Stripe's ribbon, and a band of empty grey sits under the hero at 1440x900 before the built-with strip | Quietest "wow" in the first second. Some bento tiles have uneven heights (spare space in Injection guard) |

### Self-critique against the 6 round-2 problems

| Problem | A | B | C |
|---|---|---|---|
| 1 No colour, depth or atmosphere | Fixed: glow + grid + dark depth | Fixed: mesh + tinted tile floors | Fixed: backdrop + pill colour on every tile |
| 2 About 900 words of grey paragraphs | Fixed (204) | Fixed (199) | Fixed (207) |
| 3 Empty space under the CTA | Fixed: the composition starts right under the sub row | Mostly fixed: the composition fills the right column, but there is a thin empty band before the strip | Fixed: the text column is centred on the cluster |
| 4 Film placeholder and skeleton hero | Fixed: hero server-rendered; the real-UI loop replaces the film | Fixed | Fixed |
| 5 One flat card, no layering | Fixed: 2 panes + 3 floating pieces | Fixed: 5 pieces at 3 depths | Fixed: 5 overlapping tiles |
| 6 No bento, strip or motion | Fixed | Fixed | Fixed: the bento is the centrepiece |

## Checks
- **HTTP:** all 6 routes return 200.
- **Overflow:** `scripts/check-overflow.mjs` compares scrollWidth to clientWidth. 18 of 18 OK (6 routes at 390, 1440 and 1920).
- **Words:** `scripts/count-words.mjs` counts visible copy, excluding `[data-ui]` product fragments, #pricing, #faq and aria-hidden nodes. A is 204, B 199, C 207, all within 220.
  - C notes that its 4 safety cap chips are marked `data-ui`. Counted as copy, C is about 219.
- **CSP:** a production build (`npx astro build`, 27 pages) has 0 inline scripts, 0 `<style>` tags, 0 `style=` attributes and 0 external URLs. Fonts are self-hosted. The landings ship no JS.
- **Logos:** the "Built with" strip uses plain text wordmarks with drawn glyphs, because I could not verify the Anthropic and Stripe brand terms. There is no Shopify claim.

## Fixes I made after the builders finished
1. A and B: hero step 5 showed "Checked". It now lands on "Needs approval", matching C and the product truth.

## Screenshots (`shoppilot/web/review/v3/`)
| File | What |
|---|---|
| `K-hero-1440.png`, `K-hero-390.png` | First screen as a visitor sees it |
| `K-tall-1440.png`, `K-tall-390.png` | Whole page in a tall window, with scroll reveals done |
| `K-landing-1440.png`, `K-landing-390.png` | CDP full-page capture. Reveal-on-scroll sections can show blank here; use `K-tall-*` instead |
| `K-app-1440.png`, `K-app-390.png` | Console, re-skinned from approach 6, same behaviour |
| `phones-390-abc.png` | The 3 phone pages side by side |
| `../refs/*-stack.png` | The 7 reference sites |

## Ranking and why
1. **C, Bento product-led.**
   - It answers the rejection most directly: the page is mostly the product. Nearly every section is a real UI tile, and there are almost no paragraphs.
   - It reads like Attio or Cursor, and it is the safest on a projector, where the demo is 30% of the grade.
   - Every section shows the gate, the guard or the forecast working.
2. **A, Dark premium.**
   - The strongest "premium SaaS" first impression, and amber-as-money makes the $24.00 approval glow the story.
   - Choose it if the demo runs on a bright laptop screen or a video rather than a projector.
3. **B, Vibrant light.**
   - The friendliest of the three, and the closest to Stripe.
   - Its mesh is softer than the reference, and the band under the hero is the one remaining empty-space issue.

A blend worth considering: C's layout and bento with A's amber glow behind the hero cluster, in light mode.

## Open questions
1. Which variant: A, B or C? Or C with A's amber glow?
2. Dark or light for the live demo? It depends on the room's projector.
3. Should "Built with" use official Anthropic and Stripe logo SVGs once someone checks their brand terms?
4. Is the 220-word budget the rule for the real `/` page too, including the FAQ?
