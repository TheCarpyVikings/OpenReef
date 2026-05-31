# OpenReef Onboarding Tour — Script (Phase 1)

A guided, skippable tour that runs **over Mission Control** on first launch after the feature
ships, and can be replayed any time. A cartoon Viking guide (the maker) narrates from a docked
"narrator bar"; each step scrolls to and highlights a real element on screen.

## Design rules

- **Personality lives in the calm moments.** Jokes are fine on welcome / features / empty states.
  The safety step is delivered straight — no comedy on anything that protects livestock.
- **Two tones.** `cheeky` (default) and `professional`. Every step has both lines; the toggle picks
  which to show. Professional = the same facts, no jokes/emoji.
- **Always escapable.** Skip and "Don't show again" on every step. Re-runnable from a button.
- **Degrade gracefully.** If a step's anchor element isn't on screen (feature hidden/unmapped),
  that step is skipped automatically — never blocks.

## Avatar poses used

`idle`, `point`, `smug`, `facepalm`, `celebrate` (1024² transparent PNGs — prompts below).
Until art is added, a built-in emoji placeholder is shown.

## Image-generation prompt kit (copy-paste)

### Step 0 — describe your character ONCE, then reuse it in every prompt

Replace `[CHARACTER]` below with a short description of your guy, e.g.:

```
[CHARACTER] = a cartoon Viking reef-keeper version of me — <hair, beard, build,
outfit colours, any signature item, e.g. teal hoodie + horned beanie>.
```

**Consistency is everything.** Best results: upload your existing character image as a
**reference** (Midjourney `--cref <url>`, or "character reference" / img2img in Flux, Firefly,
Ideogram), lock the **same seed** across all five, and change only the pose clause. If your tool
can't output transparency, add `on a plain solid #00b140 green background` and remove it after with
remove.bg / Photoroom (free).

### The five prompts (one per file — paste, swap `[CHARACTER]`, generate)

**idle.png**
```
Full-body mascot illustration of [CHARACTER], relaxed friendly idle giving a small
welcoming wave with one hand, warm smile. Flat vector cartoon style, bold clean
outlines, soft cel shading, vibrant friendly colours. Character centred, facing the
viewer with a slight 3/4 turn, standing on nothing. Transparent background, no scenery,
no ground shadow, no text. Identical character design, outfit, colours, scale, camera
distance and centring to the other poses. 1024x1024.
Negative: extra background, drop shadow, cropped hands or feet, watermark, text,
multiple characters, blurry, inconsistent outfit.
```

**point.png**
```
Full-body mascot illustration of [CHARACTER], enthusiastically presenting with one open
hand extended out to his left side as if showing something on a screen, bright
encouraging expression. Flat vector cartoon style, bold clean outlines, soft cel
shading, vibrant friendly colours. Character centred, facing the viewer with a slight
3/4 turn, standing on nothing. Transparent background, no scenery, no ground shadow, no
text. Identical character design, outfit, colours, scale, camera distance and centring
to the other poses. 1024x1024.
Negative: extra background, drop shadow, cropped hands or feet, watermark, text,
multiple characters, blurry, inconsistent outfit.
```

**smug.png**
```
Full-body mascot illustration of [CHARACTER], arms crossed, confident smug grin, one
eyebrow raised, chest out — "told you so". Flat vector cartoon style, bold clean
outlines, soft cel shading, vibrant friendly colours. Character centred, facing the
viewer with a slight 3/4 turn, standing on nothing. Transparent background, no scenery,
no ground shadow, no text. Identical character design, outfit, colours, scale, camera
distance and centring to the other poses. 1024x1024.
Negative: extra background, drop shadow, cropped hands or feet, watermark, text,
multiple characters, blurry, inconsistent outfit.
```

**facepalm.png**
```
Full-body mascot illustration of [CHARACTER], comic exasperation with one palm to his
forehead, eyes shut, mild light-hearted despair. Flat vector cartoon style, bold clean
outlines, soft cel shading, vibrant friendly colours. Character centred, facing the
viewer with a slight 3/4 turn, standing on nothing. Transparent background, no scenery,
no ground shadow, no text. Identical character design, outfit, colours, scale, camera
distance and centring to the other poses. 1024x1024.
Negative: extra background, drop shadow, cropped hands or feet, watermark, text,
multiple characters, blurry, inconsistent outfit.
```

**celebrate.png**
```
Full-body mascot illustration of [CHARACTER], both arms thrown up in triumph, huge
joyful grin, mid-cheer. Flat vector cartoon style, bold clean outlines, soft cel
shading, vibrant friendly colours. Character centred, facing the viewer with a slight
3/4 turn, standing on nothing. Transparent background, no scenery, no ground shadow, no
text. Identical character design, outfit, colours, scale, camera distance and centring
to the other poses. 1024x1024.
Negative: extra background, drop shadow, cropped hands or feet, watermark, text,
multiple characters, blurry, inconsistent outfit.
```

Save each at its exact filename into `custom_components/openreef/frontend/avatar/`. The panel
auto-swaps from the emoji placeholder to your art on the next update + restart — no code change.

## Steps

Each step = `{ id, anchor (data-tour), pose, cheeky, professional }`. `anchor: null` ⇒ centred,
no highlight.

### 1. Welcome — `anchor: null` · pose: `idle`
- **Cheeky:** "Welcome to OpenReef. Grab your mead — this'll be quicker than programming an Apex. Give me 30 seconds and I'll show you the good bits."
- **Professional:** "Welcome to OpenReef. Here's a 30-second tour of the main features."

### 2. Reef Health — `anchor: reef-health` · pose: `point`
- **Cheeky:** "This is your Reef Health Score. Fusion shows you graphs; *I* tell you what they mean — and *why* — with no subscription and no runes to decode."
- **Professional:** "This is your Reef Health Score: a single, explainable 0–100 read on the tank, weighted for your reef type."

### 3. Dosing Advisor — `anchor: dosing` · pose: `smug`
- **Cheeky:** "Here's the part Neptune charges a kingdom for: your tank's *actual* alk/cal/mag consumption, worked out from your Trident — plus how long until you hit a limit, and how much to dose. You're welcome."
- **Professional:** "The Dosing Advisor estimates your alkalinity, calcium and magnesium consumption from history, projects when you'll reach a limit, and suggests dose adjustments. Advisory only."

### 4. Attention — `anchor: attention` · pose: `idle`
- **Cheeky:** "If something's off, it lands here — in plain English, not a cryptic error code three menus deep."
- **Professional:** "Anything that needs attention — alerts, missing mappings, safety interlocks — is summarised here."

### 5. Trends — `anchor: sensors` · pose: `point`
- **Cheeky:** "Tap any reading to see its trend. Pinch-zoom the ocean, basically."
- **Professional:** "Tap any reading to open its trend, with ranges from 1 hour to 30 days."

### 6. Safety (straight, no jokes) — `anchor: settings` · pose: `idle`
- **Cheeky / Professional (same):** "One serious note: OpenReef never controls equipment until *you* map it and explicitly arm it. Nothing touches your livestock without permission. Set that up in Settings."

### 7. Done — `anchor: null` · pose: `celebrate`
- **Cheeky:** "That's the tour. Now go show your Apex who's boss. Skål! 🍻"
- **Professional:** "That's the tour. You can replay it any time from Settings."

## Triggers

- **Auto:** once, when `localStorage["openreef:onboarding:v1:done"]` is unset and Mission Control
  is the active tab. Sets the flag when finished or "Don't show again" is pressed.
- **Manual:** a "Take the tour" button (hero actions + Settings → Help) re-runs it regardless of
  the flag.

## Controls

`Back` · `Next` (→ `Finish` on last step) · `Skip` · `Don't show again`. Step dots show progress.

## Future (not in Phase 1)

- Phase 2: free-floating avatar that walks between anchors (sprite-sheet walk cycle).
- Phase 3: ambient reactions to live state (celebrate at grade A, facepalm when alk is about to
  breach).
- Phase 4: optional voice via HA TTS, off by default.
