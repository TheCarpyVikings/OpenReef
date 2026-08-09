# OpenReef marketing site — "The Dive"

Scroll-driven 3D journey: the page dives from the water surface to the reef floor, with
each feature beat anchored to the scene. Plan of record + copy deck: `docs/website-plan.md`.

Standalone Vite + React + react-three-fiber app — deliberately separate from the root
Next.js dashboard so it never entangles with the app's auth/secrets work.

## Run

```bash
cd site
pnpm install
pnpm dev        # local dev
pnpm build      # type-check + production build to dist/
pnpm preview    # serve the production build
```

## Deploy

Create a separate Vercel project with **Root Directory = `site`** (framework: Vite).
No env vars needed.

## Feature screenshots

The feature cards expect fresh screenshots from the **current HA integration** (not the
old v1 app) in `public/demos/`. Cards hide their image until the file exists. Capture
them all in one go against your running Home Assistant:

```bash
HA_URL=http://homeassistant.local:8123 HA_TOKEN=<long-lived-token> pnpm capture
```

See `tools/capture-demos.mjs` for options (tab selection, viewport, Chrome path).
It logs into the frontend headlessly, clicks each panel tab through the shadow DOM,
and writes `mission-control.png`, `dosing.png`, `awc.png`, etc.

## Mobile audits

Two separate tools, easy to confuse:

- **`tools/mobile-audit.mjs`** — audits **this site**. Loads it at iPhone SE/15/15 Pro
  Max, Pixel 8 and iPad mini metrics and reports horizontal overflow, tiny tap targets,
  how much screen the buddy bubble eats, and per-section screenshots.
  `node tools/mobile-audit.mjs [url]`

- **`tools/panel-mobile-audit.mjs`** — audits **the HA panel**. `/demo/` mounts the real
  `openreef-panel.js` against fixtures, which makes it a full-panel layout lab. This
  sweeps every tab at iPhone 15 Pro Max, iPhone 14/15, iPad Pro 12.9 and desktop, and
  reports what a screenshot cannot: elements overflowing the viewport, text clipped by a
  too-narrow grid column, sub-32px tap targets, and how much vertical space the nav eats
  before the first card appears.

```bash
python3 tools/demo-fixtures.py   # pin the CURRENT panel into public/demo/
pnpm build
pnpm panel:mobile-audit -- --shots /tmp/shots
```

Exit code 1 means something overflows horizontally — a real bug. Tap targets and page
heights are printed for judgement, not gated. This is how the 0.7.33 panel mobile pass
was measured: the nav was 787px tall on a 932px screen, first card 1,129px down.

## Before launch

- [ ] Wire `FORM_ENDPOINT` in `src/ui/Sections.tsx` to Buttondown/Formspree/Tally
      (until then the form falls back to a mailto).
- [x] Feature screenshots captured from the live HA integration (`pnpm capture`).
- [x] Real buddy pose art wired in (`public/avatar/`, copied from the panel).
- [x] Comparison prices verified against UK retailers, July 2026.
- [ ] Deploy to OpenReef.co.uk and re-check the OG card renders on socials.
- [ ] Mobile QA pass (only verified at 1440×900 so far).

Re-copy the buddy art whenever the panel's poses change:

```bash
cp ../custom_components/openreef/frontend/avatar/{idle,point,smug,facepalm,celebrate,concerned,thinking,chilled,apex-throne}.png public/avatar/
```

## How it hangs together

- `src/reef.ts` — shared mutable state bridging DOM (writes) and the R3F frame loop
  (reads): scroll progress, sun hour, health score, spawn pulse. Also camera depth
  keyframes and channel curves.
- `src/scene/Scene.tsx` — the whole 3D scene (water shader, god rays, fish schools,
  procedural reef, health ring, light rail, spawn burst, dosing pumps, Apex throne).
- `src/copy.ts` — buddy script (cheeky / cheekyNoApex / professional, same shape as the
  panel's onboarding script), features, tiers, comparison rows, price-ticker items.
- `src/ui/Sections.tsx` — all DOM sections and interactive widgets.
- Reduced-motion / no-WebGL visitors get a static gradient background; every section
  is plain crawlable HTML either way.
