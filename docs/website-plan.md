# OpenReef Marketing Site — "The Dive"

Plan of record for the public marketing site. Lives in `site/` (standalone Vite + React +
react-three-fiber app — deliberately separate from the root Next.js dashboard app so it
never entangles with the Vercel auth / secrets work in `VERCEL_READINESS_TODO.md`).
Deploy as its own Vercel project with root directory `site/`.

## Locked decisions (2026-07-24)

1. **Primary audience:** the 55-year-old Apex owner — the site must make *them* install
   OpenReef. The 3D spectacle exists to make first-time viewers stop scrolling and take
   the product (and the developer) seriously. Credibility carries conversion; the
   spectacle carries attention.
2. **Framing:** "Keep your Apex. Give it a brain." Never two-column us-vs-them — the
   comparison is three columns (Apex alone / **Apex + OpenReef** / full DIY OpenReef)
   with the middle column highlighted. Apex owners see an upgrade path, not a threat.
3. **Humor:** funny but not crude. Wordplay off competitor product names is the house
   style (see bank below — "Insight" → "in sight / out of sight" is the register).
   Jokes live ONLY in the reef-buddy speech bubble (clearly comedy, Cheeky/Professional
   toggle, Apex-aware joke sets — same mechanic the panel ships in
   `custom_components/openreef/frontend/openreef-panel.js` `_hasApex()` / `_tone()`).
   The comparison table itself stays dry and factual (nominative fair use — safe).
4. **Primary CTA:** email capture — "get the manual first + private beta signup" as one
   form. Secondary CTA: GitHub / get the integration. Kits: honest waitlist only
   ("still in research"), no fake shop.
5. **Manual:** it IS the product's soul, but the repo copy is outdated and OpenReef is
   still moving fast — the rewrite waits. The site collects emails *now* against its
   future release ("The manual is coming. Get it first."). Manual pages will be
   indexable HTML (not PDF) when written — it is the SEO goldmine ("DIY reef
   controller" searches), Phase 3.
6. **Scope discipline:** phased (below). Phase 1 ships one continuous dive with a small
   number of *fully finished* interactive beats + polished 2D sections, not eight
   half-done scenes.

## The journey (scroll = depth)

1. **Surface** — water shader, logo, "The intelligence layer for your reef." / "Open
   source · runs on Home Assistant · plays nicely with your Apex." Cue: "Dive in ↓"
2. **Meet the buddy** — narrator bubble asks two questions that configure the whole
   site: Cheeky vs Professional, and "Do you run an Apex? (No judgement. Well. A
   little.)" Stored in localStorage; changes every joke after it. Tooltip: "this site
   runs the same joke-selection logic as the product."
3. **One honest number** — the Reef Health ring floats in open water. **Break-the-tank
   sandbox**: sliders for alk / temp / pH / salinity; the ring, buddy pose, and a
   plain-English alert + dosing-advisor line react live. This is the Trust Moat as a
   toy. Safety line always visible: "Advisory only — OpenReef never switches an outlet
   you haven't mapped and armed yourself."
4. **Drag the sun** — schedule-aware beat. HONESTY RULE (2026-07-24): OpenReef does
   NOT control lighting yet (on/off only) — never claim light control. The scrubber
   still drives the whole 3D scene's lighting (the spectacle stays), but the DOM
   readout shows what OpenReef *derives* from the visitor's lighting schedule:
   feed-watch window, spawning dusk ramp, quiet alerts, timelapse cadence.
5. **Your controller can't count moons** — coral spawning. Lunar dial; wind it to
   nights 12–15 after the full moon and trigger a particle spawn burst. Ends on "reef
   biology, compiled into your light schedule."
6. **Features shelf** — 2D cards with the real demo webps (mission control, sensors,
   equipment, lighting, energy/tasks, spawning/AWC) + text tiles for ICP import,
   camera AI, Lagertha. Real product screenshots > renders.
7. **The cabinet** — descend past the rockwork into the sump cutaway: dosing pumps
   animating. DIY story: free manual pitch ("Every part number. Every wire. Free.
   That's the open in OpenReef.") + kit tier waitlist.
8. **The reef floor** — comparison. Sunken throne vignette: the Apex resting on it,
   respectfully lit, tiny crown ("a very good box"). Three-column factual table +
   running price ticker that has been quietly accumulating since scene 2. Buddy
   carries the jokes beside it.
9. **Resurface — CTA** — the one form (manual + beta). Buddy closer: "Now go show
   your tank who's boss. 🪸"

## Humor bank (wordplay off competitor names — buddy-bubble only)

- AV "Insight Pro" → "Some controllers sell you *Insight*. We'd rather your problems
  weren't out of sight." (replaces the old crude tier name — same joke, invitable to
  a checkout page)
- Apex Fusion → "Fusion? For most of us it was Con-Fusion."
- Trident reagents → "The maths is free. Trident reagents are the printer ink of the
  sea."
- Neptune → "Great god of the sea. Pricey religion."
- Apex → "The Apex is a great box. It's just not a great brain." / "Apex predator,
  meet apex *spectator* — Fusion shows you graphs and leaves you to play detective."
- GHL ProfiLux → "German engineering. German invoice."
- Hydros → "Hydro$" (use sparingly)
- Footer: "No corals were harmed in the making of this website. One Apex had its
  feelings hurt, but it's fine."
- Kit tiers (reef-native — NO Viking/Norse references anywhere on the site, per
  2026-07-24 decision): **Frag** (monitoring starter), **Colony** (monitor +
  control), **Reef** (the full build). Cheeky taglines only in Cheeky mode.

## Phases

**Domain:** OpenReef.co.uk (owned; not yet deployed). Deploy as its own Vercel project
with root directory `site`.

**Phase 1 (now, in repo):** the dive above with beats 1–5 fully interactive, 6–9 as
polished DOM sections over the live scene. Procedural low-poly art (no Blender
dependency), `prefers-reduced-motion` + mobile fallback (static hero, all content
still readable), full SEO meta + crawlable HTML for every claim. Email form posts to
`FORM_ENDPOINT` (Buttondown/Formspree/Tally — to be wired) with mailto fallback.

**Phase 2 (polish + art)** — progress 2026-07-24:
- DONE: OG image (`public/og.png`, regenerate via `?og=1` at 1200×630), 404
  bare-bottom-tank page (`public/404.html`), konami-code spawn easter egg,
  procedural exploded-kit vignette flanking the DIY card, screenshot capture
  harness (`site/tools/capture-demos.mjs`, run with `pnpm capture` against live HA —
  v1-app webps deleted; feature cards hide images until captures exist).
- DONE 2026-07-25: all 10 feature screenshots captured from the live HA integration
  (+ click-to-zoom lightbox); real buddy pose art wired in (copied from
  `custom_components/openreef/frontend/avatar/` to `site/public/avatar/`, emoji
  fallback retained); `apex-throne.png` gag included as a CLICK-TO-REVEAL under the
  comparison table (cheeky + Apex-owner only — it must never ambush a first-time
  reader, the image is rude); UK prices verified against All Things Aquatic /
  Charterhouse Aquatics (see below).
- DONE 2026-07-26 — **Realism pass v1** (Track 1, rendering-only): bloom/vignette/
  SMAA post-processing, camera-following projector-spotlight caustics, curved
  tapered gradient coral tubes + craggy displaced rocks (each merged to a single
  draw call with baked vertex colours), multi-octave water with distance haze.
  All gated off for low-power devices. **Track 2 (asset realism) still open**:
  replace hero corals with real scanned models (Smithsonian Open Access has CC0
  coral photogrammetry) or user's Blender art; needs curation + decimation to
  web weight (gltf-transform pipeline) — the one graphics item needing external
  input.
- REMAINING (blocked on user assets): real 30-day trend JSON from the actual tank
  powering the sandbox ("This is not demo data. This is my tank, last month.").

**Verified UK prices (July 2026)** — the site's only hard money claims, keep sourced:
Apex A3 Pro system £999.99 · Trident £774.99 · Trident NP £739.95 · Trident reagents
6-month pack £125.95 (≈£252/yr) · DOS £359.99 · DOS+DDR combo £589.95 · Energy Bar 632
UK £324.95 · ATK £269.95. Ticker total lands ≈£2,942 vs OpenReef £0.00.
- RULE: all feature screenshots must come from the current HA integration, never
  the old v1 Next.js app.

**Phase 2.5 (deep-dive pages)** — started 2026-07-26. Site is now a Vite
multi-page build: each feature deep dive is its own static HTML entry (no 3D
payload, FAQ + FAQPage JSON-LD, canonical/OG meta, honest-limits section, buddy
one-liner), linked from the features grid via "Deep dive →". Shipped:
`/features/coral-spawning/`, `/features/dosing-advisor/`,
`/features/automatic-water-change/`, `/features/icp-import/`,
`/features/camera-intelligence/` (2026-08-04 — the combined
"Spawning & water changes" card was split into two cards so every deep dive
has its own card + screenshot; spawning.png finally in use). robots.txt +
sitemap.xml live. Backlog (add via `src/pages/*` + an HTML entry in
vite.config.ts, then sitemap): maintenance, equipment safety model.
NOTE: cameras.png was captured with the camera offline (black live view,
"0/1 mapped") — re-run `pnpm capture` with the camera up when convenient. NOTE 2026-07-26: first screenshot capture
was photobombed by the guided tour — harness now pre-sets
`openreef:onboarding:v1:done` + `openreef:buddy=off` and click-skips as
fallback; re-run `pnpm capture` for clean shots.

**Phase 3 (the manual):** rewrite the manual as indexable HTML pages in this repo,
served under the site (SSG). Announce to the email list. This is the SEO engine;
everything before it is the shop window.

**Explicitly out of scope until researched:** kit sales/checkout (UKCA/liability for
mains-switching DIY electronics still unresolved — waitlist only), any claim that
implies public availability beyond the private beta.

## Site architecture notes

- Fixed full-screen R3F `<Canvas>` behind native page scroll (no drei ScrollControls —
  scrollytelling via a shared mutable `reef` state object that DOM writes and
  `useFrame` reads; robust with mixed DOM/3D content).
- Camera path: scroll t ∈ [0,1] → depth y ≈ +3 → −46 through the beat stops; fog +
  background color lerp by depth; god rays, marine snow, instanced fish schools on
  wander paths (no physics), procedural flat-shaded rockwork/coral clusters.
- All interaction happens in DOM (canvas is pointer-events: none) — keeps a11y and
  mobile simple.
- Bundle target < 500 KB gz before demo webps; webps lazy-loaded.
