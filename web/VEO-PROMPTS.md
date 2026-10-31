# Veo 3.1 prompts for the Approach 4 hero loop

You generate these in Google Flow with Veo 3.1, using the Google AI Pro student offer. No agent generates video.

Settings for all 3: **16:9, 1080p, 8 s** (6 s is fine if the motion loops better), **Quality** model for the final take (use Fast for drafts), **audio off** (it gets stripped anyway). Generate 2 to 3 drafts per prompt, then pick one.

Honesty rules (from `docs/research/02-motion-tools.md` §1.3 and §4.4):
- This is mood footage only. No screens with readable UI, no dashboards, no numbers, no text, no logos, and no real platform branding.
- The footer must say "Hero video generated with Google Veo".
- Every UI frame on the page comes from the real app, never from AI video.

After generating:
1. Transcode (≤ 1.5 MB MP4, ≤ 1.2 MB WebM, ≤ 60 kB poster). The commands are in `02-motion-tools.md` §4.2.
2. Drop the files into `shoppilot/web/public/v2/media/`:
   - `hero.mp4`
   - `hero.webm`
   - `hero-poster.avif`
3. Tell the agent which take you chose.

---

## Prompt 1: "Last light at the packing table" (recommended)

**Prompt**
> Slow, steady dolly-in across a small home-studio packing table in the evening. Kraft mailer boxes are neatly stacked and sealed. A roll of packing tape and a few handmade candles in plain tins sit beside a closed laptop. Warm desk-lamp light pools on the wood while cool blue dusk comes through a window behind. A pair of hands slides the last sealed box onto the stack, then withdraws out of frame. The scene settles and holds, calm and finished. Shallow depth of field, soft film grain, natural colour, quiet and unhurried. Seamless loop: the end frame matches the start framing.

**Negative prompt**
> text, letters, numbers, captions, logos, brand names, labels with writing, shipping labels with addresses, computer screens showing an interface, phone screens, dashboards, charts, people's faces, fast motion, camera shake, whip pans, lens flares, neon, futuristic holograms, robots, glowing AI orbs, clutter, mess, stress, night club lighting, oversaturated colour, cartoon style, watermark

---

## Prompt 2: "The lamp clicks off"

**Prompt**
> Locked-off medium-wide shot of a tidy small-business workspace at night. On the desk are a shelf of folded fabric goods, a stack of sealed parcels and a mug. Late evening, quiet room. The warm desk lamp dims gently to off, leaving soft blue moonlight from the window across the sealed parcels. Dust drifts slowly through the window light. Calm, relieved, end-of-day mood. Muted natural palette of warm wood, linen white and deep blue. Gentle, barely perceptible push-in. Cinematic 35mm look, soft grain. Seamless loop.

**Negative prompt**
> text, numbers, logos, screens, monitors showing content, laptops open, phones, user interface, dashboards, graphs, faces, people looking at camera, fast cuts, camera shake, harsh flicker, strobe, neon, sci-fi, holograms, robots, glowing particles that look digital, clutter, mess, horror mood, darkness that hides the scene, watermark

---

## Prompt 3: "Parcels in morning light" (the abstract option)

**Prompt**
> Macro, slow lateral slide along a row of plain kraft parcels and tissue-wrapped products on a light oak shelf. Soft early-morning sunlight rakes across the paper texture, and the shadows of a window frame move slowly over the parcels. A single sprig of dried lavender rests on top of one box. Clean, airy, hopeful, unhurried. Warm neutral palette with soft cream highlights and no saturated colours. Very shallow depth of field and creamy bokeh. Smooth, constant camera speed so the loop point is invisible. No people.

**Negative prompt**
> text, writing, handwriting, numbers, barcodes, shipping labels, stamps with words, logos, brand marks, screens, interfaces, charts, people, hands, faces, fast motion, zoom bursts, camera shake, lens flare, neon, futuristic effects, glowing lines, clutter, dirt, damaged boxes, watermark
