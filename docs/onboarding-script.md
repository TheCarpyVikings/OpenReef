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

`idle`, `point`, `smug`, `facepalm`, `celebrate` (1024² transparent PNGs, see image-prompt kit).
Until art is added, a built-in SVG placeholder mascot is shown.

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
