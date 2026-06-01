# OpenReef Onboarding Tour — Script (Phase 1)

A guided, skippable tour that runs **over Mission Control** on first launch after the feature
ships, and can be replayed any time. A cartoon reef-keeper guide narrates from a docked
"narrator bar"; each step scrolls to and highlights a real element on screen. Humour is
reef-related or pokes fun at Neptune Apex — nothing else.

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
[CHARACTER] = a cartoon reef-keeper mascot — <hair, beard, build, outfit colours,
any signature item, e.g. olive hoodie + cap + sunglasses>.
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

Poses are matched to the joke and all five are used: idle → point → smug → facepalm → point →
idle → celebrate.

Every cheeky line ties to a **documented** Apex pain point (see "Fact-check" below) — no invented
claims (Apex Fusion is free, so no "subscription/licence" jokes).

### 1. Welcome — `anchor: null` · pose: `idle`
- **Cheeky:** "Welcome aboard! A 30-second tour — and not a single line of Apex code. No virtual outlets, no Defer commands, no hunting through scattered docs for the one setting you need."
- **Professional:** "Welcome to OpenReef. Here's a quick 30-second tour of the main features."

### 2. Reef Health — `anchor: reef-health` · pose: `point`
- **Cheeky:** "Your whole reef's health in one honest number. Apex Fusion shows you the graphs and leaves you to play detective — I actually tell you what they mean."
- **Professional:** "Your Reef Health Score: one explainable 0–100 read on the tank, weighted for your reef type."

### 3. Dosing Advisor — `anchor: dosing` · pose: `smug`
- **Cheeky:** "Your alk, cal and mag consumption — worked out, with how much to dose. Your Trident burns reagents and clogs its lines to take those readings; turning them into actual advice costs you nothing."
- **Professional:** "The Dosing Advisor estimates alk/cal/mag consumption from history, projects when you'll reach a limit, and suggests dose changes. Advisory only."

### 4. Attention — `anchor: attention` · pose: `facepalm`
- **Cheeky:** "Anything wrong shows up here in plain English. No fault codes to Google, no scattered docs, no three-day forum thread just to get your auto top-off behaving."
- **Professional:** "Anything that needs attention — alerts, missing mappings, safety interlocks — is summarised here in plain English."

### 5. Trends — `anchor: sensors` · pose: `point`
- **Cheeky:** "Tap any reading for its full trend. Every probe you own in one place — no extra module to buy just to read one more thing."
- **Professional:** "Tap any reading to open its trend, with ranges from 1 hour to 30 days."

### 6. Safety (straight, no jokes) — `anchor: settings` · pose: `idle`
- **Cheeky / Professional (same):** "One serious note: OpenReef never switches an outlet until you map it and arm it yourself. Your livestock is never automated behind your back. Set that up in Settings."

### 7. Done — `anchor: null` · pose: `celebrate` (+ apex-throne sticker in Cheeky mode)
- **Cheeky:** "That's the tour — your reef's in good hands. Your Apex can sit there and think about what it's done. 🪸"
- **Professional:** "That's the tour. You can replay it any time from the Tour button."

## Triggers

- **Auto:** once, when `localStorage["openreef:onboarding:v1:done"]` is unset and Mission Control
  is the active tab. Sets the flag when finished or "Don't show again" is pressed.
- **Manual:** a "Take the tour" button (hero actions + Settings → Help) re-runs it regardless of
  the flag.

## Controls

`Back` · `Next` (→ `Finish` on last step) · `Skip` · `Don't show again`. Step dots show progress.

## Fact-check (keep jokes grounded)

Apex jabs must map to a real, documented pain point. Verified ones used above:

- **Programming complexity** — non-standard language (virtual outlets, `Defer`), and Neptune's
  official docs are widely described as scattered; the de-facto manual is community-written.
  [ATK tutorial thread](https://www.reef2reef.com/threads/neptune-apex-programming-tutorials-part-3-automatic-top-off-kit-atk.618106/),
  [programming help](https://www.reef2reef.com/threads/neptune-apex-programming-help.1003634/)
- **Auto Top-Off Kit (ATK)** — one of Neptune's most-complained-about products; setup/operation
  confusion is common. (same ATK thread above)
- **Trident reagents = the real recurring cost** — ~$45/2-month, ~$100/6-month; availability
  issues; sample/waste lines clog; readings can drift vs manual test kits.
  [reagent cost thread](https://www.reef2reef.com/threads/trident-2-months-reagent-44-95-6-month-is-99-95-what.697014/),
  [Trident service/clogging](https://help.neptunesystems.com/tridentservice/)
- **Fusion is FREE** — do **not** joke about Fusion subscriptions/licence fees. It does show raw
  graphs without interpreting them (no health score / dose math), which is the fair contrast.
  [Apex Fusion](https://help.neptunesystems.com/apex-fusion/)
- **Module-per-capability** — extra inputs/probes generally mean buying another module.

Before adding or editing a joke, confirm the claim against a source like the above.

## Future (not in Phase 1)

- Phase 2: free-floating avatar that walks between anchors (sprite-sheet walk cycle).
- Phase 3: ambient reactions to live state (celebrate at grade A, facepalm when alk is about to
  breach).
- Phase 4: optional voice via HA TTS, off by default.
