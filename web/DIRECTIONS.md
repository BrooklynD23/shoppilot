# ShopPilot+ visual directions (phase 1)

Pick one direction, then the 4 pages (Landing, Agent console, How it works, Report + links) get built in that world.

- Review index: http://127.0.0.1:4321/ (dev server: `cd shoppilot/web && CHOKIDAR_USEPOLLING=1 npx astro dev --host 127.0.0.1 --port 4321 --ignore-lock`)
- Static fake data: `src/data/demo.ts` (shapes from specs 00 §7 and 06 §3).
- Recommendation: **C, Build Book**. A (Carton) is the runner-up. Reasons are at the bottom.

## Side by side

| | A. Carton | B. Label | C. Build Book |
|---|---|---|---|
| How it was chosen | impeccable direction roll (assigned) | impeccable's own top pick (risk: familiar e-commerce trope) | catalog challenger, won on product clarity |
| World | Side panel of a corrugated shipping carton in a maker's packing room | A 4x6 direct-thermal shipping label coming off a roll | A construction-toy assembly booklet (generic, no brand marks) |
| Rationale | Shop owners spend their day in this room. The page is the box: the request form is a label slapped on it, handling marks map to tool flags (fragile glass = moves money, umbrella = screened, return arrow = undoable), clear tape seals an approved step and red tape refuses the injection email. Strongest mood and brand voice. | Every unit of work is a printed label: zones split by heavy rules, a routing block for the headline, barcodes, and an inverse black block for money like a service-code box. The console is the most legible of the three, but shipping-label styling is a known look in this category. | An agent plan is assembly instructions: numbered steps, a parts inventory (the 5 tools), 1:1 call-out boxes for money, the old state ghosted and the new state bright yellow with an arrow. The injection email is a "piece that does not fit". The world explains the mechanism without extra words. |
| Display type | Big Shoulders Stencil (box stencil) | Archivo, width 62, weight 850 to 900 | Red Hat Display 900 |
| Body type | Atkinson Hyperlegible Next | Archivo, width 100 | Red Hat Text |
| Mono (IDs, tool names only) | Atkinson Hyperlegible Mono | JetBrains Mono | JetBrains Mono |
| Light tokens | board #c69c6d, print #1c140c, muted #33240f, label #f7f4ee, tape red #b3261e, green #1f6b34 | liner #efe6cf, stock #ffffff, print #000000, grey #3d3d3d, red #b3261e, green #1f6b34, money block #000 on #fff | page #a9d8f2, ink #0b1620, muted #1e3a4d, call-out #ffffff, new part/money #ffc915, red #b3261e, green #1f6b34 |
| Dark tokens | board #2a2018, print #efe3cf, label #1e1913, red #e0574d, green #5fbf7a | liner #17150f, stock #0f0f0f, print #f4f4f0, red #ef6a5f, green #5cc27a | page #0e2a3d, ink #e7f3fb, call-out #12344b, yellow #ffd23f, red #f47a70, green #63c983 |
| Lowest text contrast (measured by builders) | muted ink on board 5.98 (light). Red text never sits on kraft (only 2.92). | dark red on stock about 5.8 | dark red on dark call-out 4.86 |
| Landing signature | Clear tape runs across the request label and seals it (scaleX, 700 ms) | The hero label prints top to bottom (clip-path, steps(18), 900 ms), then feeds up 6 px | The top block drops along its dashed arrow and seats flush (600 ms + 2 px settle) |
| Idle motion | One glint along the tape, 7 s loop | None (decision: a calmer page) | Guide-arrow dashes creep, 8 s loop |
| Console motion | 150 ms state feedback, press scale .97; tape seal follows the checkbox via `:has()`, no JS | 150 ms colour feedback, press scale .97 | 150 ms feedback, press scale .97 |
| Reduced motion | Tape shown sealed, no glint | Label shown printed | Block seated, dashes still |
| Font cost (Latin woff2) | 89 KB (3 files) | 130 KB (2 files) | 101 KB (3 files) |
| JS | 0 | 0 | 0 |
| Risk | Mid-tone kraft loses contrast on a washed-out projector; heaviest-looking console | Looks like other shipping tools; the "SUN" routing block reads oddly | Can read as playful for a money tool; must stay clear of toy-brand trade dress |

CSP check on a production build (`npx astro build`, 7 pages): 0 inline scripts, 0 `<style>` tags, 0 `style=` attributes, 0 external URLs, 0 JS files. Fonts are self-hosted from `@fontsource-variable/*`, so `default-src 'self'` covers them and no Google Fonts CSP entries are needed.

## Screenshots (`shoppilot/web/review/`)

| Direction | Desktop 1440 | Phone 390 | Extras from the builders |
|---|---|---|---|
| A Carton | `a-landing-1440.png`, `a-console-1440.png` | `a-landing-390.png`, `a-console-390.png` | `a-*-320.png`, `a-dark-landing.png`, `a-dark-console.png` |
| B Label | `b-landing-1440.png`, `b-console-1440.png` | `b-landing-390.png`, `b-console-390.png` | `b-*-320.png`, `b-console-1440-dark.png` |
| C Build Book | `c-landing-1440.png`, `c-console-1440.png` | `c-landing-390.png`, `c-console-390.png` | `c-*-320.png`, `c-dark-landing.png`, `c-dark-console.png` |

## Challengers the roll dealt and declined (kept for the record)

| Challenger | Verdict | Discipline borrowed |
|---|---|---|
| Algorave live-code floor | declined | the upcoming change is visible before it runs (the dry-run diff) |
| VU meter bridge | declined | cost meter values never jump; they settle |
| 19th-century lexicon page | declined | guide words: the plan heading names the span in view |
| Tanaka plane portrait | declined | none needed |
| Glazier colour-field partition | competitive (clarity) | colour is reserved for "what matters now": money and BLOCKED only |

## Recommendation: C, Build Book

1. **The world is the mechanism.** Plan, check, approve, run is literally a numbered build. Graders read it in seconds, which serves the problem (10%) and UI (10%) criteria with no extra copy.
2. **It works from the back of a room.** Sky blue, black keylines and yellow money call-outs survive a projector better than kraft (A). Demo is 30%.
3. **The injection story explains itself.** A red-crossed piece that does not fit makes the guard visible without a lecture.
4. **Money stands out.** Every dollar sits in its own yellow 1:1 call-out, which matches "shows every change and dollar".
5. **Cost is moderate.** About 101 KB of fonts and zero JS. It also extends cleanly to "How it works" (a full instruction booklet) and "Report" (the parts list and the build log).

Pick A instead if you want maximum brand mood and award feel on the landing page, and you accept a heavier console.
