# ShopPilot+ frontend: final build notes (2026-10-31)

## Run it
- **Dev:** `cd shoppilot/web && npm run dev` → http://127.0.0.1:4321. `/api` and `/healthz` proxy to a backend on :8010.
- **Backend:** `cd shoppilot && LLM_MODE=replay uv run uvicorn app.main:app --port 8010`.
- **Production:** `cd shoppilot/web && npm run build:app` writes the site into `shoppilot/app/static/`. FastAPI already serves it with `StaticFiles(html=True)`, under its CSP headers.

## Theme decision: "night to morning"
The user picked R3-A (Dark premium) and asked for their Veo clip, which has 2 scenes: a dusk desk with an amber lamp, then a bright morning shelf. The page follows that story.

| Decision | Why (skill) |
|---|---|
| Warm-dark espresso #14100c, not pure black | The footage is walnut, kraft and amber. Pure black fights it. taste v1: "no pure black", one warm grey family, no mixing warm and cool |
| Top half night, bottom half cream #f7f1e7 | The video is literally night, then morning. The page turns from the problem (Sunday night) to the result ("Monday morning: done.") at the scene-2 band. awwwards: the concept comes from the subject's own world |
| One accent: approval amber #f5b544 = money | It already matched the lamp. ui-unified floor 20 (one accent); frontend-design (spend boldness in one place) |
| Console, How it works and Report on cream with a night header band | The console is projected for the live demo (30% of the grade), so the light surface is more legible. ui-unified conflict 6: theme from the use scene. The night band keeps the hand-off from the dark hero |
| Two surfaces, one token set (`.night` / `.morning` re-point the same variables) | ui-unified "one theme per page", read as one palette family with section surfaces. Every text pair was checked: lowest is 4.66:1 |

## Video use
| Clip | Source range | Files (`web/public/media/`) | Size |
|---|---|---|---|
| Night loop (hero) | 6.0 to 12.0 s, lamp on, no hands, 0.5 s crossfade seam | `night.mp4` / `night.webm` | 631 kB / 279 kB (cap 1.5 MB) |
| Morning loop (dawn band) | 22.0 to 28.0 s, crossfade seam | `morning.mp4` / `morning.webm` | 630 kB / 302 kB (cap 1.2 MB) |
| Posters | first frames | `night-poster.avif` / `.webp`, `morning-poster.avif` / `.webp` | 13 / 23 kB, 9 / 17 kB (cap 60 kB) |

- All clips are 1280x720 at 24 fps with no audio.
- Attributes: `muted playsinline loop preload="metadata"`, with a visible Pause button (aria-pressed) and a CSS-only pause fallback.
- Each video plays only while it is on screen (IntersectionObserver). The morning video loads only once it scrolls into view.
- `prefers-reduced-motion`: the `<source>` tags carry a media query, so no video downloads. The posters show as CSS backgrounds.
- A warm gradient scrim keeps text at 5.29:1 or better, measured on the brightest pixel behind each text box across 24 frames.
- The footer says "Background footage is AI-generated (Google Veo)." No UI appears in the video.

## Routes (production build: 4 pages + 404)
| Route | What |
|---|---|
| `/` | Landing with A's layered product hero over the night video: built-with strip, problem, walkthrough loop, safety, dawn band with the morning video, bento, proof, planned pricing (labelled simulation), FAQ, closing |
| `/app/` | The full console on the real API, plus fixture mode (`?fixtures=happy\|invalid\|clarify\|ratelimit\|llmdown\|fail\|slow\|empty\|mock`) |
| `/how-it-works/` | Pipeline and architecture SVGs, the 4 layers with code paths, a 10-step walk through one request, 14 prompt-engineering techniques mapped to real files, safety rails, the ML methods |
| `/report/` | Tests, guard, eval, ML backtest and costs. Every number has a source; anything unmeasured says "pending W3". Video poster that links out (link pending), deliverables checklist |
| `/404.html` | Designed not-found page |

Rounds 1 to 3 (`mockups`, `v2`, `v3`) moved to `web/src/pages/_lab/`. Astro skips `_` folders, so they are left out of the build. Their old fixture moved to `web/lab-public/`. All of it is still in git history.

## Checks (2026-10-31)
| Check | Result |
|---|---|
| HTTP | `/`, `/app/`, `/how-it-works/`, `/report/` all 200, on both dev and :8010 |
| Overflow (`scripts/check-overflow.mjs`, scrollWidth vs clientWidth) | 15 of 15 OK (4 pages + 404 at 390, 1440 and 1920) |
| Landing word count (`scripts/count-words.mjs`) | 211 of 220 (h1 8, sub 15) |
| CSP scan of `app/static` | 0 inline scripts, 0 `<style>` tags, 0 `style=` attributes, 0 external URLs, 0 `innerHTML` in bundled JS |
| CSP at runtime (served by FastAPI with its real CSP header) | 0 console errors or violations on all 4 pages at 1440 and 390 (`scripts/weigh.mjs`) |
| Landing weight, first load, cache off | 514 kB in 10 requests: video 273 kB (webm), fonts 136 kB, CSS 40 kB, HTML 40 kB, posters 23 kB, JS 1 kB. Reduced motion: posters only |
| Other pages | `/app/` 262 kB (JS 29 kB, 10.7 kB gzipped), `/how-it-works/` 221 kB, `/report/` 200 kB |
| Console end to end (`scripts/e2e-console.mjs`) | 25 of 25 pass. Against the backend: boot, chip, the replay error UI (`replay_miss` 404), reset. On `?fixtures=happy`: plan, See it, injection shown as text, refund unchecked + Irreversible, run 4 of 4, audit refetch, Undo on the PO, no Undo on refunds |
| Fixture scenarios | 9 of 9 captured: `review/final/console-fx-*.png` |
| Lighthouse | Not run. The chrome-devtools MCP cannot find Chrome (it expects `/opt/google/chrome/chrome`). Run it on the deployed URL instead |
| Screenshots | `web/review/final/`: `<page>-hero-{1440,390}.png` and `<page>-tall-{1440,390}.png` |

## Backend requests (for the W3 workflow; nothing was edited under `app/`)
1. **Replay recordings:** `app/llm/recordings/` does not exist, so `POST /api/plan {replay:true}` returns 404 `replay_miss` for all 3 chip prompts ("Sunday cleanup", "Stockout check", "WISMO replies"). The demo fallback needs them.
2. **Guard recordings:** in replay mode the clean inbox emails come back as `guard_error`, so 4 of 5 emails show BLOCKED. The damaged-mug email is blocked too, which makes the real Sunday-cleanup refund fail validation.
3. **`send_email` preview:** shows "shipped via ." with a blank carrier.
4. **Optional:** `clarify.options` is always empty. The UI renders option buttons if they arrive.
5. **Dockerfile Node stage:** Node 22.23.4 or newer (Astro 7.4.4 engines field; Node 24 LTS is fine). Run `cd web && npm ci && npm run build:app`, then copy `app/static`. `StaticFiles(html=True)` is already mounted, and `404.html` is picked up automatically.
6. **Generated output:** `app/static/` is now build output. Either commit it on purpose or gitignore it and build it in Docker. Pick one.
7. **Optional cache headers:** `Cache-Control: public, max-age=31536000, immutable` for `/_astro/*`, and a long max-age for `/media/*`.
8. **CSP:** no change needed. `default-src 'self'` already covers same-origin video, posters and fonts. Do not add `media-src`.
9. **Test suite:** the report shows 662 passed and 7 failed, but that run happened while backend files were being edited. Re-run it when stable and update `web/src/data/report.ts` (`tests`).

## Pending inputs (one-line changes in `web/src/data/site.ts`)
- `links.repo`, `links.video` (YouTube), `links.deployed`. The report and footer switch from "pending" to links automatically.
- Eval results, measured cost per plan, the live guard column: `web/src/data/report.ts`.
