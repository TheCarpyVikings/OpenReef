# Coral Diary — research + design brief (2026-09-15) · STATUS: §8 LOCKED (§9) · stages A+B+C SHIPPED as 0.7.192 (§10)

The ask (Reece, 2026-09-15): a coral diary/log. Every coral the keeper owns, with the
details that matter (age, source, placement…), a smart health tracker in the spirit of
Reef Health, target-feed / note / photo logging, optional reminders to log a health check
on a recommended-but-overridable schedule, feed reminders with recommended foods for the
corals that want them, and tie-ins with the Reef Layer, NPS mouth data and the rest of
OpenReef.

The headline stance, before the detail: **a coral cannot be probed, so its "score" is an
observation ledger with a confidence clock, not a sensor reading.** Anything that pretends
otherwise is a number people will stop trusting. The leapfrog is not the score itself; it
is that the score sits beside the probes, the shelf, the camera and the feed ledger, and
can say *why* a colony slipped.

---

## 1. What exists today (0.7.191) — the foundations this stands on

| Piece | Where | What it gives the diary |
|---|---|---|
| **Reef Layer registry** | `livestock.corals` (const.py ~1438, normaliser `__init__.py` ~3394) | 16-coral cap; `name`, `species` (36 art species), `colour` (8), `addedAt`, `notes` (500), `photoUrl` (one photo, replaced in place). Drawn on the diagram + Pulse wall; Pulse focus card shows age + zone line. Dialog off the Diagram tab (0.7.178). |
| **Photo upload** | `openreef/coral_photo_upload` (~10185) | Client downscales to ≤1280 px JPEG; server writes `openreef_captures/corals/<id>.jpg` and pins the URL. Already path-safe by construction. |
| **Reef Health score** | panel `_reefHealthScore` (~6285) | The vocabulary to copy: losses by category, **caps** for life-critical states, a "cannot see this tank" confidence cap, insights grouped action / watch / context / learning, `affectsScore` honesty flag, per-profile weights. |
| **Maintenance due evaluator** | `_maintenance_due_items` (~4905), digest push (~5573), quiet hours, snooze, `MAINTENANCE_DUE_EVENT` | Backend-authoritative reminders that fire with the panel closed, one daily digest, quiet-hours hold. Culture tasks already hook in with a custom clock (`_cultures_task_clock`) — the exact pattern for a coral check-in clock. |
| **Manual test schedules** | `manualTests.schedules` per parameter, presets per tank profile | The "recommended cadence with user override + criticalAfterDays" shape, already understood by keepers. |
| **NPS species library** | `nps.py` SPECIES_LIBRARY, `MOUTHFUL_REFERENCES`, `mouth_note`, `species_card`, `compile_feed_plan` | Particle windows in µm, foods by category, cadence (pulse / continuous / **target**), feeds per day, night / trainable flags. `nps.species` is a separate tick-list of library ids — **not** linked to Reef Layer corals today. |
| **Food shelf** | `consumables.products` (categories, particle windows, low/expiry nags) | The foods the keeper actually owns, so "recommended food" can be "you have Reef Roids on the shelf" rather than a brand list. |
| **Feed ledger** | `nps.feed_log`, rows carry `to` (tank / soak / jar), hand-dose undo window | Target feeds are tank feeds; a `coralId` on the row is all that is missing. |
| **Camera V2** | event capture, timelapse (fixed window, same lighting), feed-watch, live WebRTC | "Same angle, same lighting phase, once a week" is literally the timelapse contract. |
| **Vision (Frigate)** | coral zones, per-zone fish visits | Which fish keeps visiting which colony (nipping) — an optional "why" signal. |
| **Alert history / live stats** | alert history, ring buffers, event ticks | The "what happened to the water this week" context to line up against check-in drops. |
| **Activity log** | `_append_activity`, cap 200 | Not a diary store (too short, shared); the diary needs its own ledger. |

Reminder of the house rules that bite here: any server-written field joins the stale-save
guard; backend due evaluator stays LOCKSTEP with the panel; every new dialog gets a
distinctive class; new WS handlers must join `async_register_command`; personality only
on calm copy.

---

## 2. Research digest

### 2.1 What the market ships (and does not)

- **Coral Tracker** (coral-tracker.com): per-coral name / type / price / photo / frag count /
  size cm / days owned / ROI, growth charts and visual timelines. **No health scoring, no
  reminders.** Free ≤10 corals, €4.99–€9.99/mo above.
- **Coralline** (free), **AQma**, **NextUpReef**, **ReefDeck**, **Aquarimate**: livestock
  lists with photos, notes and care records; journal photos usually behind a Pro tier.
  None of them is a controller, so none can put a colony beside a live alk trend.
- **Apex Fusion** (the beta tester's world): a notes system with date-stamped good / bad /
  ugly notes and livestock purchase entries. **No per-coral record, no per-coral history,
  no check-in schedule.**
- **CoralWatch Coral Health Chart** (University of Queensland citizen science): colour
  brightness score 1–6 per hue, where 4–6 is a normal symbiont load and <3 is distress.
  Free, standardised, and hobbyists already know it from the reef-monitoring world. A
  six-swatch picker is trivial to build and gives the colour field real-science footing.

**Honest claim we can make:** "the first coral diary that lives next to the probes" —
per-coral check-ins scheduled like tests, judged against the same week's water, with the
shelf, the camera and the NPS mouth data in the same room. Not "the first coral log"
(Coral Tracker and Coralline exist).

### 2.2 What a health check actually observes (the research, distilled)

| Signal | Reacts in | How to log it | Notes |
|---|---|---|---|
| **Polyp extension / expansion** | hours | 0–3 (retracted · partial · normal · full) vs the colony's own baseline | The first signal; three quiet days is real. |
| **Feeding response** | hours | took food / ignored / could not tell | NPS feed log already has this for NPS animals. |
| **Tissue** | days–weeks | intact · receding (active, white skeleton) · receding (stalled, algae-dusted) · STN/RTN | The one you can *measure*; bright white edge = active now. |
| **Colour** | weeks | CoralWatch 1–6 against the colony's baseline; browning vs pastel | Same lighting phase every time or the number is noise. |
| **Fluorescence** | weeks | up · same · fading | Under actinics; fading greens/reds precede colour loss. |
| **Pests / nuisance** | variable | none · suspected · confirmed (list: flatworms, nudis, red bugs, vermetids, aiptasia contact, algae smothering) | Lights-out torch inspection is the protocol. |
| **Neighbours** | variable | stung / shading / fish nipping | Diagram slots know adjacency; vision knows the fish. |
| **Size / growth** | months | mm or cm, frag count | Coral Tracker's whole product is this one field. |

Cadence guidance from the sources: weekly same-angle photos for SPS and LPS, fortnightly
for softies, **every 2–3 days for a new arrival's first month** (acclimation, dip follow-up,
pests), and a lights-out pest inspection monthly. Nothing in the hobby argues for daily
check-ins on established colonies; daily is how logs die.

### 2.3 Feeding guidance by group (seed data for the recommendations table)

| Group (Reef Layer species) | Target feeding | Foods | Notes |
|---|---|---|---|
| Euphyllia (torch, hammer, frogspawn), bubble, elegance | light, ≤1×/week or none | small particles: reef blend, mysis pieces | do not force large items; sweepers to ~15 cm |
| Acan, blasto, favia, brain, chalice, duncan, candycane, goniopora | 2–3×/week | mysis, LPS pellets, prepared blends | evening, polyps open |
| Scoly, trachy, cynarina, lobo, fungia | 1–2×/week, modest portion | mysis, chopped seafood | too much rots unswallowed |
| SPS (staghorn, table, birdsnest, digitata, stylophora, pavona, plate) | broadcast only | fine zooplankton / amino blends | no per-colony target feed reminder |
| Softies, zoas, mushrooms, ricordea, xenia, gsp, kenya tree, toadstool | none required | broadcast if at all | reminder off by default |
| Anemone | 1–2×/week | meaty chunks (mysis, silverside pieces) | mouth-sized only |
| Clam | none (light) | phyto optional for small clams | |
| Sun coral, gorgonian (NPS) | **from SPECIES_LIBRARY** | library foods + mouth note | the existing compiler owns this |

Particle windows for the mouth check (new, for non-NPS corals): Euphyllia/LPS 300–3000 µm,
acan/brain/favia 500–5000 µm, scoly/trachy/cynarina 1000–20000 µm (whole items), SPS 5–300
µm, anemone 2000–20000 µm. These plug straight into `MOUTHFUL_REFERENCES` /
`mouth_note`, so "rotifers are too fine for this mouth; mysis fits" comes free.

---

## 3. The design — "Corals" (a diary that grows out of the Reef Layer)

### 3.1 One registry, two faces

The Reef Layer registry **is** the diary's registry. Nothing is duplicated:

- `livestock.corals[<id>]` grows the diary fields (§3.2). The diagram keeps drawing the
  species glyph; the cap on **drawn** colonies stays 16 (art budget), the cap on
  **registered** corals rises (proposal: 60). A coral is drawn when it has a slot in
  `diagram.layout`; unplaced corals live only in the diary.
- The Reef Layer dialog stays the art kit (species glyph + colour + place it). The diary
  is its own tab (**Corals**) in flow order, with the dialog reachable from it.
- NPS animals: a coral entry may carry `npsId` (a SPECIES_LIBRARY id). `nps.species` becomes
  **derived** from the registry (LOCKSTEP: one source of truth), with a one-shot migration
  that creates a diary entry per ticked NPS species so nothing the compiler relies on
  disappears. This is the load-bearing decision — see §8 Q2.

### 3.2 The entry (fields)

```
livestock.corals[id] = {
  # Reef Layer (unchanged)
  name, species (art species), colour, addedAt, notes, photoUrl,
  # identity
  taxon: "",            # free text: "Acropora tenuis 'Walt Disney'"
  npsId: "",            # SPECIES_LIBRARY id when it is an NPS animal
  source: "",           # shop / trade / frag from <coral id> / wild
  paid: null,           # currency-free number; value is v2
  arrivedAt: "",        # = addedAt today; keep one, rename in the UI ("in your tank since")
  dipped: false, quarantined: false,   # arrival protocol, drives the 30-day cadence
  status: "active",     # active | fragged | rehomed | lost   (never deleted; tombstone)
  statusAt: "", statusNote: "",        # "lost — RTN after the alk crash, 2026-08-30"
  # the diary's knobs
  checkCadenceDays: null,  # null = recommended for the group; number = override
  feedCadenceDays: null,   # null = recommended; 0 = off
  foods: [],               # shelf product ids the keeper uses on this colony
  baseline: { extension, colour, notes },   # what "normal" looks like for THIS colony
}
```

Ledgers, server-owned (written by WS, so they join the stale-save guard):

```
livestock.checkins[id] = [ { at, extension 0-3, tissue, colour 1-6, fluor, feeding,
                             pests[], neighbours[], sizeMm, note, photoUrl, score }, … ]   # newest first, cap 52/coral
livestock.feeds[id]    = [ { at, productId, amountNote, response } ]                        # OR rows in nps.feed_log with coralId — §8 Q6
```

Photos: `openreef_captures/corals/<id>/<stamp>.jpg`, cap per coral (proposal 24) + a
global byte budget, oldest evicted, `photoUrl` stays the hero (latest, or pinned).

### 3.3 The colony score — Reef Health's grammar, applied honestly

Per coral, 0–100 with a grade and a **trend vs last check-in**. Same three instruments:

- **Losses** from the latest check-in, each tied to the signal that caused it: partial
  extension −10, retracted −25, colour two steps under baseline −15, fluorescence fading
  −8, ignored food (for feeders) −8, pest suspected −12, confirmed −20, stung/shaded −8.
- **Caps** for the life-critical states: active recession caps at 40, STN/RTN caps at 20,
  confirmed pest caps at 60. A cap always names itself ("Active recession — the score cannot
  read above 40 until the edge stops").
- **Confidence clock** (the "cannot see this tank" idea): no check-in inside 2× the
  cadence caps at 70 and the card says "Not looked at for 19 days"; inside the cadence but
  the photo is older than 4 weeks: a context insight, not a loss. **A coral you never look
  at cannot be graded A.** This is the honesty rule, same as bare rock.
- **Context, never score** (`affectsScore: false`): the water. If alk moved > 1 dKH in the
  week before a drop, or temperature capped, or a salinity excursion, or an ICP flag on a
  trace the colony cares about, the card says so as *context*. The colony score does not
  fall because the water did — the check-in already recorded what the coral thought of it.

Aggregate: a **Livestock strip** on the Corals tab ("14 colonies · 11 fine · 2 watch ·
1 needs you · 3 unchecked"). Whether any of this feeds Reef Health's headline is §8 Q4
(my vote: no — self-reported input must not inflate a number people trust from probes;
show it as a Reef Health *insight* in the context group instead).

### 3.4 The check-in ceremony (the thing that must be fast)

One coral, one screen, thirty seconds: hero photo (or grab a frame from the tank camera —
same window as the timelapse so the lighting matches), four tap-rows (extension · tissue ·
colour swatches · feeding), a pest / neighbour chip row, a size box, a note, **Save**.
Defaults pre-filled from the last check-in so "same as last week" is one tap. A **round**
mode walks every due coral in diagram order (crest → mid-rock → base → back) and ends on
the strip. Undo inside 15 min via the tombstone pattern (`undoneAt`), never deletion.

### 3.5 Reminders — ride the maintenance rail, do not build another

- A **synthetic maintenance task per due family**, like culture tasks: `coral_check`
  ("Coral check-in: 4 colonies due — Golden torch, WD tenuis, …") and `coral_feed`
  ("Target feed: acan garden, scoly"). Custom clocks via the `_cultures_task_clock` pattern,
  LOCKSTEP helpers shared by panel and backend; one digest push, quiet hours, snooze — all
  inherited. Per-coral notifications are refused: that is spam, not care.
- Recommended cadences (overridable per coral and per group in Settings, fields only):
  new arrival 3 days for 30 days → then group default: SPS 7, LPS 7, softies 14, NPS 7
  (their feeds are daily and already logged), clams 14. `criticalAfterDays` = 2× cadence,
  the manual-test convention.
- Feed reminders: from the table in §2.3, on by default only for the groups that need
  target feeding; NPS animals defer to the compiler's plan (never two clocks for one
  mouth — the 0.7.158 rule).

### 3.6 Feeds, foods and the mouth

- Logging a target feed: pick the coral(s), pick a **shelf** product (the foods you own,
  filtered to the ones whose category and particle window fit the mouth), optional amount,
  optional response. Rows land in the feed ledger with `coralId` and `to: "tank"`, so the
  Feeding hub, Pulse and the feed log count them like any other tank feed.
- Recommended foods = the group table ∩ the shelf, with the mouth note in words ("mysis
  fits; rotifers are too fine"). When the shelf has nothing that fits, say so ("nothing on
  your shelf fits a scoly's mouth — a mysis-sized meaty food would"). Never a brand list.
- Consumable debit: a target feed is a pinch, not a millilitre. No automatic debit; an
  optional "about N ml" on the row debits the bottle if given. §8 Q6.

### 3.7 Tie-ins (cheap ones first)

1. **Diagram / Pulse wall**: colony glyph carries its state — dim + slow pulse when
   "needs you", a faint ring when unchecked past cadence. Pulse focus card grows the score,
   the last check-in line and the hero photo. Calm copy only.
2. **Reef Layer placement sanity**: LPS in an SPS crest slot → context insight ("high light
   and flow for a hammer"); Euphyllia adjacent to a non-Euphyllia LPS → "sweeper reach"
   insight. The slots already encode zone.
3. **Water context** (§3.3): alert history + live-stats ring buffers for the 7 days before
   each check-in. No new maths — read the ledgers that exist.
4. **NPS**: `npsId` links the compiler's species card; the feed log's response column
   feeds the colony's "feeding" signal automatically for NPS animals (LOCKSTEP: the diary
   reads the feed log, never re-derives).
5. **Camera**: check-in frame grab; before/after slider between any two check-in photos;
   a per-coral timelapse strip is v2 (it needs a crop region per colony).
6. **Vision**: fish zone visits shown on the colony card ("your tang visited this zone 41
   times this week") when a Frigate zone is bound to the coral. Optional, default off.
7. **ICP**: a flagged trace lands as context on every coral in the groups it affects
   (e.g. iodine → softies/xenia; potassium → SPS colour).
8. **Spawning arc**: corals with `taxon` in Acropora/Montipora get the spawning window on
   their card — the program already knows the night.

---

## 4. Really cool suggestions (ranked by value ÷ cost)

1. **"Same angle, same light" camera frame at check-in** — the one thing every article
   asks for and no app can do, because no app owns the camera and the light schedule.
2. **"Why" on the colony card** — the water week, the neighbours, the placement, the
   shelf, in one paragraph. This is the intelligence-layer moment; the score alone is not.
3. **CoralWatch swatches for colour** — a real standard, six taps, no free text.
4. **New-arrival protocol** — dip / QT flags, 3-day check-ins for 30 days, the pest
   torch inspection on day 7 and 21, then it graduates to the group cadence with a note.
5. **In memoriam / lessons** — lost corals keep their record with the cause and the water
   week; the diary's "lessons" view lists what was going on each time something died.
   This is the feature a spreadsheet never gives you.
6. **Round mode in diagram order** — the check-in walk is the rockwork walk.
7. **Frag ledger** — "fragged 3 from this colony", a child entry with `source: frag of X`;
   value/ROI can sit on top later if wanted (Coral Tracker's whole pitch, at zero cost).
8. **Sweeper reach warning** from slot adjacency.
9. **Coral CV share card** — one PNG: photo, taxon, in your tank since, score trend.
10. **Fish-nip evidence** from vision zones.

Parked / refused: AI photo-based health grading (a bright white edge under blues is not
something to guess at from a phone JPEG; the vision-integration plan stays its own doc),
daily check-in cadences, per-coral push notifications, automatic consumable debits for a
pinch, and any "coral value" headline (this is a diary, not a portfolio).

---

## 5. Staged build (once §8 lands)

| Stage | Scope | Touches |
|---|---|---|
| **A — registry v2** | fields in §3.2, status tombstones, cap 60 / drawn 16, Corals tab with cards + strip, Settings group (fields only), migration of `nps.species` → `npsId` entries | const, normaliser (+ schema bump), panel tab + dialog class, tests |
| **B — check-ins + score** | ceremony, ledger WS, score maths (LOCKSTEP module, Python + panel mirror), confidence clock, synthetic due task + digest, quiet hours | `livestock.py` (new, like `cultures.py`), `_maintenance_due_items`, panel, tests both sides |
| **C — feeds + foods** | feed rows with `coralId`, group table + mouth windows, shelf filter, feed task, Feeding hub / strip / Pulse counts | nps.py (MOUTHFUL groups), feed_log, panel |
| **D — photos** | per-coral photo timeline + caps, camera frame grab, compare slider | capture store, WS, panel |
| **E — the why** | water-week context, placement + sweeper insights, ICP context, NPS feed-response link, diagram/Pulse glow, lessons view | panel mostly; small backend readers |

Every stage ships on its own; A+B is the version that beats Fusion.

---

## 6. Sources

- Coral Tracker — https://coral-tracker.com/
- NextUpReef, "Best reef tank tracking app in 2026" — https://nextupreef.com/blog/best-reef-tank-tracking-app
- Coralline — https://coralline.app/ · ReefDeck — https://reefdecks.com/ · AQma — https://play.google.com/store/apps/details?id=pl.aqma.aqma_aquarium_log
- Reefs.com, "Neptune Apex Fusion's powerful logging tool" — https://reefs.com/neptune-apex-fusions-powerful-logging-tool/
- CoralWatch, "Using the Coral Health Chart" — https://coralwatch.org/monitoring/using-the-chart/ and https://coralwatch.org/product/coral-health-chart/
- Chicago Fish Guy, "Coral health: early warning signs reef keepers miss" — https://www.chicagofishguy.com/post/coral-health-warning-signs
- AGRRA coral indicators — https://www.agrra.org/coral-reef-monitoring/coral-indicator/
- Fancyreef, "Target feeding LPS corals" — https://fancyreef.com/target-feeding-lps-corals/
- Bubble Magus, "How often should you feed corals" — https://bubble-magus.net/blogs/aqua-feeding-101/how-often-should-you-feed-corals
- My Reef Log, "Feeding guide for LPS corals" — https://www.myreeflog.com/learn/lps-corals-feeding
- AlgaGen, "LPS coral care" — https://algagen.com/blogs/marine-fish-nutrition/lps-coral-care-simple-feeding-and-lighting-guide

---

## 7. Where the reef-layer glyph set falls short (for the record)

The 36 art species are drawing buckets, not taxonomy: "brain" is three genera, "acan" is
now Micromussa, "plate" means Montipora but "fungia" is also a plate. The diary needs
`taxon` free text on top and must never make the art species the identity. The group →
cadence / feed table keys off the art species deliberately (it is the only classification
every entry is guaranteed to have).

---

## 8. The grill — questions for Reece before anything is built

Each has my recommendation in brackets. Push back where it is wrong.

1. **Scope: corals only, or all livestock?** Fish are the first thing a beta tester will ask
   for, and vision already tracks fish species. [Corals + anemones + clams in v1, exactly
   the Reef Layer's species set. Fish = v2 with the vision species list as the seed. Call
   the tab **Corals** now and rename to Livestock when fish land; do not build a generic
   "animal" schema up front.]
2. **Merge the NPS species tick-list into the registry?** Today `nps.species` is a list of
   library ids with no colony identity; the compiler, the hatchery coverage and the shelf
   all read it. Merging means a migration and a LOCKSTEP derivation; not merging means a
   sun coral exists twice. [Merge. Migration creates one diary entry per ticked id; the
   compiler reads `derived_nps_species(config)`. Worth the risk because "one animal, one
   record" is the whole point.]
3. **Cap:** 60 registered, 16 drawn? A big mixed reef has 80+ frags. [60 in v1; raise later
   once the config-blob size is measured on your tank. Photos are the real budget.]
4. **Does colony health touch the Reef Health headline?** [No. Self-reported observations
   must not move a number that today comes from probes. Reef Health gets one context
   insight: "2 colonies need you". Reversible later if it earns it.]
5. **Check-in cadences:** new arrival 3 d × 30 d, then SPS 7 / LPS 7 / softies 14 / clams
   14, critical at 2×. Too nagging for your tank, or not enough? And is the cadence
   overridable per coral, per group, or both? [Both; per coral wins.]
6. **Target feeds: rows in the existing feed ledger with `coralId`, or a separate
   `livestock.feeds` ledger?** Shared ledger means the Feeding hub, strip and Pulse count
   target feeds as tank feeds (they are); separate keeps NPS clean. [Shared ledger, `to:
   "tank"`, `coralId` on the row; no automatic bottle debit; optional "about N ml".]
7. **The photo budget:** 24 photos per coral, global cap ~400 MB, oldest evicted? Or
   unlimited and let the disk be the keeper's problem? [Capped, with the cap in Settings.]
8. **Lost corals stay in the diary** with cause + the water week (the lessons view), and
   drop off the diagram. Or does a loss delete the entry as today? [Keep. Losing the record
   is losing the lesson.]
9. **Frag ledger + value in v1, or later?** `source: frag of <id>` is cheap; price/value is
   cheap but changes the feel of the feature. [Source + frag link in A; `paid` as a plain
   optional field; no value, ROI or "collection worth" anywhere.]
10. **CoralWatch 1–6 for colour, or a plainer "paler / same / darker than usual"?** The
    chart is a real standard but needs a same-light discipline. [Both: the swatch picker
    stores 1–6, the card speaks in "paler than usual".]
11. **Camera frame grab at check-in** requires a camera bound and a timelapse-style light
    window; on your tank that is the ELP over go2rtc. Worth it in v1 (stage D) or v2?
    [Stage D as listed; the check-in must work with no camera at all.]
12. **Personality:** the calm strip copy ("Fourteen colonies, all accounted for. Go and
    enjoy them.") under the Cheeky toggle; never on a colony that is anything but fine.
    [Yes, per the standing rule.]
13. **Name:** "Coral diary", "Corals", "Colony log", "Livestock"? [Tab: **Corals**. The
    feature's name in release notes: the coral diary.]

---

## 9. Decisions — LOCKED 2026-09-15 (Reece: "build with your recommendations")

All thirteen §8 recommendations stand: corals + anemones + clams only (tab **Corals**, in
the Home group after Diagram); the NPS tick-list MERGED into the registry; 60 registered /
16 drawn; colony health never touches the Reef Health headline; cadences arrival 3 d × 30 d
then SPS 7 / LPS 7 / softies 14 / clams 14, overridable per coral (own wins); target feeds
on a per-coral ledger with an optional shelf debit and no automatic debit for a pinch; photos
capped per coral (24, Settings); lost corals keep their record (the Lessons view); source +
frag note and a plain optional `paid`, no value or ROI anywhere; CoralWatch 1–6 stored, the
card speaks in "paler than usual"; camera frame grab parked for stage D; personality on the
calm strip only; release-note name "the coral diary".

## 10. As built — v0.7.192 (2026-09-15): stages A + B + C, and the photo timeline from D

**Backend.** `livestock.py` (new, pure): the group table (`GROUPS`, `SPECIES_GROUP`),
`check_cadence` (own > arrival > group), `feed_cadence` (null = group, 0 = off),
`score_checkin` (losses + caps, `SCORE_LOSS` / `SCORE_CAP` tables), `coral_state` (score,
grade, trend, word, the confidence clock: past 2× cadence caps at 70 and reads stale; never
looked at = no score), `summary` (counts + due lists), `mouth` / `foods_on_shelf` (the NPS
matcher's rule, reused). `__init__.py`: `_normalise_livestock` (registry v2 fields, statuses,
ledgers keyed by coral and dropped with it, the one-shot `npsMigrated` migration that turns
`nps.species` into `npsId` entries), `_normalise_nps_config` now DERIVES `nps.species` from
active corals, `_livestock_preserve_runtime` (check-ins, feeds, photo timelines, a newer
WS-stamped status, a first-look baseline) on both save paths, WS `livestock_summary`,
`coral_checkin` (+`_undo`, 24 h tombstone; the FIRST look becomes the baseline when none is
set), `coral_feed` (+`_undo`; `ml` with a `productId` debits the bottle as a tank feed),
`coral_status` (drops the rockwork slot, keeps the record), `coral_photo_upload` now a
stamped timeline with the keeper's cap evicting the oldest file, and `_maintenance_coral_nags`
riding the daily digest (one line for check-ins, one for feeds; off with the diary's switches).
Schema 58 → 59.

**Panel.** Corals tab (mission row: Colonies / Check-ins / Target feeds; filters; cards with
score pill + trend arrow + due chips; the Lessons list under Lost & gone; calm quip under
Cheeky), the check-in ceremony (`coral-checkin-dialog`: tap rows, six CoralWatch swatches in
the colony's hue, live score preview, photo for this look, Round mode = Save & next over every
due colony), the diary dialog (`coral-diary-dialog`: "why it reads N", identity fields,
clocks + baseline, the check-in timeline with Undo, feeds with Undo, status buttons), the feed
dialog (`coral-feed-dialog`: multi-pick, shelf filtered to the mouth, optional ml). The
rockwork draws active colonies only; a colony that needs you dims and pulses, one unchecked
past its cadence wears a dashed ring. Pulse focus card carries the score line. Mission card
"Corals". Settings → Corals (reminders, arrival window, photo cap — fields only). The NPS
species grid ticks/unticks registry entries. LOCKSTEP mirror `_coralState` pinned by
tests/test_panel_corals.mjs against tests/test_livestock.py's numbers.

**Not built yet (stages D/E remainder):** camera frame grab at check-in, before/after
slider, water-week context on the card, placement/sweeper insights, ICP context, vision zone
visits, Coral CV share card, frag ledger UI (the `source` field takes "frag of X" as text).

## 11. The catalogue — v0.7.193 (2026-09-15)

Reece: "add all the NPS corals to the coral picker, and expand on other species." The picker
is now a **grouped catalogue of 100 species** (SPS 16 · Euphyllia 8 · LPS regular feeders 15 ·
LPS meaty 7 · soft 19 · anemones 5 · clams 4 · **NPS 24 = the whole NPS library**) drawing with
the 36 original glyphs (`_coralArtOf`; the rock zone follows the glyph). An NPS tile's species id
IS the library id, so picking one sets `npsId` and ticks the species for the feed plan; the
migration now stores the library id as the species too. `const.CORAL_SPECIES`,
`livestock.SPECIES_GROUP` and the panel's `_coralCatalogue()` are LOCKSTEP — an id added to one
is added to all three (test_livestock pins every CORAL_SPECIES has a group; test_panel_diagram
pins every catalogue id draws with a real glyph). "suncoral" / "gorgonian" stay valid legacy ids
outside the picker. The diary's Species select is grouped the same way and carries `npsId` along.
