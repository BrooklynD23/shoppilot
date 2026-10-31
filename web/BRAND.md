# ShopPilot+ brand system

Night to morning, kept. Precise like Resend: graphite and tissue neutrals, light instead of colour, and one accent. **Lamp amber means money waiting for a human. Nothing else is amber.**

- Tokens: `src/styles/tokens.css` (imported by `src/styles/site.css`). Shared components (buttons, pills, header, footer): `site.css`.
- Contrast gate: `node scripts/check-contrast.mjs` (57 pairs, all pass AA).
- References and before/after shots: `review/brand-refs/`.

## 1. Rules for page teams (the 10 that matter)

1. **Amber = money awaiting approval, only.** Allowed: money amounts (`.money`), the approval badge, the money checkbox (`.money input` or `accent-color: var(--money-fill)`), the `Needs approval` pill. Never on CTAs, logos, focus rings, unread dots, quote rules, disclaimers or glows.
2. **No new hex values in page CSS.** Read `var(--bg|s1|s2|s3|ink|ink-2|ink-3|line|line-2|line-ctl|money|ok|bad|run)`. Scrims: `rgb(var(--n-bg-rgb) / .5)`. Need a new colour? Add it to `tokens.css` and pass the contrast gate.
3. **Gradients are light, never colour.** Use only `--light-top`, `--light-edge`, `--light-sheen`, `--light-lamp` (hero, once), `--dawn` and photo scrims. No mesh, no purple or pink, no coloured radial glows, no `filter: blur` halos, no gradient text.
4. **Primary button is ink** (`.btn-primary`, light on night, dark on morning), 12 px radius, at most 1 per screen. Secondary is `.btn-line`. Pill radius is for status pills and small toggles only.
5. **Elevation once.** Resting card: `box-shadow: var(--elev-1)` (or `--shadow`) with no `border`, or a `border` with no shadow. Floating layer over content or footage: `var(--elev-2)`. Never border plus wide soft shadow.
6. **One radius scale**: 4 stamps and checkboxes, 6 tags, 12 controls, 16 cards, 20 media. Inner radius = outer minus padding.
7. **Type**: Mona Sans only (+ JetBrains Mono for code, tool names, IDs). h1 and h2 at weight 500, tracking `--tr-display` / `--tr-h2`; h3 and card titles 560; body 16 px / 1.6. Contrast comes from colour (ink vs ink-2), not from weight 600+ or size jumps.
8. **Status is a word + a dot.** Use `.pill--{planned|checked|running|done|allowed|undone}` (hairline chip) and only tint `approval` and `blocked|irreversible|failed`. No violet, no rainbow chips.
9. **Icons**: one line family, 16 px (20 px max in features), `stroke: currentColor`, rendered at `--icon-stroke` 1.5 px via `non-scaling-stroke` (automatic for `svg.icon`). New glyph: copy Lucide geometry (ISC) or draw on our 16 grid. No filled, duotone, emoji or Unicode icons.
10. **Copy is short and true** (section 6): h1 8 words max, sub 16, h2 6, button 3. Real demo numbers, "Demo store" labels, no hype words, no dashes, no eyebrows.

## 2. What the references do (measured 2026-10-31, 1440 px)

Probe: `review/brand-refs/*-probe.json` (computed styles), screenshots `*-1440-s0..s4.png`.

| | Resend (`resend-*`) | Linear (`linear-*`) | Mercury (`mercury-*`) |
|---|---|---|---|
| Ground | `#000`, cards `#05050a` | `#08090a`, panels `#0f1011` | navy `#171721`, then a light warm section |
| Ink / secondary | `#f0f0f0` / `#a1a4a5` | `#f7f8f8` / `#8a8f98` | `#ededf3` / `#c3c3cc` |
| Display | Domaine serif 96 px, w400, -0.01em | Inter 64 px, w510, -0.022em | Arcadia Display 49 px, w480, 0 |
| h2 | Favorit 56 px, w400, -0.05em | 48 px, w510, -0.022em, grey continuation | 42 px, w480, +0.01em |
| Body | 18 px / 1.5, grey | 15 px / 1.6, grey | 16 px |
| Buttons | 40 to 48 px, **16 px radius**, dark fill, 5% white sheen, 1 px ring | 32 px light-grey pill, 5-layer micro shadow | 40 px pill, one accent fill |
| Radii | 6 / 16 / 24 | 4 / 8 / 12 / pill | 4 / 12 / pill |
| Borders | 1 px cool white at 14 to 19% | 1 px white at 8% (12% strong) | 1 px at 36% |
| Shadows | rings only; one coloured glow on a 3D icon | ring + inset 0.5 px highlight + 0 2 32 black 25% | barely any (2 to 4%) |
| Gradients | 245 nodes, almost all **luminance**: text fade, 5 to 10% button sheen, 1 px edge highlight, image masks. Colour: 2 tiny spots | header fade, light floor under the product, 3 to 4% white fills | 19 nodes, all scrims and feather masks |
| Icons | filled, 14 to 24 px | line 1.5, 14 px | filled, small |
| Motion | `(.4,0,.2,1)` 150 to 200 ms | `(.25,.46,.45,.94)` 100 ms; drawer `(.32,.72,0,1)` 700 ms | `(0,0,.2,1)` 300 ms |
| Copy | h1 3 words, sub 17, h2 3 to 6 | h1 9 words, sub 11, h2 3 to 4 | h1 3 words, sub 14 |

What we take: neutrals that recede, hairlines instead of shadows, light as the only gradient, short headlines with a grey continuation, generous section spacing (about 190 px on Resend), money set precisely (Mercury's small cents). What we skip: Resend's serif display and gradient text (serif + cream + warm accent is the top AI tell), icon eyebrows above headings (banned), Mercury's accent-filled CTA.

## 3. Diagnosis and fix

Before: `review/final/landing-hero-1440.png`, `review/final/landing-tall-1440.png`. After the token pass: `review/brand-refs/shoppilot-after-*.png`.

| Read as AI-made | Fix (token or shared rule) |
|---|---|
| Amber on 8 roles: CTAs, nav CTA, logo tile, focus ring, selection, every checkbox, glows, a full amber closing band | Amber on 1 role (money). CTAs, logo, focus, selection and checkboxes are ink |
| Espresso `#14100c` + cream `#f7f1e7` + saffron: the "espresso, beige, brass = premium" palette | Graphite `#0f0e0c` and tissue `#f7f6f3`, chroma under .005; the footage carries the warmth |
| Blurred amber radial glows behind the hero, bento and pricing | `--light-lamp`: one 10% warm light, hero only; other glows removed |
| 7-stop brown-orange dawn gradient | `--dawn`: two neutral stops |
| Five tinted pill colours, including AI violet for "undone" | Hairline chip + dot; tint only for approval and danger; violet removed |
| Headings at weight 580 to 640 | 500 display, 560 titles |
| Cards with border plus soft shadow | `--elev-1` hairline ring; `--elev-2` only when floating |

## 4. Tokens

### Colour (WCAG 2.1, all text pairs 4.5:1 or more)

| Role | Night | Morning | Use |
|---|---|---|---|
| `--bg` | `#0f0e0c` | `#f7f6f3` | page ground |
| `--s1` / `--s2` / `--s3` | `#161513` / `#1d1b19` / `#272523` | `#fdfdfb` / `#eeede9` / `#e1dfdb` | card, inset, pressed |
| `--ink` | `#f2f0ec` 17.0:1 | `#1b1916` 16.2:1 | headings, primary text, primary button, focus |
| `--ink-2` | `#bab7b2` 9.7:1 | `#504c48` 7.9:1 | body, continuations |
| `--ink-3` | `#97938e` 6.3:1 | `#67625e` 5.6:1 | meta, timestamps (4.5:1 even on s3) |
| `--line` / `--line-2` | white 8% / 14% | ink 9% / 16% | hairlines, hover edges |
| `--line-ctl` | white 36% (3.0:1) | ink 48% (3.1:1) | input and outline-button edges |
| `--money` | `#f0be6d` 11.3:1 | `#8a560c` 5.7:1 | money text; `--money-fill` for the badge and checkbox |
| `--bad` | `#ea8f7d` | `#a8372a` | blocked, irreversible, failed |
| `--ok` / `--run` | `#91cea6` / `#9bc0db` | `#2d6945` / `#376285` | dots, chart lines, provenance tags |

Surfaces switch with `.night` / `.morning` on a section; components never pick a surface's primitives (`--n-*`, `--m-*`) except to draw on footage.

### Type

| Token | Value | Use |
|---|---|---|
| `--fs-display` | 40 to 72 px, w500, -0.03em, 1.04 | h1 |
| `--fs-h2` | 28 to 44 px, w500, -0.024em, 1.1 | section heads; second sentence in `--ink-2` |
| `--fs-h3` | 20 px, w560, -0.012em | card titles |
| `--fs-lead` | 17 to 19 px | hero sub, ledes |
| `--fs-body` / `--fs-small` / `--fs-micro` | 16 / 14 / 12 px | body, meta, pills |

Money on figures 24 px and up: `$24<span class="cents">.00</span>`. Numbers use `.num` (Mona Sans tabular figures have a slashed zero).

### Space, radius, elevation, light, motion

| Group | Tokens |
|---|---|
| Space | `--sp-1..9` = 4, 8, 12, 16, 24, 32, 48, 64, 96 px; `--section` 96 to 168 px between landing sections; `--gutter`, `--maxw` 1200 |
| Radius | `--r-xs` 4, `--r-sm` 6, `--r-ctl` 12, `--r-card` 16, `--r-media` 20, `--r-pill` |
| Elevation | `--elev-1` resting (night: 8% ring + 4% top highlight; morning: 9% ring), `--elev-2` floating (adds one deep shadow), `--shadow` = `--elev-1` |
| Light | `--light-top` (night section head), `--light-edge` (1 px top highlight: `background: var(--light-edge) top / 100% 1px no-repeat, var(--s1)`), `--light-sheen` (on buttons), `--light-lamp` (hero, once), `--dawn` |
| Motion | `--ease-out` (.23,1,.32,1) for all UI; `--ease-in-out` for on-screen moves; `--ease-drawer` for sheets; `--ease-sig` (.16,1,.3,1) for the one Persuade moment. `--dur-press` 140, `--dur-1` 160, `--dur-2` 220, `--dur-3` 320, `--dur-reveal` 700 ms. Press: `scale(.97)`. No bounce. Reduced motion: opacity only |
| Icon | `--icon-stroke` 1.5 px |

### 3D agents and illustration

Agents are objects from the desk, told apart by **shape, material and a name label**, never by neon hue:

| Material | Token | Agent on the console stage (`src/scripts/console/stage3d.ts`) |
|---|---|---|
| Pewter tin `#a7a49d` | `--mat-tin` | Guard: a service-desk bell that rings when an email is blocked |
| Tissue `#e9e4da` | `--mat-tissue` | Router: a felt pebble with a signpost |
| Kraft paper `#b69770` | `--mat-kraft` | Planner: a notebook with an elastic band and a pencil |
| Dusk glass `#546f7b` | `--mat-dusk` | Forecaster: a glass globe with a spinning orbit |
| Graphite `#3a3734` | `--mat-graphite` | Validator: a rubber stamp that stamps each step it checks |
| Sage felt `#8f9a8a` | `--mat-sage` | Judge: a tall egg in reading glasses |
| Walnut `#775531` | `--mat-walnut` | Executor: a desk drawer that prints a receipt per step |

Lighting is soft and from above (the morning window). The lamp amber appears on an agent only while it holds money for approval (the Executor's envelope). No purple, no emissive glows, no chrome. State still shows as a word. The same silhouettes exist as 2D SVG portraits (`src/components/console/Portrait.astro`) for no WebGL and reduced motion.

## 5. Do and don't

| Do | Don't | See |
|---|---|---|
| Ink primary button with a 10% sheen, 12 px radius | Saffron pill CTA | `brand-refs/resend-1440-s0.png`, `shoppilot-after-hero-1440.png` |
| Hairline (8%) panels on graphite; one top-edge highlight | Soft grey shadow under every card | `resend-1440-s4.png`, `linear-1440-s0.png` |
| Light falling on surfaces: sheen, edge, a faint lamp | Coloured radial glows, mesh, gradient text | `resend-1440-s1.png` (edge light on the panel top) |
| Bright sentence + grey continuation in one heading | Kicker label above the heading | `linear-1440-s1.png` |
| Money set precisely, cents smaller | Big amber numbers everywhere | `mercury-1440-s3.png` |
| Footage with a measured scrim, UI floats on it | UI baked into the footage, or text on unscrimmed video | `mercury-1440-s0.png` |
| Neutral morning band to close | Saturated colour field to close | `shoppilot-after-closing-1440.png` |

## 6. Copy voice

Precise, short, concrete. Say what happens, with the real number.

| Rule | Example |
|---|---|
| h1 8 words max, sub 16, h2 6 (+ a grey continuation of 10 at most), feature body 25, button 3 | "Autopilot for your shop. You approve every dollar." |
| Real demo numbers as numerals; money with cents | "$24.00 waits for your approval", "5 steps, 1 needs your approval", "21:52" |
| Name the action and keep the name through the flow | "Run approved steps" then "Run complete"; "Undo" then "Undone" |
| Honest labels | "Demo store", "Stripe test mode", "Planned", "pending W3"; no logos, testimonials or metrics we do not have |
| Sentence case; no exclamation marks; no em or en dashes; no "→" after link text; caps only on the BLOCKED stamp | "Blocked. Every email is screened before the planner sees it." |

Never: elevate, seamless, unleash, cutting-edge, revolutionize, supercharge, effortless, magic, powerful, robust, next-gen, game-changing, empower, unlock, streamline, transform, delightful, world-class, AI-powered, "simply", "just".

## 7. Checks before you ship

1. `node scripts/check-contrast.mjs` after any token change.
2. `npx astro build`, then `scripts/check-overflow.mjs` and `scripts/weigh.mjs` (0 console or CSP errors) against a server that sends the real CSP.
3. Grep your page CSS for `#` and `rgba(`: only tokens, `rgb(var(--n-bg-rgb) / x)` scrims and black shadow alphas.
4. `npm run build:app` writes `../app/static`; nothing else under `app/` is ours.
