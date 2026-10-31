# 02 — Motion tools for the ShopPilot+ landing page

Researched 2026-10-30. Demo 2026-11-05 (6 days). Budget 0–30 USD.
Stack constraints: Astro static build served by FastAPI on the same origin; CSP `default-src 'self'; script-src 'self'` (no CDNs, no inline scripts); Render free tier (5 GB/mo bandwidth).

**Source labels.** "Official" = fetched from the vendor's own page on 2026-10-30. "3rd-party" = an aggregator or blog. Its numbers conflict across sources, so re-check the vendor page before you pay. Prices are USD per month unless noted.

---

## TL;DR

1. **Hero loop:** generate one 5–8 s abstract or product-mood clip with **Google Flow (Veo 3.1)**. Free for students for 1 year via Google AI Pro, otherwise $19.99. **Fallback:** Kling free daily credits for drafts plus 1 month of Standard (about $7–10) for a watermark-free final. Then transcode to H.264 MP4 **≤ 1.5 MB** plus WebM plus an AVIF/WebP poster.
2. **Product walkthrough:** record the **real ShopPilot+ UI**. Use Screen Studio (macOS, $29 for 1 month) or free OBS/ShareX, then export MP4. **Do not** embed Arcade, Supademo or Storylane iframes, because they break `default-src 'self'`.
3. **Micro-interactions:** native CSS (scroll-driven animations at about 88% support, View Transitions at about 93%) plus **Motion** `animate` mini (3.2 kB, bundled by Astro). Add GSAP (free, including all plugins) only if you need SplitText or complex timelines. **Skip** Lottie, Rive and Spline. Their WASM needs `'wasm-unsafe-eval'` and adds time.
4. **Higgsfield verdict:** usable but not the best buy. It is an aggregator (Kling, Veo, Sora 2, Seedance, Hailuo, Wan) plus its own DoP and Soul models. The Free tier has 0 credits, no video and a watermark. Starter at $19 (270 credits) gets Kling 3.0 at 720p only. For the same $19–20, Google AI Pro gives 1,000 Flow credits of Veo 3.1 at 1080p (or $0 with the student offer).
5. **Total realistic cost: $0–30.** Typical: $0 Veo (student) + $0 OBS + $0 CSS/Motion = **$0**. Worst case: $19.99 Google AI Pro + $9 Kling = **about $29**.

---

## 1. AI video and image generators (hero loops, product films)

### 1.1 Comparison

| Tool | What it is (Oct 2026) | Free tier | Cheapest paid | Watermark / commercial | Output | Best use for a SaaS landing | Source |
|---|---|---|---|---|---|---|---|
| **Higgsfield** | Aggregator plus own models. Video: Seedance 1.5–2.5, Kling 2.1–3.0/Omni, Sora 2/Pro/Max, Veo 3/3.1, Wan 2.2–3.0, Hailuo 02/2.3, Grok Video, DoP (own). Image: Nano Banana / 2 / Pro, GPT Image, FLUX.2, Seedream, Reve, Soul / Soul 2.0 (own). Tools: Cinema Studio, Marketing Studio, Speak, UGC builder. | $0, 0 credits, images on 2 models only, **no video** | **Starter $19**, 270 credits/mo, Kling 3.0 at 720p, Seedance 2.0 Fast/Mini, DoP. Plus $47 (annual) / $59 (monthly), 1,200 credits, all models, 1080p | Free = watermark that cannot be removed. Paid = no watermark. Commercial use: the pricing table says "not on Free", but the Help Center (updated 2026-09-12) says the ToS does not tie it to a plan. The ToS bans using outputs to train AI models. Credits do not roll over. | Kling 3.0 720p ≈ 7 cr / 5 s, Veo 3.1 720p ≈ 29 cr / 4 s, Sora 2 720p ≈ 10 cr / 4 s | Camera-move presets ("cinematic" pushes, orbits) for a stylised hero. Good for social/UGC ads. Overkill for a loop. | 3rd-party (Krea, pricing captured 2026-09-14); official Help Center |
| **Runway** | Gen-4.5, Gen-4/Turbo, Aleph 2.0, plus hosted Kling 4.0, Seedance 2.0 Pro, Nano Banana Pro | 125 one-time credits | Standard $15 ($12 annual), 625 cr ≈ 52 s of Gen-4.5 | "No watermarks" listed from Standard. The Free tier is watermarked per 3rd-party sources. | 1080p, 4K upscale; Gen-4.5 = 60 cr / 5 s | Image-to-video from a real UI screenshot. Aleph to restyle footage. | Official |
| **Google Veo 3.1 / Flow** | Veo 3.1 (Lite / Fast / Quality) inside Flow, with native audio | Flow free credits per 3rd-party sources (unconfirmed). **Students: Google AI Pro free for 1 year** (SheerID; not on school-issued accounts). | AI Plus 200 Flow cr. **AI Pro $19.99, 1,000 Flow cr.** Ultra $99.99, 10,000 cr. | Invisible SynthID on all outputs (no visible mark on paid). Commercial use allowed under Google terms. | 720p/1080p, 4–8 s clips. 3rd-party: Fast ≈ 20 cr, Quality ≈ 100 cr per clip. | **Best quality per dollar** for a 1080p abstract or 3D-ish hero loop | Official (plans); 3rd-party (credit burn) |
| **Kling (Kuaishou)** | Kling 3.0 / 4.0 / Omni | ~66 credits/day, 720p, watermark (3rd-party) | Standard ≈ $6–10 (sources conflict) | Paid = no watermark. Free = watermark plus no commercial use. | 720p–1080p (4K on 3.0), 5–10 s | Cheapest watermark-free path. Strong motion. | 3rd-party (official page JS-rendered, not readable) |
| **Luma Dream Machine** | Ray3.2 / Ray3.14 plus hosted Seedance, Kling, Veo, MiniMax H3 | None listed | **Plus $30** ($25 annual), 10,000 cr, commercial use | Commercial from Plus | Ray3.2: 100 cr / 5 s at 720p, 400 cr at 1080p. HDR option. | Smooth seamless loops (keyframes), HDR | Official |
| **OpenAI Sora** | **App shut down 2026-04-26. API end announced for 2026-09-24.** Sora 2 is still reachable via Higgsfield. | — | — | — | — | **Do not plan on it** | 3rd-party news (CBS, PC Gamer) |
| **Pika** | Pika 2.5, Pikaframes, plus Seedance 2.5, MiniMax H3, Wan 3.0, Gemini Omni Flash | $0 but 0 credits (top-up packs only), no commercial use | **Starter $10** ($8 annual), 900 cr, commercial | Pricing table: no watermark on any plan | 720p, 5 s examples (Wan 3.0 = 33 cr) | Cheap commercial clips. Pikaframes for keyframed transitions. | Official |
| **Midjourney video** | V1 video (image-to-video, 5 s, extendable). Launched 2025-06-18. | No free tier | Basic $10 (video ≈ 8× image cost). Unlimited Relax video only on Pro $60 / Mega $120. | No watermark. Companies > $1M revenue need Pro+ (per MJ ToS). | 480p/720p SD-HD | Art-directed stills turned into subtle loops. Weak for UI. | 3rd-party (official docs returned 403) |
| **Hailuo (MiniMax)** | Hailuo 02 / 2.3, MiniMax H3 | Daily credits, 720p, 6 s, watermark, no commercial rights | Standard $7.99 (promo) to $14.99 list | Paid = no watermark | 768p–1080p | Cheap, good physics. Also on Higgsfield, Luma and Pika. | 3rd-party (conflicting) |

### 1.2 Higgsfield deep-dive (the user asked)

| Question | Answer |
|---|---|
| What it is now | San Francisco company (Higgsfield Inc.), raised $400M Series B at a $5.4B valuation (2026-08-17). It is mainly a **model aggregator** with its own image models (Soul / Soul 2.0), its own video camera-control model (DoP), and an agent ("Supercomputer"). |
| Free credits | **0** on the Free plan (pricing table, 2026-09-14). Some blogs say "10 credits/day", but that is older or unverified. |
| Watermark | Free = Higgsfield watermark, cannot be turned off, and removing it breaks the ToS. Paid = watermark-free downloads. |
| Commercial use | The documents conflict: the pricing table says Free = not included, while Help Center and ToS §4.4 say you own outputs and the right is not tied to a plan. **Safe reading: pay for Starter or above before you publish.** |
| Data | Outputs may not be used to train AI models (§5.1(iii), §5.2(iv)). Higgsfield may use inputs and outputs to train its own models unless you delete them or have an Enterprise agreement. |
| Verdict for us | **Skip unless you already pay for it.** $19 Starter is limited to 720p Kling 3.0 / Seedance Fast, which is weak for a full-bleed hero on a 1440p screen. The same money buys Veo 3.1 at 1080p on Google AI Pro (or $0 for students). Its strength (cinematic camera presets, UGC ads) matters more for social ads than for a landing loop. |

### 1.3 Prompting rules for the hero clip (honesty-safe)

- Generate **abstract or brand motion** (light through a storefront, parcels gliding on a soft gradient, a calm glowing orb). **Never** generate fake dashboards or UI. AI video invents UI the product does not have.
- Ask for "seamless loop, slow camera drift, no text, no logos, dark background, 16:9". Text in AI video comes out garbled.
- Keep it to 5–8 s and crossfade the last 0.5 s in ffmpeg if the loop seam shows.

---

## 2. Web-native motion tools (CSP compatibility is the gate)

| Tool | Cost | Runtime / size | CSP with `script-src 'self'` | Verdict | Source |
|---|---|---|---|---|---|
| **CSS scroll-driven animations** (`animation-timeline: scroll()/view()`) | Free | 0 kB | ✅ pure CSS | **Use.** Chrome/Edge 115+, Firefox 159+, Safari 26+, about **88% global**. Progressive enhancement via `@supports`. | Official caniuse |
| **View Transitions API** (same-document) | Free | 0 kB | ✅ | **Use** for tab or section swaps. Chrome 111+, Firefox 144+, Safari 18+, about **93%**. Astro has `<ClientRouter />` built in for cross-page transitions. | Official caniuse |
| **Motion (motion.dev)** | Free, open source (Motion+ is paid, optional) | `animate` mini **3.2 kB**. Uses native ScrollTimeline when available. | ✅ bundled by Astro, served from `'self'` | **Use** for springs, stagger, `inView`. | Official |
| **GSAP 3** | **100% free including SplitText, MorphSVG, ScrollTrigger** (Webflow-funded). Commercial use OK. Ban: building a visual no-code animation tool that competes with Webflow. | ~25 kB core gz plus plugins | ✅ npm, bundled | Use only if Motion is not enough (text-split hero headline, pinned scroll story) | Official (pricing and license) |
| **Three.js / OGL** | Free (MIT) | Three ~150 kB+ gz, OGL ~25 kB | ✅ bundled. Shaders compile as GLSL, no `eval`. | Overkill for 6 days. Only for a WebGL gradient or particle hero, and OGL is lighter. | — |
| **Lottie / dotLottie** | Free runtimes. LottieFiles free tier for assets. | `lottie-web` ~60 kB gz, no WASM. `dotlottie-web` loads WASM **from jsDelivr/unpkg by default**. | ⚠️ `lottie-web` svg renderer works with self-hosted JSON. ⚠️ dotLottie needs `setWasmUrl('/…wasm')` **and** probably `'wasm-unsafe-eval'` in `script-src`. | Only if a designer hands you a ready Lottie. Use `lottie-web` (svg) to avoid WASM. | Official GitHub wiki |
| **Rive** | Free editor (exports show a **Rive splash screen**). **Cadet $9** removes it. | WASM fetched **from unpkg by default**. Self-host via `RuntimeLoader.setWasmUrl()`. `canvas-lite` is the smallest package. | ⚠️ self-host WASM plus `'wasm-unsafe-eval'` | Great for interactive state machines, but the learning curve does not fit in 6 days | Official (docs and pricing) |
| **Spline** | Free plan = watermarked web export (3rd-party). Starter ≈ $12–15. | `@splinetool/runtime` plus a `.splinecode` scene (often 1–5 MB). WebGPU with WebGL fallback. | ⚠️ the scene loads from `prod.spline.design` unless self-hosted. WASM/CSP not documented, so assume `'wasm-unsafe-eval'` is needed. Heavy on mobile. | **Skip.** If you want 3D, render a Spline scene to **MP4** and treat it as the hero video. | Official docs; 3rd-party pricing |
| **Unicorn Studio** (WebGL effects) | Free = 8 publishes with Unicorn branding, **non-commercial**, limited video export. **Legend $20/mo** ($168/yr): commercial license, JSON export, HQ video export. | Own UMD script plus JSON scene | ⚠️ the free embed loads from their CDN. Legend JSON plus self-hosted script could pass `'self'` but is untested. | Skip, or export a **video** from it (Legend) | Official |
| **Jitter** | Free: 720p30, watermark, 3 files. Pro: 1080p60, WebM, no watermark. **Free Pro for students and educators.** | Exports MP4/WebM/GIF/**Lottie** | ✅ the output is a file | **Good** for animated feature cards or a logo sting. Apply for the education plan. | Official |

**CSP note.** Everything that is "just a file" (MP4, WebM, AVIF, JSON for `lottie-web` svg) works under `default-src 'self'`. Anything that compiles WASM needs `script-src 'self' 'wasm-unsafe-eval'`. That change is small but it loosens policy, so avoid it unless the payoff is large.

---

## 3. Product-demo tools (make the real UI the hero)

| Tool | Platform | Price | Export file? | Embed = 3rd-party iframe/script? | Verdict | Source |
|---|---|---|---|---|---|---|
| **Screen Studio** | macOS only | $29 monthly / $9 per month yearly. 40% student discount. | ✅ MP4 720p–4K 60 fps, GIF up to 1080p | n/a | **Best polish** (auto-zoom, smooth cursor). Pay for 1 month if anyone on the team has a Mac. | Official |
| **CleanShot X** | macOS 13+ | $35 one-time (Setapp 7-day trial) | ✅ screen recording (MP4/GIF per product docs) | n/a | Cheaper per-frame screenshot tool; less cinematic | Official |
| **Rotato** | macOS 11+ | One-time (prices not shown on page) | ✅ H.264/HEVC/ProRes 4444/PNG frames, up to 8K | n/a | 3D device mockups of real screenshots. Nice to have, not essential. | Official |
| **Arcade** | Web | Free: 250 cr, 30 s videos, 1080p, **watermark**. Pro $59 ($49 annual). | ✅ video export (watermarked on Free) | ⚠️ the interactive embed is an iframe from arcade.software, which breaks `default-src 'self'` (`frame-src`) | Export the video only. **No iframe.** | Official |
| **Supademo** | Web | Free: 5 demos, 50 recordings (4K), link/embed/video/PDF. Scale $50 ($38). | ✅ video (on Free per page) | ⚠️ the embed is a 3rd-party iframe | Export MP4 if you like the editor | Official |
| **Storylane** | Web | Free: 1 published demo, 200 AI credits, Storylane branding. Starter $50 ($40). | GIF/Video/PDF exist (the plan matrix was unreadable) | ⚠️ 3rd-party iframe/script | Skip; too expensive for value here | Official |
| **OBS Studio / ShareX / Windows Game Bar** | Win/Mac/Linux | **Free** | ✅ MP4 | n/a | **Default** for a Windows/WSL team. Add zoom-in punch-ins in DaVinci Resolve (free) or CapCut. | — |

**Rule:** interactive demo iframes require loosening CSP with `frame-src https://app.arcade.software` (or similar) and pull in 3rd-party tracking. For a 6-day sprint, **export MP4 and self-host**.

---

## 4. Recommended 6-day pipeline (0–30 USD)

### 4.1 Tool choice

| Slot | Tool | Cost | Deliverable |
|---|---|---|---|
| (a) Hero loop | Google Flow, Veo 3.1 Fast, 1080p. Student AI Pro = $0, else $19.99 for 1 month. Fallback: Kling free drafts plus Standard (about $7–10) for the final. | $0–20 | `hero.mp4` (H.264), `hero.webm` (VP9/AV1), `hero-poster.avif` |
| (b) Product walkthrough | Real ShopPilot+ UI recorded with OBS (free) or Screen Studio ($29 for 1 month, Mac only). Edit in DaVinci Resolve or CapCut. | $0–29 | `walkthrough.mp4` 20–40 s, captions burned in or a `<track>` VTT |
| (c) Micro-interactions | CSS scroll-driven animations plus View Transitions plus Motion `animate` (npm). Jitter education plan for 1–2 animated feature cards exported as WebM. | $0 | CSS plus about 3–10 kB JS |
| Optional | GSAP SplitText for the headline reveal | $0 | — |

**Total: $0 typical, about $29 maximum** (AI Pro $19.99 + Kling Standard about $9, *or* Screen Studio $29 alone; do not buy all three).

### 4.2 File-size budget (Render free tier: 5 GB/mo, so a 2 MB hero allows about 2,500 views)

| Asset | Budget | How |
|---|---|---|
| Hero MP4 | **≤ 1.5 MB** (hard cap 2 MB), 6–8 s, 1280×720 (or 1920×1080 if under budget), no audio track | `ffmpeg -i in.mp4 -an -vf "scale=1280:-2,fps=24" -c:v libx264 -preset slow -crf 28 -pix_fmt yuv420p -movflags +faststart hero.mp4` |
| Hero WebM | ≤ 1.2 MB | `ffmpeg -i in.mp4 -an -vf "scale=1280:-2,fps=24" -c:v libvpx-vp9 -b:v 0 -crf 40 hero.webm` |
| Poster | ≤ 60 kB AVIF/WebP | `ffmpeg -i hero.mp4 -frames:v 1 poster.png`, then Astro `<Image>` or `avifenc` |
| Walkthrough | ≤ 5 MB, `preload="none"`, loads on click | CRF 30, 1280 wide, 30 fps |
| JS for motion | ≤ 15 kB gz total | Motion mini plus your code; GSAP only if needed |
| Mobile | Serve the poster only below 768 px, or a 480p variant ≤ 600 kB | `<source media>` is ignored on `<video>` in some browsers, so swap with CSS or JS at mount |

### 4.3 Markup pattern (CSP-safe, no inline script)

```html
<video class="hero-video" autoplay muted loop playsinline preload="metadata"
       poster="/media/hero-poster.avif" aria-hidden="true">
  <source src="/media/hero.webm" type="video/webm">
  <source src="/media/hero.mp4"  type="video/mp4">
</video>
```

```css
@media (prefers-reduced-motion: reduce) {
  .hero-video { display: none; }                    /* show the poster as a background image instead */
  .hero { background: url(/media/hero-poster.avif) center/cover; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
@supports (animation-timeline: view()) {
  .reveal { animation: fade-up linear both; animation-timeline: view(); animation-range: entry 0% cover 30%; }
}
```

Also: put a visible **pause button** on any autoplaying video longer than 5 s (WCAG 2.2.2). Wire it in a bundled JS module, not inline. Keep the H1 and CTA as real text above the video, never baked into it.

### 4.4 Honesty rule (non-negotiable)

1. **AI video = mood only.** Abstract, brand or metaphor footage. No AI-generated dashboards, numbers, logos of real platforms, or "fake customer" faces.
2. **Every UI frame on the page comes from a real recording or screenshot of a feature that works in the demo build on 2026-11-05.** If a feature is planned, label it "Coming soon" or leave it out.
3. Numbers in the UI recording come from seeded demo data. Label them "demo data" in a caption.
4. Disclose AI-generated media in the footer ("Hero animation generated with Google Veo"). SynthID is in the file anyway.
5. No testimonials or logos of shops that are not real users.

### 4.5 Day plan

| Day | Date | Task |
|---|---|---|
| 1 | 10-30 | Claim the Google AI Pro student offer (or decide on $19.99). Apply for the Jitter education plan. Write 3 hero prompts. |
| 2 | 10-31 | Generate 6–10 Veo Fast drafts, then 1–2 Quality finals. Transcode and check sizes. |
| 3 | 11-01 | Build the hero section plus reduced-motion fallback plus pause button. Add CSS scroll reveals. |
| 4 | 11-02 | Freeze the demo build. Record the walkthrough (OBS or Screen Studio). Edit to 30 s. |
| 5 | 11-03 | Micro-interactions with Motion (CTA hover, feature-card stagger, View Transition on pricing toggle). Lighthouse pass (LCP < 2.5 s; the poster is the LCP element). |
| 6 | 11-04 | Mobile QA, CSP check (DevTools console shows 0 CSP violations), honesty audit against 4.4. Buffer. |

---

## 5. Sources (all accessed 2026-10-30)

### Higgsfield
- https://higgsfield.ai/pricing (JS-rendered; contents not readable by fetch)
- https://higgsfield.ai/creator-hub/help-center/account-and-privacy/who-owns-my-generations-and-can-i-use-them-commercially (official, updated 2026-09-12)
- https://www.krea.ai/blog/what-is-higgsfield-ai-pricing-free-plan-and-alternatives-in-2026 (3rd-party, competitor; pricing captured 2026-09-14)
- https://novoads.ai/en/blog/is-higgsfield-free
- https://aliteq.com/higgsfield-watermark
- https://flowith.io/blog/higgsfield-pricing-2026-free-vs-creator-vs-studio
- https://costbench.com/software/ai-video-generators/higgsfield/
- https://zsky.ai/blog/is-higgsfield-free

### Other generators
- https://runway.com/pricing (official)
- https://one.google.com/about/ai-premium/ (official, Google AI plans and Flow credits, student offer)
- https://www.imagine.art/blogs/Google-Veo-3.1-pricing
- https://diyai.io/ai-tools/video-generation/google-veo-pricing/
- https://lumalabs.ai/pricing (official)
- https://pika.art/pricing (official)
- https://kling.ai/membership/membership-plan (official, JS-rendered)
- https://eesel.ai/blog/kling-ai-pricing
- https://aireiter.com/blog/kling-ai-free-tier-2026
- https://www.cbsnews.com/news/sora-ai-openai-discontinues
- https://www.pcgamer.com/software/ai/openai-discontinues-sora-video-generation-app-disney-pulls-out-of-usd1-billion-investment-deal
- https://en.wikipedia.org/wiki/Sora_(text-to-video_model)
- https://techcrunch.com/2025/06/18/midjourney-launches-its-first-ai-video-generation-model-V1
- https://eesel.ai/blog/midjourney-pricing
- https://docs.midjourney.com/hc/en-us/articles/27870484040333-Comparing-Midjourney-Plans (official, returned 403)
- https://krater.ai/pricing/hailuo
- https://costbench.com/software/ai-video-generators/hailuo-ai/free-plan/

### Web motion
- https://gsap.com/pricing/ (official)
- https://gsap.com/community/standard-license/ (official)
- https://motion.dev/ (official)
- https://caniuse.com/mdn-css_properties_animation-timeline_scroll
- https://caniuse.com/view-transitions
- https://rive.app/pricing (official)
- https://rive.app/docs/runtimes/web/web-js
- https://rive.app/docs/runtimes/web/preloading-wasm
- https://github.com/LottieFiles/dotlottie-web/wiki/CSP-and-WASM-Self%E2%80%90Hosting-Guide
- https://docs.spline.design/exporting-your-scene/web/exporting-as-code
- https://www.npmjs.com/package/@splinetool/runtime
- https://costbench.com/software/ai-3d-generation/spline/free-plan/
- https://www.unicorn.studio/docs/pricing/ (official)
- https://jitter.video/pricing/ (official)

### Product demo
- https://screen.studio/ (official pricing section)
- https://cleanshot.com/pricing (official)
- https://rotato.app/pricing (official)
- https://www.arcade.software/pricing (official)
- https://supademo.com/pricing (official)
- https://www.storylane.io/pricing (official)
- https://obsproject.com/ (free recorder)

### Unverified, re-check before paying
- Kling and Hailuo official prices (JS-rendered pages; the 3rd-party figures conflict).
- Midjourney's current video pricing (official docs returned 403).
- Spline runtime WASM/CDN behaviour under strict CSP (not documented).
- Higgsfield's free-tier commercial use (pricing table and Help Center contradict each other).
