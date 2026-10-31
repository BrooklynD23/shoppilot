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
| `/` | Landing over the night video: layered plan + approval hero, Sunday-night problem (labelled Reddit quote + inbox), the seven-agent team room with its night-shift log, safety (hard caps + the blocked email), dawn band with the morning video and run receipt, Forecaster bento, planned pricing (labelled simulation), FAQ, closing (round 4) |
| `/app/` | The console on the real API: team stage (7 mascots, 3D), one request bar, the plan with the approval moment; inbox, outbox, audit, team log and guide in a drawer. Fixture mode `?fixtures=happy\|invalid\|clarify\|ratelimit\|llmdown\|fail\|slow\|empty\|mock\|trace` (`trace` = the proposed agent trace, docs/specs/09) |
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

## Console team stage (2026-10-31, console team)
| What | Where |
|---|---|
| Layout | One 960 px column: heading, team stage + request bar (one card), plan. Inbox, outbox, audit, team log and the graders' guide moved into a native modal `<dialog>` drawer (`components/console/Drawer.astro`), closed by default |
| Cast (each one real module) | Guard (bell, `inbound_guard.py`), Router (pebble + signpost, `route()`), Planner (notebook, `planner.py`), Forecaster (glass globe, `ml/forecast.py`), Validator (rubber stamp, `validator.py` + `policy.py`), Judge (egg in glasses, `judge()`), Executor (drawer that prints receipts, `executor.py`). Data: `scripts/console/agents.ts`; materials `--mat-*` in `tokens.css` |
| 3D | `scripts/console/stage3d.ts`, three.js 0.186.1 (npm, bundled). `import()`ed only on `/app/`, only with WebGL2, no reduced motion and a stage at least 800 px wide (`STAGE_3D_MIN_PX`, `agents.ts`; review round 2), from an idle callback after boot's API calls. 149.5 kB gzipped (budget 220). 67 draw calls, 41.6k triangles, DPR capped at 2 and stepped down on slow frames, about 30 fps when calm, paused off screen and below 800 px |
| Fallback | `components/console/Portrait.astro`: 2D SVG portraits with the same silhouettes and state words (phones, no WebGL, reduced motion, before 3D loads). The hand-over crossfades: the canvas fades in while the portraits fade out in place (`data-gl`), then the names move (`data-mode="3d"`) |
| Honest choreography | `scripts/console/team.ts`. In flight: Router reads, Planner drafts. On return: replays only fields in the response (`usage.calls` stages and ms, `blocked_inputs`, `validations`, forecast in `diff`, `plan.judge`), or the proposed `trace` when present. Execution: each real `POST /api/execute` drives the Executor; `error == "invalid"` is shown by the Validator |
| Frame log | `window.__stageStats()` (rAF gap, main-thread ms per frame, draw calls); `?fps` logs it every 5 s |

Checks (production build served with the backend's exact CSP, `/api` proxied to :8010): e2e 40 of 40 (`scripts/e2e-console.mjs`, backend error path, fixtures full flow, trace), 10 of 10 fixture scenarios plus overflow with plan, run log and open details at 390/1440/1920; `check-overflow.mjs` 6 of 6; 0 CSP violations in full flows with the 3D live; 0 inline scripts, `<style>`, `style=`, external URLs, `innerHTML` or `eval` in the build; contrast gate 57 of 57. Frames: headless Chrome here only has SwiftShader or llvmpipe (no GPU), which renders 4 to 9 fps; our main-thread work is 1.6 to 2.9 ms per frame on average. Run `window.__stageStats()` on real hardware for the true fps. Shots: `review/console-team/`.

Backend requests from the console team:
1. Implement the agent trace (`docs/specs/09-agent-trace.md`). The UI already reads it.
2. Compress static files: `app.add_middleware(GZipMiddleware, minimum_size=1000)` (or precompressed assets). The 3D chunk is 590,653 B raw, 149,488 B gzipped. Still open after review round 2: `/app/` at 1440 transfers 625 kB of script uncompressed (phones 48 kB). Re-check with `WAIT=7000 node scripts/weigh.mjs app=http://127.0.0.1:8010/app/`.
3. Rebuild `app/static` with `npm run build:app` once the landing team is done.

## Console review round 1 fixes (2026-10-31)
| Finding | Fix |
|---|---|
| 390 px 3D stage less legible than 2D, 86 px jump, blank fade-in | Stages under 560 px keep the 2D portraits and never fetch the 3D chunk; long state words wrap instead of clipping. The narrow follow-cam code is gone. On wide stages the canvas crossfades over the portraits, timed by `transitionend` |
| Approval not actionable from the run bar | "Review the $26.00 refund" in the bar scrolls the refund row to the centre and focuses its checkbox; it hides once nothing waits |
| Blue checkboxes | `accent-color: var(--ink)` moved from `html` (where `--ink` is undefined) into `.night` / `.morning` in `tokens.css` |
| Bar still says "Money out if you run" after the run | Done state: "Run complete. Refunded $26.00 (Stripe test mode)" + Open audit, no longer sticky (`data-done`) |
| Three different blocked counts on the replay backend | `verdicts()` in `render.ts` (held = `guard_error`) feeds the bar ("1 blocked, 3 held"), the HELD / BLOCKED stamps, Guard's words and the plan replay. Guard's dot keeps the verdict through every mood (`data-flag`), never a green OK |
| Labels snapping ahead of the eased camera | Labels project from the live camera every frame it moves |
| Weight, eager import, continuous render | 3D loads after boot from `requestIdleCallback`; every other frame is skipped when calm. Gzip is still a backend request (above) |

Checks: e2e 49 of 49 on the FastAPI build (`scripts/e2e-console.mjs`, now also asserts one inbox count, the Review button, the done bar and phone 2D), overflow 15 of 15, contrast 57 of 57, CSP scan 0 of each, 0 CSP violations at 1440 and 390. Shots: `review/console-r1-fix/`.

## Console review round 2 fixes (2026-10-31)
| Finding | Fix |
|---|---|
| The run happened off screen (stage at -1272 px while Executor ran), so the 3D loop slept through it | Run and "Retry from here" always scroll the team back into view (`showTeam()`, `console.ts`); the sticky run bar stays below it. Always, not "if off screen": that check raced a Review scroll still in flight. Plus the ambitious option: a mini team strip under the header (`#strip`, `app/index.astro`), shown while the team replays or runs and the stage is under 40% visible, 700 ms after scrolling settles (so the scroll back never flashes it). It copies the roster's `data-mood/flag/money` with one MutationObserver and the current line from `say()`. `aria-hidden`, no focusable content, no motion when reduced |
| 3D labels overlapped at 560 to 760 px stages | `STAGE_3D_MIN_PX` 560 to 800, measured: at 760 the outer mascots sit 94 px apart and "Waiting for you" next to "Warning" needs 95; at 800 the tightest real pair clears by 3 px, at 960 by 21. The 2D 4 + 3 grid now switches on stage width (`@container brief (width < 800px)`), and both gates read the unrounded width. Long words were shortened to fit: Judge "No review" (was "Unavailable"), Executor "None approved" (was "Nothing approved"). 2D words wrap instead of clipping at every width, with portraits kept level |
| Validator's last pill showed only the last step ("4 passed", green) with a blocked step 2 | `tally()` in `team.ts` adds a closing Validator beat after its last one, from the plan's own validations: "1 of 5 blocked" and "4 of 5 steps pass. 1 blocked step cannot run." It sets `data-flag="blocked"`, so the dot stays red through the run and the cheer. "4 passed, 1 blocked" was 137 px, wider than a 3D label |
| Fixtures said "Stripe test mode" over a `[MOCK]` receipt | `session.json` and `store.json` now say `"stripe_mode": "mock"` |
| Replay server showed "Run: python -m tests.eval.record" and "Try Plan it for a live plan" | When `llm_mode` is `replay`, a plan `error` or a `replay_miss` shows one line: "This demo server only has recorded plans for the three examples. Pick one, or open the offline fixtures." For an example with no recording, it says "This demo server has no recording for this example yet. Open the offline fixtures to see the whole flow." Both retry buttons hide, because they would replay the same miss, and Open offline fixtures shows. Planner's bubble uses the same line. The raw server text stays in the team log only |
| Console bar grew from 1 row to 2 after the first plan | The meter reads "AI $0.0105 · 56% cached", with the tokens in its tooltip. `#cost-meter` also shrinks first, with an ellipsis, so a long inbox count ("1 blocked, 3 held") never pushes the actions to a second row: 53 px before and after a plan at 1280, 1366, 1440 and 1920, on both the backend and fixtures |
| 623 kB of uncompressed script at 1440 | Backend item, still open (request 2 above). Skipped the optional "import when the stage is near the viewport": the stage sits at the top of `/app/`, so it would load on arrival anyway |

Checks (production build served by FastAPI with its real CSP, `/api` on the replay backend): e2e 58 of 58 (`scripts/e2e-console.mjs`, now also asserts no developer command in the replay error, the team in view after Run, the strip, Stripe mock, the Validator tally with the blocked step moved to position 2, and 2D 4 + 3 at 390 and 768); fixture scenarios 10 of 10 plus overflow with plan and run log at 390/1440/1920; `check-overflow.mjs` 15 of 15; contrast 57 of 57; CSP scan 0 inline scripts, `<style>`, `style=`, inline handlers, `innerHTML` or `eval`; 0 console errors at 1440 and 390 (`weigh.mjs`). Label clearances measured in 3D at stages 800, 828, 883 and 960 for the happy and invalid plans (approval, ticked, running). Strict `tsc` on the console scripts: 0 errors outside the untyped three.js import. Shots: `review/console-r2-fix/`.

## Round 4: integrated QA (2026-10-31, after the brand, landing and console teams)

**Verdict: GO to show the user.** Caveat: on the replay server, Plan it answers "no recording" for all three chips (backend request 3), so show the full flow on `/app/?fixtures=happy`. The 3D stage needs a real GPU to look smooth.

### What changed in round 4
| Team | Change |
|---|---|
| Brand | `BRAND.md` + `src/styles/tokens.css`: graphite and tissue neutrals, amber only for money awaiting approval, Mona Sans + JetBrains Mono only, one radius and elevation scale, light-only gradients. Contrast gate: `scripts/check-contrast.mjs` |
| Landing | New sections and copy (Routes table above). New `TeamRoom.astro` (the seven agents and the night-shift log). `Walkthrough.astro` and `Receipt.astro` removed |
| Console | Team stage with 7 agents in 3D (three.js) and 2D portraits as fallback, one request bar, a drawer for inbox, outbox, audit, team log and guide, the mini team strip, trace replay (sections above). `Rail.astro` removed |
| Size | 34 tracked files under `web/src`, `web/scripts`, `web/public` (+1,514 / -1,464 lines) and 12 new files (2,433 lines). All uncommitted |

### QA fixes (web/ only)
| Found | Fix |
|---|---|
| `/app/` h1 at 390 broke as "Your team is / in. Say what needs doing." (`text-wrap: balance` with the inline-block grey continuation) | `.deck-h { text-wrap: wrap }` in `page-console.css`. Now "Your team is in. / Say what needs doing." |
| Trace cap mismatch: spec 09 lets the backend send 60 events, and the UI kept the first 40, so a long trace lost the Judge's verdict and "Plan ready" | `readTrace()` in `team.ts` keeps the first 37 and the last 3. New e2e check with a 50-event trace |
| The audit count raced the inbox screen ("Audit 1" or "Audit 2" for the same fresh store), because screening the inbox writes `guard_block` | Boot and reset load the audit after the inbox (`console.ts`) |
| `/report/` was stale: "662 passed, 7 failed", eval "22 cases, runner not written", "no evaluate script in app/ml/" | `data/report.ts` + `pages/report/index.astro`: the 09:31 run with its one failure named; eval 24 cases, gate 22 (c23 and c24 are the two other chips); runner and cases exist, recordings do not; `app/ml/evaluate.py` exists but is not run here |
| The :8010 process (started 02:54) still answered `guard_error` for 3 clean emails, so the console said "1 blocked, 3 held" | Restarted it at 09:28 (`LLM_MODE=replay .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010`). It runs the working tree as of 09:28: ad293b5 plus the backend's uncommitted edits (gzip is active). Clean emails are `heuristic_only` (allowed) and the bar reads "1 blocked". No code change |

Scripts: `shoot-full.mjs` and `shoot-scrolls.mjs` take `REDUCED=1` (prefers-reduced-motion). `e2e-console.mjs` adds a keyboard-only pass (7 checks), the 50-event trace check and `SHOTS_DIR` (default `final`).

### Checks (production build in `app/static`, served by FastAPI on :8010 with its real CSP, `LLM_MODE=replay`)
| Check | Result |
|---|---|
| Build | `npm run build:app`: 5 pages, 52 files |
| Screenshots | `review/final-v2/`: `<page>-tall-{1440,390}.png` for landing, app, how, report, 404; `landing-hero-{768,1024}-s0.png`; reduced motion `landing-reduced-{1440,390}-s{0,1,2}.png` and `app-reduced-{1440,390}.png`; console states `console-fx-*.png`, `console-plan-run-390.png`, `console-e2e-*.png` |
| Overflow | 15 of 15 at 390/1440/1920 (4 pages + 404), 16 of 16 at 320/768/1024/1280 (4 pages), 3 of 3 with plan, run log and open details |
| CSP scan of the build | 0 inline scripts, 0 `<style>`, 0 `style=`, 0 inline handlers, 0 `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`, 0 `eval`/`new Function`, 0 `setAttribute('style')`. One URL string, `https://jcgt.org/...`, sits in a three.js shader comment and is never fetched |
| CSP at runtime | 0 console errors or violations on all 4 pages at 1440 and 390 (`weigh.mjs`). The 404 page logs only its own 404 status |
| Weight, first load, cache off | Before the restart (no gzip): `/` 508 kB in 10 requests (video 273, fonts 136, HTML 42, CSS 32, posters 23, JS 1); `/app/` 890 kB at 1440 (script 625, fonts 96, API JSON 95), 312 kB at 390; `/how-it-works/` 224 kB; `/report/` 202 kB; 404 114 kB. After it (gzip from the working tree): `/` 452 kB, `/app/` 295 kB at 1440 (script 164; the 3D chunk 590,653 B is served as 149,007 B) and 148 kB at 390, `/how-it-works/` 157 kB, `/report/` 165 kB. Video and posters are not compressed, as intended |
| Console e2e (`e2e-console.mjs`) | 67 of 67: backend error path, fixtures full flow, trace, 50-event trace, validator tally, 2D at 390 and 768, keyboard |
| Fixture scenarios (`SHOTS_DIR=final-v2 node scripts/e2e-console.mjs <base> --shots`) | 15 of 15: the 10 scenarios with 0 JS errors, the slow counter and Cancel, overflow with plan + run log + open details at 390/1440/1920 |
| Keyboard on `/app/` (Tab, Enter, Space only) | First Tab is the skip link. 13 more Tabs reach the "Sunday cleanup" chip, 4 reach Plan it, 9 go from the Plan heading to the $26.00 refund checkbox (Space approves), 1 reaches Run approved steps (Enter runs). 28 focus stops, each with a 2 px outline |
| Contrast gate | 57 of 57 |
| Landing words | 154 copy words (budget 180); h1 8, sub 14 |
| Links | 90 internal links and assets on 5 pages, all 200, every `#anchor` exists. The 3 `/api/export/*` links answer 401 without a session cookie, as intended |
| Pricing claim | How it works says cache reads cost $0.10 per million tokens on Sonnet 5.5 instead of $2.00. That matches the platform.claude.com pricing page today (0.05x on Sonnet 5.5) |
| Backend suite (read-only run) | 762 passed, 1 failed, 26 skipped, 16 deselected in 347 s (09:31, ad293b5 plus the uncommitted trace and gzip work) |

### Open issues (frontend)
1. The 3D frame rate is unmeasured on a real GPU (SwiftShader here: 4 to 9 fps). A capture taken mid-crossfade shows the 2D portraits fading under the canvas; after 20 s the hand-over is complete (`app-tall-1440.png`). Run `window.__stageStats()` on the demo laptop.
2. Demo numbers differ between pages: the landing forecast says "Black Speckle Mug, 31 on hand, 3 to 5 days", How it works says "9 on hand, 3 to 6" (`data/demo.ts`, Lavender tin) and walks a 6-step plan where the landing shows 4. Each is labelled demo or illustration. Unify once real recordings exist.
3. Gzip works only in the backend's uncommitted working tree. Until it is committed and deployed, `/app/` sends 625 kB of uncompressed script on stages of 800 px or more (backend request 4).
4. Lighthouse still not run (the DevTools MCP cannot find Chrome).
5. 7 orphaned headless Chrome processes from earlier rounds (oldest about 6.5 h) are still running and slow SwiftShader timing here. Left alone, because this QA did not start them.

### Backend requests, round 4 (nothing edited under `app/`)
1. **Agent trace (spec 09): in progress** in the working tree (`planner.py`, `models.py`, `main.py`, `tests/agent/test_trace.py`, uncommitted at 09:30). Contract against the UI (`readTrace()` in `team.ts`): top-level `trace` matches, fields `agent/event/detail/t_ms/step_id` match, the 10 event names match, `detail` is at most 160 chars of plain text, cap 60 (the UI keeps the first 37 and the last 3). Asks: (a) emit the plan-ending events (Judge verdict, Planner `done`) last; (b) keep `t_ms` non-decreasing, because pacing uses last minus first; (c) no Executor events are needed, the UI drives the Executor from `/api/execute`; (d) a trace only arrives with a plan, so the replay server also needs request 3.
2. **Guard replay: fixed in ad293b5, one gap left.** After the restart, clean emails are `heuristic_only` (allowed) and the inbox reads "1 blocked". Gap: `heuristic_only` verdicts are not stored, and `_plan_context()` (`app/agent/validator.py:231`) treats every email without a stored `allowed = 1` row as blocked. So in replay, a refund citing E001 or a WISMO reply citing E003 fails validation while the inbox shows both emails as Allowed. Pick one: count in-memory `heuristic_only` verdicts as allowed evidence, or store them with a label that is re-screened once a recording exists.
3. **Plan recordings:** `app/llm/recordings/` is still absent, so all 3 chips return `replay_miss` on the replay server and the 24 eval cases skip. Record them with a key (`uv run python -m tests.eval.record`) and commit them.
4. **Gzip: works, not committed.** `GZipMiddleware(minimum_size=1000)` from the working tree took `/app/` at 1440 from 890 kB to 295 kB (3D chunk 590,653 B raw, 149,007 B on the wire; `tests/test_gzip.py` is new). Commit it and re-check on the deploy with `WAIT=7000 node scripts/weigh.mjs app=<url>/app/`.
5. **Restart the server after pulling.** The 02:54 process kept serving the old guard behaviour for 6.5 h. The :8010 server now running was started by this QA at 09:28 from the working tree; restart it once the trace and gzip work is committed.
6. **Test flake:** `tests/test_sessions.py::test_concurrent_create_respects_cap` fails with sqlite3 "disk I/O error" on the WSL `/mnt/c` drive. Re-run on a Linux filesystem or in CI, then update `tests` in `web/src/data/report.ts`.
7. **`app/static`:** the Dockerfile now builds `web/dist` into it, so the local copy is build output. Gitignore it or commit it on purpose (still open from the first request list).
8. Not re-checked: the blank carrier in the `send_email` preview ("shipped via ."). It needs a plan on the server.
