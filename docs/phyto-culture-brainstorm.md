# Phyto culture — Nannochloropsis on the rack · brainstorm (2026-09-20)

> **STATUS: §8 LOCKED 2026-09-20. Stages A (0.7.207, §10), B (0.7.208, §11) and C (0.7.209, §12) BUILT 2026-09-21 — unverified on Reece's HA. Stage D (the camera/phone green index) parked with drip Stage D; the hardware track shelved.**
> Grows the cultures arc (docs/live-cultures-brainstorm.md — the v1 grill parked "own phyto
> culture = a later card, needs light", 2026-09-03) and closes the phyto-drip brief's loose end
> (docs/phyto-drip-brainstorm.md §5.4 Q3 / §10: "a phyto culture on the rack feeding the jar is a
> cultures-arc follow-on"). Trigger: the rotifer cone crashed (2026-09-20 — Reece: probably dead on
> arrival; out of scope here); a 250 ml *Nannochloropsis oculata* liquid starter, 250 ml of f/2 and
> a fresh rotifer starter are on the way (§2.1).

## 1. The idea in one line

A third culture on the Cultures rack whose clock is **light, not food**: a lit vessel that greens
up over a week, is split 50–70 % into a **fridge bottle on the food shelf**, and that bottle — one
ledger — doses the tank by hand every day (the shelf's own plan), loads the Dendro drip's jar once
the pump is bound, and feeds the rotifer cone by tint when the rotifers run. The card says how
dark the water is, how many days to the next split, how much light the vessel actually got
(sun and lamp), whether the room is about to cook it, and whether the vessel is the right size
for what the rack drinks.

Why it matters: Reefphyto's guide is a good protocol and nobody has turned it into a system. The
things a keeper actually loses cultures to — a lamp on the wrong timer, a short autumn day, a
heatwave, re-dosing f/2 mid-cycle, a split too deep, a culture held at peak until it turns, a
rotifer in the phyto — are all facts OpenReef already holds or can hold. And for a **tank-first**
keeper the fridge bottle is the piece the guide never names: it reconciles a weekly split with a
daily dose.

## 2. What already exists (honest map)

- **The culture engine is generic — mostly.** `cultures.py` runs any species from a preset:
  `culture_state` (none / crashed / establishing / producing, chore clocks off stamps, restart on a
  sign or on slow clearing), `cadence_for` with per-jar overrides, `refill_guide` (the measured jug:
  mix + RODI to a target ppt), `harvest_guide` (harvest + purge, the 30 % warning), `rig_state`
  (the drawing's inputs), `learned_cadences` (rolling three, Apply chips), `risk_line`
  (explainable, never a score), `heat_guard` (the cooling projection against the species band,
  rack offset), `tint_strip` / `feed_timeline`, `replay_state` + tombstoned Undo, `acclimation_plan`.
  The orchestration (`_cultures_log_apply`, `_cultures_restart_apply`, `_cultures_split_apply`,
  `_cultures_push_plan`) is one tap → every ledger.
- **What does NOT fit a phyto vessel:** the clocks are *feed / harvest / restart / water change* —
  a phyto culture has no feed (light and one nutrient dose per split); `TINTS` is a **clearing**
  scale (green → clearing → clear = the rotifers ate it) where phyto needs a **darkening** scale
  (pale → green → dark, with "off-colour" as a sign); `feed.doseMl` is capped at 200 ml (a home
  culture dose into a cone is 100–300 ml); `refill_guide` is two-way (mix + RODI) and knows nothing
  of "phyto water as part of the refill"; `volumeL` is settings-owned (a scale-up split changes it);
  there is ONE rotifer fridge bottle; `CULTURE_JARS_MAX` is 4.
- **The shelf is the right home for the harvest.** `consumables.products` already carries
  `refrigerated`, `stirDaily`, `shelfLifeDaysOpened`, `openedAt`, `remainingMl`, `history`,
  `cellsPerMl` (0 = unknown, "set by tint"), the runway, the reorder nudge, the **hand-dose plan**
  (`hand_dose_state`: `doseMl` + `doseEveryDays`/times a day, the *Dosed N ml* tap, the
  `nps_dose_<pid>` reminder, the strip mark) and `_consumable_debit(..., to=tank|soak|jar)` as the
  single choke point. The cone's feed already debits a linked bottle (`_cultures_feed_debit`); the
  drip's pump already debits its linked bottle; hand doses already log. The rotifer bottle's fill
  rule — oldest stamp wins, the brim is the brim, a mixed load only keeps a claim all of it earns
  (`_cultures_bottle_fill`) — transfers as-is. `live_cone_product` is the *source* pattern for
  keepers who feed straight from the vessel.
- **The drip's jar** (`schedule.standing`, `reservoir.refrigerated`, `reservoir_clock`,
  `dosing_mark_refreshed` = **Loaded**, `standing_care` = stir / fridge / flush) is the consumer
  the drip brief promised: today "Loaded" only stamps the day clock; it can debit the bottle.
  The drip itself (path A, the kalk stepper) is released (0.7.205) and not yet set up on Reece's HA.
- **The mixing station** makes the water: `_cultures_mix_ppt`, `_mixing_hatchery_debit` (mix share
  only, RODI is not the vessel's). At 35 ppt the vessel's water IS the station's water.
- **Plugs:** the stirrer plug (`standing.stir {switchEntity, everyHours, burstMinutes}`, driven from
  the dosing tick, own stamps, retry on a failed call) and the spawning plug are the two shapes a
  lamp can borrow. Own readings, never the recorder (the cooling arc's doctrine).
- **The sun:** nothing in the integration reads HA's sun entity today; its rising/setting
  attributes give the day length for free (§5.6).
- **Heat:** `heat_guard` + `rack_offset_c` + `cultures.tempEntity` (hatchery fallback). Nanno's
  band is different (20–27, sensitive near 30) — a preset, not new code.
- **Camera:** `vision.py` is Frigate events (feed-watch, capture). No tint index exists yet —
  drip Stage D is parked; a culture density index is the same piece of work (§6).
- **Prior decisions that stand:** Reef Juice is a shelf product, never a culture (0.7.129); the
  continuous phyto/rotifer reactor is SHELVED on the hardware track (v1 grill #10, audit 09-10) —
  the phyto-only half of it comes back as §5.7's reactor path; the enrichment stays algae-in-drops;
  Inkbird-style hard guards are never software.

### 2.1 What arrived (the 2026-09-20 order) and what is on the bench

| Item | Role | Facts |
|---|---|---|
| **Phytoplankton Liquid Starter Culture — N. oculata, 250 ml** | seeds vessel A | fridge until scaled, **use within four weeks of delivery**; 1 part starter to 4 parts medium (starter page) or the whole 250 ml into 3.5 L (kit guide) |
| **Phytoplankton Nutrient — Guillard's f/2, 250 ml** | the split's dose | label: **3 ml per 2 L** of fresh water (1.5 ml/L); at 3.2 ml a split that is ~78 splits — the shelf's runway will say so |
| Copepod Feed 100 ml | the Tigriopus tub's food | the preset ships as 50 ml; `bottleMl` is the keeper's |
| JBL Artemio 4 sieve set | rotifer / brine sieving | nothing to do with phyto (2–4 µm passes every mesh) |
| Live Rotifers 500 ml | the cone's new starter | out of scope here (Q1) |
| Oyster Relish Concentrate 50 ml | a coral food for the shelf | a preset to add after reading its page — not this arc |
| **On the bench:** one Reefphyto 4 L culture vessel, an air pump, an LED strip; the rack gets sunlight; a purpose-built phyto reactor is a possible later purchase (§5.7) | | |

## 3. Research digest (2026-09-20, one inline sweep)

**Reefphyto — the supplier, read from the pages.**
- *Liquid starter (250 ml):* keep refrigerated until scaling up, **use within four weeks of
  delivery**; add at roughly **1 part starter to 4 parts prepared medium**; daylight LED 12–16 h;
  continuous aeration; visible greening days 3–7; first harvest **7–10 days**; then **remove 50 to
  70 %** and replace with fresh saltwater + f/2
  ([starter page](https://reefphyto.co.uk/products/liquid-starter-culture-nannochloropsis)).
- *Kit / guide:* 4 L container, **3.5 L of 1.025 seawater + the whole 250 ml starter** (the kit
  starter is stated at ~2 billion cells/ml); sterilise with dilute bleach, rinse; f/2 **6 ml for
  3.5 L** at set-up (≈ 1.7 ml/L) — the nutrient page says **3 ml per 2 L** (1.5 ml/L): *the label
  wins*; **never re-dose mid-cycle** ("adding more nutrient during the initial culture phase can
  cause a culture crash — wait until you harvest and dilute"); **6000–6500 K** daylight LED
  **10–15 cm** away, **16 h on / 8 off** ("the simplest and most effective setup"); **20–27 °C**;
  days 1–3 "light, thin green", 3–7 "green deepens noticeably", 7–10 "dense, dark green" =
  harvest; the **30/70 rule** (always leave ≥ 30 %); the remainder "re-establishes the harvested
  volume within three to five days"; one 4 L vessel "typically produces **two to three litres** of
  dense Nannochloropsis per week"; keep "a second small vessel (even a clean glass bottle on a
  windowsill with some f/2 and a splash of culture)" as backup; **refresh from a clean start every
  three to four harvest cycles**; harvested phyto at **4–8 °C is viable two to three weeks, shake
  every one to two days**; crashes are "most commonly caused by contamination, nutrient depletion,
  insufficient light, or temperature shock"; past its best when the rich green dulls to **grey or
  yellow** or it smells; "not greening up / unusual colour / foul smell / **cloudy rather than
  green**" → their troubleshooting centre, or Darren
  ([guide](https://reefphyto.co.uk/pages/guide-to-culturing-phytoplankton),
  [kit](https://reefphyto.co.uk/products/phytoplankton-culture-kit),
  [f/2 nutrient](https://reefphyto.co.uk/products/phytoplankton-nutrient-modified-f-2-medium),
  [dosing blog](https://reefphyto.co.uk/a/blog/4-ways-phytoplankton-impacts-your-reef)).
- *Rotifer guide:* only ever feeds the concentrate (Nanno + Tetraselmis); says nothing about
  home-grown phyto as feed or refill; crash causes = **overfeeding in a single dose (ammonia /
  nitrite)**, insufficient aeration (sulphurous smell), skipping the fortnightly clean; signs =
  foul smell, dark or discoloured water, rotifers not swimming, sinking or clumping; contamination
  = never aquarium water ([rotifer guide](https://reefphyto.co.uk/pages/rotifer-culture-guide)).

**Biology and numbers (papers and the better hobby sources).**
- Cell **2–4 µm**; hobby cultures reach **> 10–20 million cells/ml**; a concentrate is ~2 billion —
  **a home culture is ~100–200× thinner than the bottle the cone is used to**. Doubling **12–24 h**
  under optimal conditions (one *N. oceanica* strain 14 h). Temperature **20–30 °C, best ~25**,
  and *"extremely sensitive to temperatures near 30 °C"* (abrupt growth drop). Salinity **20–35 ppt
  optimal** (12–40 tolerated); one study found higher counts at 25 ‰ and 33 ‰ — 35 is fine.
  pH **7.5–9, optimum 8–8.5**; EPA 24–39 % of fatty acids, **no DHA** → the DHA soak stays
  ([PodDrop species page](https://www.getpoddrop.com/pages/nannochloropsis-oculata-live-phytoplankton),
  [temperature study](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3896454/),
  [salinity × f/2 study](https://www.researchgate.net/publication/366408318_Ritmo_de_crecimiento_de_Nannochloropsis_oculata_usando_diferentes_concentraciones_de_salinidad_y_F2_Guillard_en_10_y_23_dias_de_cultivo),
  [OGTR biology doc](https://www.ogtr.gov.au/sites/default/files/files/2021-07/the_biology_of_nannochloropsis_oceanica_a_microalga.pdf)).
- **Light:** 100–200 µmol photons m⁻² s⁻¹ at the vessel, 16:8 or 24:0 (PodDrop); a UK window in
  autumn delivers a fraction of that indoors, and the astronomical day at 51.5° N is ~12 h 20 min
  on 20 September, ~11 h 40 on 1 October, ~9 h 50 on 1 November, ~7 h 50 at the solstice —
  **sunlight alone is a summer method here**; too much direct sun yellows the cells and heats a
  small vessel (the kit guide's LED is "simplest and most effective" for a reason).
- **pH is a free growth gauge:** photosynthesis draws CO₂ down and pH climbs; past the band growth
  slows or the culture crashes; Industrial Plankton holds a pH set-point with CO₂ in production
  ([Industrial Plankton](https://industrialplankton.com/2022/11/24/co2-and-ph/),
  [culture quality indicators review](https://www.tandfonline.com/doi/full/10.1080/07388551.2020.1854672)).
  Aeration is the hobby's CO₂ supply: it never switches off.
- **Semi-continuous vs batch:** a **30 % daily dilution** was the most productive rate in one
  Nannochloropsis study; harvest just before stationary for the most biomass; log-phase cells are
  the better food ([harvest frequency study](https://www.sciencedirect.com/science/article/abs/pii/S2211926420305956),
  [Algae Research Supply primer](https://algaeresearchsupply.com/blogs/news/batch-semi-continuous-and-continuous-cultures)).
- **The rotifer coupling (for Stage C):** rations of **80,000–200,000 cells per rotifer per day**
  in enrichment work; hobby copy says "up to 115,000 a day"; rotifer growth > 0.9 /day once the
  water holds **0.3–1.5 × 10⁶ cells/ml**; FAO's batch method fills the rotifer tank WITH algae at
  **13–14 × 10⁶ cells/ml** for 100 rotifers/ml over two days; the hobby rule is *keep it light
  green, never clear, feed at least twice a day*; 90 % Nanno + 10 % Tetraselmis is the classic mix
  ([N. gaditana rations](https://www.sciencedirect.com/science/article/abs/pii/S0044848617317829),
  [algae density × rotifer growth](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5893227/),
  [FAO rotifer chapter](https://www.fao.org/4/w3732e/w3732e0h.htm),
  [Reefs.com Breeder's Net](https://reefs.com/magazine/the-breeder-s-net-the-rotifer-and-rotifer-home-culture/)).
- **Crash and contamination signs beyond Reefphyto's:** yellowing = too much light or a competitor;
  settling in mats on the bottom = crash; bubbles standing at the surface = ammonia; *Amphora*
  diatoms clump the cells; **a rotifer or ciliate in the phyto grazes it flat** — separate airline,
  syringe and sieve for the phyto, always
  ([oilgae thread](http://www.oilgae.com/forum/viewtopic.php?f=31&t=1192),
  [Reef2Reef](https://www.reef2reef.com/threads/what-is-happening-to-my-phyto-culture.729561/),
  [Amphora clumping](https://www.frontiersin.org/journals/microbiology/articles/10.3389/fmicb.2023.1271836/full)).
- **Density without a lab:** a **Secchi stick** with a species-specific log fit (one hobby Nanno
  set-up: log₁₀ cells/ml ≈ −0.63 × depth cm + 17.3 — *their* culture, *their* light; needs one
  count to calibrate) ([Controlled Mold](https://controlledmold.com/measuring-cell-growth-using-a-secchi-stick-and-lots-of-fun-math/),
  [Algae Research Supply](https://algaeresearchsupply.com/pages/measuring-growth)); **RGB image
  analysis** tracks biomass from the red + green channels, blue carries nothing
  ([J. Appl. Phycol. 2021](https://link.springer.com/article/10.1007/s10811-021-02634-6));
  a **TCS34725** colour sensor runs natively in ESPHome and reads a liquid at 3–10 mm behind a
  shroud with its own LED — a DIY transmitted-light OD sensor
  ([ESPHome](https://esphome.io/components/sensor/tcs34725/)); **Pioreactor / Phenobottle /
  Alg-Flex** are the open-source OD-driven bioreactors — prior art, none of it in the reef hobby
  ([Pioreactor](https://pioreactor.com/), [Phenobottle](https://github.com/HarveyBates/Phenobottle),
  [Alg-Flex](https://www.mdpi.com/2673-9410/6/3/96)).

**First-mover read:** dosing pumps and fridge rigs for *bought* phyto exist (NPS brief §2); the
DIY reactor threads exist (cultures brief §1.1); nothing tracks a home culture's density, light,
heat and split as clocks, and nothing couples the culture's yield to what the rack drinks.

## 4. The maths

### 4.1 Who drinks what (the sizing line the card must show)

Assumptions, all overridable and all estimates (nobody has counted this culture): a dark home
culture ~1.5 × 10⁷ cells/ml; a concentrate ~2 × 10⁹; a 4 L vessel at 3.5 L yields 2–3 L a week;
Reece's tank 52 L; the cone (later) 2.5 L at a "light green" ~1 × 10⁶ cells/ml.

| Customer | Home culture | Concentrate |
|---|---|---|
| **The tank, one tint** (10,000 cells/ml in 52 L = 5.2 × 10⁸ cells) | **~35 ml** | 0.26 ml |
| The tank by hand, once or twice a day | **~35–70 ml/day** | — |
| The drip holding the density (turnover ~10/day, phyto-drip §4) | **~350 ml/day** by tint | 5.8 ml/day (Reefphyto heavy) |
| The cone, one tint dose (Stage C) | ~170 ml | 1.25 ml |
| The cone, two doses a day | ~330 ml/day | 2.5 ml/day |
| **One 4 L vessel on a weekly 70 % split** | **~2.45 L/week ≈ 350 ml/day** | — |

Read it two ways. **Tank-first (Reece now):** a hand-dosed 52 L tank drinks ~5–10 % of what a
3.5 L vessel makes; the surplus is a week in the fridge bottle, then the cone or the sink. The
drip at heavy turnover would take the lot. **Rotifers (Stage C):** one vessel ≈ one cone at hobby
tint; at real rotifer densities the concentrate stays the calorie source. Either way the card
says it in one line — *"the tank drinks ~50 ml a day; this vessel makes ~350 — the rest is the
fridge bottle, the cone, or a smaller working volume"* — §8.8 #13 of the cultures brief
(demand-driven sizing), finally with a reason. The honest fix for a tank-only keeper is a
**smaller working volume**, and the starter page's own 1:4 recipe is exactly that (§5.11).

### 4.2 The split jug

At 35 ppt (LOCKED, Q5) the fresh water is the mixing station's water, no cut: a 60 % split of a
3.5 L vessel = 2.1 L out, 2.1 L of 35 ppt mix in, **3.2 ml f/2**, the mix share debited from the
vessel as every culture refill is. The three-way jug (phyto + mix + RODI) only appears when a
harvest refills a *brackish* cone — Stage C: cone at 27 ppt, 675 ml to replace, 350 ml of 35 ppt
phyto → 171 ml mix + 154 ml RODI + the phyto; `refill_guide` gains an optional
`(phyto_ml, phyto_ppt)` component then.

### 4.3 f/2 and the vessel

Fresh water per split = split % × working volume; f/2 = 1.5 ml/L of the **fresh water only**
(label wins). Nutrient is dosed **only at a split, a scale-up or a fresh vessel**, never mid-cycle
(Reefphyto's crash warning) — the ceremony owns it, and a Looked tap never offers it.

### 4.4 Growth expectations the clocks encode

Seed → first harvest 7–10 d (density-gated, not age alone — the audit's rule; expect longer under
window light); split → dark again 3–5 d; fresh vessel every 3–4 cycles (≈ 4–5 weeks); fridge
bottle 14–21 d; starter in the fridge ≤ 4 weeks. Doubling 12–24 h means a 60 % split (× 2.5) is
~1.3 doublings — the 3–5 days is the hobby lamp, not the alga.

### 4.5 The medium into the tank (Q12b)

Fresh f/2 is roughly 880 µM nitrate (~55 mg/L as NO₃) and 36 µM phosphate (~3.4 mg/L); a dark
culture has eaten most of it. Worst case, 100 ml of undepleted medium a day into 52 L is
~0.1 ppm NO₃ and ~0.007 ppm PO₄ a day. A one-line note in the nutrient budget ("home culture:
f/2 medium, mostly consumed — not priced"), never a figure.

## 5. The design

### 5.1 A species preset, kind `phyto`

```
{"id": "nanno", "name": "Nannochloropsis (phyto)", "kind": "phyto", "latin": "Nannochloropsis oculata",
 "vesselKind": "bottle",                       # a lit vessel — the 4 L container; "reactor" later (§5.7)
 "tempMinC": 20, "tempMaxC": 27, "tempHardMaxC": 29, "tempActC": 30, "tempCriticalC": 32,
 "salinityPpt": 35,                             # LOCKED: the tank's water (Q5)
 "lightHours": 16, "lightKelvin": "6000–6500 K", "lightCm": "10–15",
 "nutrientMlPerL": 1.5, "nutrientProduct": "Phytoplankton Nutrient (f/2)",
 "splitPct": 60, "splitIntervalDays": 8, "firstHarvestDays": 7, "recoverDays": 4,
 "restartCycles": 4,                            # a fresh, sterilised vessel every 3–4 splits
 "bottleShelfDays": 21, "starterShelfDays": 28,
 "tintTarget": "dense, dark green — the harvest colour; grey, yellow or cloudy is a sign",
 "tints": ("pale", "green", "dark", "off"), "signs": ("yellow", "brown", "cloudy", "clumping", "foam", "smell", "settling")}
```
Heat tiers are precautionary (papers: abrupt decline near 30 °C), phrased as inspect-and-protect,
never as measured limits — the audit's tone holds. `feedIntervalH`, `harvestPct`,
`waterChange*` are meaningless for the kind and hidden; `CADENCE_FIELDS` grows `splitPct`,
`splitIntervalDays`, `restartCycles`, `lightHours`. `tints_for(species)` / `signs_for(species)`
replace the module-level scales at every reader; the normaliser accepts the union.

### 5.2 The vessel's clock — light, not food

`culture_state` for `kind == "phyto"`: **none → establishing** (seeded, first cycle, "day 4 of ~7,
greening") **→ producing** (after the first harvest; the cycle ring = days since the last split ÷
the split interval) **→ crashed**. Clocks: **look** (daily tint tap — the density readout, the one
thing the method has), **split** (due at the interval, or *brought forward by a "dark" tap* — the
restart-on-a-sign shape, inverted: ready on a sign), **restart** (fresh vessel, `restartCycles`
splits since the last fresh vessel, or on an off-colour sign), **light** (not a chore: hours
delivered today — §5.6). No feed clock, no water change.

Two **modes** (Q7): `batch` (default — 50–70 % every 7–10 days, the 30 % seed rule) and `daily`
(semi-continuous — 20–30 % a day replaced with fresh medium, the culture held in log phase). The
tab offers `daily` once days-to-dark has been learned twice; in `daily` mode the draw is sized to
the **culture**, never to the tank — the surplus routes to the bottle (§5.3).

`density_advice` (the `feed_advice` sibling): pale and < 3 days since the split → *wait, it is
recovering*; green → *growing — dark in ~N days* (learned); **dark → split now** (into the bottle
/ the tank / the drip); **dark for three days without a split → "a culture held at peak turns —
split or dose more"** (peak-held); **off → do not harvest into anything** — check smell, light,
temperature; if it has not recovered in two days, mark it crashed and reseed from B. Tint and
elapsed days do not measure cells — the copy says so.

### 5.3 Ceremonies and the journal (the rotifer taps, re-cast)

- **Seed** — the day the starter lands. **Arrival check first** (the rotifer pouch's lesson): the
  starter's tint under a light — rich green, no smell, not grey or brown; an `off` arrival tint
  **refuses the seed** and says *contact Darren*. Then the recipe: **LOCKED default = the starter
  page's 1:4** — 250 ml into 1 L of 35 ppt water + 1.5 ml f/2 in the 4 L vessel (1.25 L working;
  small volumes green faster under window light — less self-shading — and a first cycle is the
  riskiest), scaling to the kit's 3.5 L at the first splits (§5.11); the kit's straight 3.5 L is
  the alternative on the same card. Stamps `starterMl`, `starterOpenedAt` (→ the four-week clock),
  lamp and air on, the f/2 debit, the mix debit. Writes `seeded` with the arrival tint.
- **Looked** — the tint (pale / green / dark / off); an optional **Secchi cm** box beside it from
  day one (nothing is inferred from it until Stage C calibrates a stick — the numbers just
  accrue); Undo for a day, tombstoned, as today.
- **Split** (= the harvest) — `ml` (default `splitPct` × working volume, warned above 70 % of the
  working volume, refused above it), **destinations, several in one tap**: `bottle` (the home phyto
  bottle — **the default**, Q9), `tank` (a hand dose straight from the vessel: the feeding-log row,
  the hand-feed reminder done, `to: tank` with the ml), `drip` (load the Dendro jar, once the pump
  is bound), `cone` (Stage C), `vessel` (seed B — the split-rides-the-restart doctrine). A
  **scale-up** is a split whose fresh water exceeds what came out (1.25 L → 3.5 L over the first
  one or two splits): `state.workingL` moves, the jug says "add 2.25 L", nothing is removed.
  **f/2 dosed** rides the tap (default on; `fresh_ml × nutrientMlPerL` off the f/2 product) and
  the fresh water's mix share comes off the mixing vessel. Writes `harvest` with `to[]`, `ml`,
  `freshMl`, `nutrientMl`, `tint`, `tempC`; the split clock re-anchors; the tint goes back to `pale`.
- **Fresh vessel** (= the restart) — the whole culture into a sterilised container of new water
  + f/2; writes `restart`; the cycle counter resets; the bleach-and-rinse routine is the note.
- **Sign** — yellow / brown / cloudy / clumping / foam / smell / settling; brings the restart
  forward and blocks harvest-to-anything until a tint tap says green or dark again.
- **Crashed** — the honest stamp; the payload offers reseed from B, **from the fridge bottle if it
  is under a week old** (a legitimate starter — a phyto-only option), or from a new starter.
- **Bottle taps** — the shelf's own: *Dosed N ml* (the tank's daily dose, §5.4), and a new
  **Shaken** tap on any refrigerated `stirDaily` product with a 48 h nag (Reefphyto's shake every
  one to two days) — generic, the drip's Stirred is the same idea.

### 5.4 The home phyto bottle — one ledger, the tank first

A real shelf product, created with the jar and kept by id (`home_phyto_<jid>`): `category: phyto`,
`brand: "Home culture"`, `bottleMl` = the keeper's fridge bottle, `refrigerated: true`,
`stirDaily: true`, `shelfLifeDaysOpened: 21`, `cellsPerMl: 0` (unknown — *set by tint*; §6 may
estimate it), and a **hand-dose plan by tint**: `doseMl` (the keeper's — the card seeds it from
§4.1's "one tint ≈ 35 ml" line as an estimate to raise or lower against the glass),
`doseEveryDays: 1`, `doseNote: "into the flow at dusk, by tint — a faint green that clears"`. That
plan is the tank's daily driver *today* (Q2): the shelf's *Dosed 50 ml* tap, the `nps_dose_<pid>`
reminder and the strip mark all exist. **Filled** by the split ceremony with the rotifer bottle's
rules (`openedAt` = the oldest unconsumed load; a top-up never renews the clock; overflow logged,
not pretended). **Debited** by: the hand dose, the drip's **Loaded** (new: `dosing_mark_refreshed`
debits the linked bottle by the jar's fill, `reservoir.jarMl` — the "auto phyto doser" path that
needs no hardware beyond the released drip), the cone's feed (`feed.productId` → this bottle;
`doseMl` cap raised to 1000; a home-culture link defaults to ~5 % of the cone's volume, "to a leafy
green" — Stage C), and a split straight to the tank. Everything downstream is free: the runway
("bottle A: 9 days at the tank's rate"), Dendro coverage, the feeding log rows with `to`, the
reorder nudge becomes a **split nudge** ("the bottle runs dry Thursday; vessel A is green — split
Wednesday"), the Pulse line. Keepers who dose straight from the vessel every day get the
`live_cone_product` shape (a SOURCE with the split clock) — user-selectable per jar (Q9), the
bottle is the default because phyto keeps three weeks in a fridge and rotifers do not.

### 5.5 The cone coupling — Stage C, but the link exists day one

The rotifer harvest ceremony gains **"refill with phyto: N ml"** (from the bottle, or straight from
a vessel that is dark today): the jug goes three-way when the salinities differ (§4.2), the phyto
is debited `to: jar`, the cone's tint goes to green without a separate feed tap. The clean-cone
restart offers the same at 100 % (FAO's batch method). **Overfeed refusal carries over**: a
refill-with-phyto while the cone is still green is refused with the feed tap's own "still green —
skip"; Reefphyto's #1 rotifer crash cause is one big dose. Deferred to Stage C by Q1; the
bottle-as-feed link (§5.4) is a one-line cap change and ships in A so the new rotifers can be
tinted from the home bottle when they run.

### 5.6 Light — sun on the rack, the LED on the plug (LOCKED Q3/Q4/Q6)

`light: {mode: sun | lamp | sun+lamp, switchEntity, onAt, targetHours: 16, latestOff: "00:00",
tempEntity?}` per phyto jar. Reece's rack gets sunlight and the LED goes on a smart plug, so his
mode is **`sun+lamp`**:
- **`sun`:** no plug; the day length comes from HA's sun entity (rising / setting attributes —
  new, tiny, nothing reads it today) and the card shows *"daylight 12.3 h (astronomical — the
  window gives less)"*; a **short-day nudge** when the day drops under ~12 h (late September at
  51.5° N: *"the days are under 12 h — put the LED on the plug"*), and once under the target it
  is a `watch` on the risk line; a **direct-sun note** once (yellowing, heat).
- **`lamp`:** the plug runs `onAt` + `targetHours` (16:8), the stirrer-plug pattern: own stamps
  `lightOnAt` / `lightOffAt` / `lightMinutesToday`, retry on a failed call, unbinding clears.
- **`sun+lamp`:** the plug turns on **at sunset** and off when `daylight + lamp = targetHours`,
  never past `latestOff` — 16 h always leaves the eight dark hours the guide wants; in September
  the lamp runs ~3.5 h, by November ~6 h, at the solstice ~8 h. Delivered = lamp hours (own
  stamps) + daylight (astronomical, an upper bound of what the rack gets — the copy says so).
- A plug unavailable or off inside its window earns a `watch` ("lamp off 3 h into its window");
  under 12 h delivered by window end, an `act` ("the culture lost a day of light — expect the split
  to slip"). Aeration is never switched; the card says why once.

Heat: `heat_guard` with the Nanno band (watch above 27, warn past 29, the pods' push shape);
`temperature_advice` copy names the alga's sensitivity near 30 and says *shade it, move it off the
sunlit shelf, a cooler room*. A vessel in the sun runs over the room and over the rack sensor — an
optional **vessel-side sensor entity** (`light.tempEntity`) reads the water itself; without it the
rack sensor + offset is the reading and the copy says it is the room, not the culture.

### 5.7 The reactor and the "auto phyto doser" (Q3, Q9)

`vesselKind: "reactor"`: a purpose-built tube (typically 2–8 L) with its own LED (its timer, or the
plug) and a **drain tap** — the harvest comes from the valve like the cone's, drawn as a lit tube.
The doser has two paths: **now** — the released drip (kalk stepper, path A) with its jar **Loaded
from the fridge bottle** each morning (§5.4, no new hardware); **later (hardware track)** — the
stepper pulling **straight from the reactor**: `reservoir.source = "culture:<jid>"`, the reservoir's
freshness is the culture's own tint/status instead of a `mixedAt` clock. One decision is parked
for that stage, with a recommendation: *a crashed or off-colour source culture PAUSES the pump.*
The jar's stale is a WARN because a day-old jar is merely weaker food; a crashed culture is
bacteria soup, and this is the one live-food case where the stop is right.

### 5.8 Backup and hygiene

- **Never zero, phyto edition (Q10):** B is a windowsill bottle (Reefphyto's own advice) — a
  second `nanno` jar of any volume (0.5 L is fine), seeded by the split ceremony's `vessel`
  destination; refresh B from A every `restartCycles` (a chore on the rack: "refresh the backup");
  after a crash A reseeds from B (the `reseedFrom` list already does this per species).
  `CULTURE_JARS_MAX` 4 → 6.
- **Cross-contamination is the phyto killer on a rack that also holds rotifers (Q12a: said
  once).** The walkthrough and the settings hint: own airline (own check valve, ideally a 0.2 µm
  filter), own syringe, own sieve; never the rotifer jug.
- **Sterilise:** the fresh-vessel ceremony's note carries the bleach-and-rinse routine; the
  container count (two, alternating) is a setting so the nag reads "sterilise the spare".

### 5.9 Surfaces (Q11: the same rack)

- **The rack tile** (`.culture-tile`, the 0.7.163 form): the jar drawing becomes a **lit vessel** —
  a lamp / sun glyph, fill colour by the darkening tint (pale → green → dark), a thin bar for light
  hours today, the cycle ring "day 5 of ~8"; labelled rows Water (pale/green/dark/off) + Secchi cm,
  Split to (bottle / tank / drip / B, multi), Litres out, New working volume (scale-up), "f/2 dosed"
  tick; notes: density advice, the sizing line (§4.1), the jug, light delivered, heat, learned
  lines; actions Looked / **Split** / Fresh vessel / Crashed / Share card.
- **The rig drawing** (`rig_state` → `_culturesRigSvg`): a lit carboy right of the cones, before
  the tub; stages gain *greening*, *split* (the jug in split mode: "2.1 L out → 1.8 L bottle +
  0.3 L tank · 2.1 L fresh @ 35 + 3.2 ml f/2"), *scale-up*, *off-colour*, *heat*, *short days*;
  a dashed arc to the fridge bottle and to the tank; B drawn faint on the windowsill.
- **The shelf card** for the home bottle: days left, the daily dose plan and its *Dosed* tap, the
  split nudge, *Shaken*, coverage.
- **Feeding hub compact card + Pulse:** *"Nanno A · day 5 · greening · split in ~2 d · bottle
  1.2 L, 9 d left · light 14 h today (sun 11 + lamp 3)."*
- **Reminders:** `culture_<jid>_look` (daily), `culture_<jid>_harvest` (the split, on the split
  clock — the existing culture task clock reads it), `culture_<jid>_restart` (fresh vessel),
  `culture_<jid>_backup` (refresh B); the tank dose is the shelf's `nps_dose_<pid>`. Push: the
  one-question day — *"Nanno A — split? · Split · Later"* — through `_cultures_push_plan` /
  `_async_push_actionable`.
- **Reef Report:** the rack's yield (litres a week) beside the rotifer harvests (Stage C).

### 5.10 Learned cadences and the risk line

`learned_cadences` for the kind: **days-to-dark** (split → first dark tap; rolling three → "your
culture darkens in ~6 days — split every 6?", Apply on `splitIntervalDays`; two samples unlock the
`daily` mode offer); **yield** (litres a week, the demand line's other half); **recovery by split
depth** (the `purge_note` shape: "70 % splits took ~5 d to darken, 50 % took ~3 d — this does not
establish the cause"); **light delivered vs days-to-dark** (a week under 14 h beside a slow cycle
earns the line, never a claim). `risk_line`: not darkening three days after a split (light? heat?
f/2 skipped?); an off-colour tap; **peak-held** (dark ≥ 3 days, no split ≥ 30 %); room past the
band; light under 12 h; f/2 not logged at the last split; more than `restartCycles` since a fresh
vessel; the starter bottle past four weeks. One sentence, the cause, never a score.

### 5.11 Sizing for a 52 L tank (the thing that bites first)

The 4 L kit vessel is sized for feeding rotifers, not a 52 L display: at 3.5 L on a weekly split
it makes ~350 ml a day against a hand-dosed tank's ~35–70 ml. So, LOCKED as the default and all of
it keeper-editable: **seed at 1:4 (1.25 L working)**; **scale up to 3.5 L only when there is a
customer for it** — the drip bound and running by tint, or the rotifer cone producing; until then
the bottle absorbs the weekly split and the sizing line says what the rack drinks and what the
vessel makes. `state.workingL` is server-written by scale-ups; `volumeL` stays the vessel's
capacity. When the tank is the only customer for good, the line's advice is "run it at ~1.5 L".

### 5.12 Config, WS and guards (concrete)

`nps.cultures.jars.<id>` (species `nanno`): `vesselKind: "bottle" | "reactor"`, `volumeL` (the
container, 4), `salinityPpt` (35), `starterMl`, `starterOpenedAt`, `mode: batch | daily`,
`light {mode, switchEntity, onAt, targetHours, latestOff, tempEntity}`, `nutrient {productId,
mlPerL}`, `bottleProductId` (the home bottle), `harvestTo: bottle | source` (Q9), `cadence
{splitPct, splitIntervalDays, restartCycles}`, `state {startedAt, workingL, lastSplitAt,
lastFreshVesselAt, cyclesSinceFresh, lastTint, lastSignAt, lastSign, crashedAt, seededFrom,
generation, lightOnAt, lightOffAt, lightMinutesToday, lightDay}` (server-written →
`_nps_preserve_runtime`), `history` rows gain `to[]` (list), `freshMl`, `nutrientMl`, `secchiCm`.
`consumables.products.home_phyto_<jid>` as §5.4 (runtime fields under the existing shelf guard;
`lastShakenAt` joins it). New WS: `cultures_split {jar_id, ml, to: [{dest, ml}], fresh_ml,
nutrient: bool}`, `cultures_fresh_vessel {jar_id}`, `consumable_mark_shaken {product_id}`;
`cultures_log {tint, secchi_cm}` accepts the phyto scale; `cultures_seed` accepts
`starter_opened_at`, `arrival_tint`, `working_l`; `dosing_mark_refreshed` gains `debit: bool`.
Engine: `tints_for`, `signs_for`, `density_advice`, `darkening_samples`, `split_guide` (the jug +
f/2 + scale-up), `light_state` (daylight from the sun entity's stamps, lamp from own stamps, the
sunset rule), `demand_line(tank_ml_day, drip_ml_day, cone_ml_day, yield_l_week, working_l)`;
`rig_state` gains `phyto[]`. Tests: `test_cultures.py` (kind phyto states, split maths incl. the
scale-up, density advice incl. peak-held, light state across the three modes and the sunset rule,
learned days-to-dark), `test_cultures_audit.py` (volume conservation, f/2 by fresh water only),
`test_nps.py` (bottle fill/debit through the handlers on the fake HA, the hand-dose plan on a home
bottle, Loaded debit, the plug through the fake HA, refusal paths incl. the arrival tint),
`test_panel_cultures.mjs` (tile, rig stage, shelf card). The runner stays last; every new WS
joins `async_register_command`.

## 6. The intelligence bit (v2) — the culture that says when it is ready

The tint is the readout, and it can be measured. Build the **green index once, use it twice**
(this is drip Stage D's tint index): a fixed patch of the vessel against a white card behind it,
the red + green channels over a stored baseline → a daily density index, the curve → days-to-dark
without a tap, and — calibrated once by a count or a Secchi reading — an estimate that could fill
the bottle's `cellsPerMl` so the drip's density line stops reading *unknown*. Three sensor paths,
all advisory, none auto-harvesting: **(a) the ELP camera / a phone photo** (no hardware,
`vision.py`-adjacent); **(b) a TCS34725 in a shroud on an ESP node** (transmitted light through a
narrow tube = OD; a phyto node on the hardware track); **(c) a pH probe on the vessel** (pH climbs
while it grows, flattens at stationary, falls on a crash — the cheapest "is it alive" signal).
The printable **Secchi stick** for the 4 L container is Stage C (Q8: "taps now, stick later") and
the cm box collects its calibration data from day one.

## 7. Refused or parked

- The continuous phyto → rotifer reactor: still shelved (hardware track); the phyto-only reactor
  path is §5.7.
- Automating the split (a pump drawing culture into a bottle): the leak-and-ammonia risk the
  skeptic refused for rotifers; the split is a two-minute jug job. The reactor's tap is the keeper's.
- Any auto-dose of home phyto by the index: the drip's rate is the keeper's, by tint.
- Switching the air pump: never.
- A "cells/ml" figure without a count or a calibrated index: never shown as a number.
- Re-dosing f/2 without dilution: the UI never offers it.

## 8. The grill — ANSWERED 2026-09-20, decisions LOCKED

| Q | Reece | Consequence |
|---|---|---|
| 1 | Rotifers: don't worry, probably dead on arrival — focus on the phyto | No rotifer-side fix in this arc; the cone coupling is **Stage C**; the bottle-as-feed link ships in A (one-line cap change); the Seed ceremony gains an **arrival tint check** |
| 2 | Priority = feed the tank, by hand until the dosing pump is set up | Default destination **bottle**; the tank's daily dose is the **shelf's hand-dose plan** on the home bottle (existing tap + reminder); the drip's **Loaded debits the bottle** as the no-hardware doser path |
| 3 | Starter + 250 ml f/2 ordered; one Reefphyto 4 L vessel, an air pump and an LED on hand; **sunlight** planned, LED if not enough; a purpose-built reactor maybe later | Light modes `sun / lamp / sun+lamp` (§5.6); UK autumn day length makes the LED near-certain within weeks — the short-day nudge says when; `vesselKind: reactor` + the reactor-as-reservoir path (§5.7) on the hardware track; f/2 250 ml → ~78 splits on the runway |
| 4 | The rack, which gets sunlight | Shared rack sensor + offset; **optional vessel-side sensor**; heat copy for a sunlit vessel; direct-sun note once |
| 5 | Salinity: the tank's | **35 ppt** — the station's water, no cut; the three-way jug waits for Stage C |
| 6 | Bind the lamp to a plug | `sun+lamp`: the plug runs from **sunset** to a 16 h day, never past `latestOff`; delivered hours are a fact |
| 7 | Default | `batch` first; `daily` offered after two learned days-to-dark; in `daily` the draw is sized to the culture, the surplus to the bottle |
| 8 | Taps now, stick later | Tint taps in A; a **Secchi cm box from day one** (data only); the printable stick + log fit in C; camera index in D |
| 9 | User-selectable; personally: daily straight to the tank / auto doser eventually, spares in the fridge | `harvestTo: bottle | source` per jar (bottle default); `tank` as a per-split destination; **§5.11 sizing**: a 3.5 L vessel out-produces a 52 L tank 5–10× — seed at 1:4 (1.25 L), scale up when the drip or the cone drinks it |
| 10 | Default | B tracked as a jar, the split seeds it, refresh every 3–4 cycles; `CULTURE_JARS_MAX` 4 → 6 |
| 11 | Same rack | Third tile, the rig gains a lit carboy, the tab's headline changes |
| 12 | Default | Hygiene said once (walkthrough + settings hint); f/2 residue = a nutrient-budget note, never a figure |

The original questions, for the record:

1. **The crash.** What did the cone look like when it went; days since the last clean-cone
   restart; the room; what and how often it was fed; did the risk line say anything first?
2. **Who is the phyto for?** Rank the cone's tint, the drip, hand doses, the pod tub, backup food.
3. **What is arriving and what is on the bench?** Starter alone or the kit; f/2, lamp, air pump
   with its own line, a spare vessel for B?
4. **Where does it live?** The rack or a windowsill?
5. **Salinity.** 27 to match the cone, or 35 to match the tank and the drip?
6. **The lamp: owned or observed?**
7. **Split policy.** Batch (50–70 % / 7–10 d) or semi-continuous (20–30 % daily)?
8. **Density readout.** Eye taps now; camera / colour sensor / pH probe / Secchi stick later?
9. **Bottle or vessel.** Fridge bottle on the shelf, or feed straight from the vessel?
10. **Backup doctrine.** B tracked as a jar? Raise the cap?
11. **Where on the tab?** Same rack or a Phyto section?
12. **Hygiene and the medium.** Say once or nag; f/2 residue note?

## 9. Staged build (answers landed — A is unblocked)

- **Stage A — the vessel, the bottle, the tank:** the `nanno` preset and kind-aware engine
  (§5.1–5.3: statuses, the darkening tints and signs, `density_advice` incl. peak-held, modes),
  Seed with the arrival check and the 1:4 / 3.5 L recipes, Looked (+ Secchi cm), Split with
  destinations bottle / tank / drip / B, scale-ups, f/2 by the fresh litres and the mix debit,
  Fresh vessel, Sign, Crashed (reseed from B or a young bottle), the **home phyto bottle** on the
  shelf with its hand-dose plan and the *Shaken* tap, Loaded debits the bottle, the cone feed cap
  lift, tile + rig + hub + Pulse lines, reminders + the push, the day-the-starter-lands
  walkthrough (hygiene said once), the sizing line (§4.1/§5.11), the nutrient-budget note, tests.
- **Stage B — light, heat, backup, learning (BUILT 0.7.208, §11):** the three light modes on the plug and the sun
  entity (the sunset rule, delivered hours, the short-day nudge, the lamp-off watch), the Nanno
  heat guard and sunlit-vessel copy + the optional vessel sensor, B and the refresh chore, learned
  days-to-dark / yield / recovery-by-depth, the `daily` mode offer, the risk line, the shelf's split
  nudge. *Reece will be seeding under sun within days — A and B ship back to back, before the
  first split.*
- **Stage C — the rotifer coupling and the stick (BUILT 0.7.209, §12):** refill-with-phyto on the rotifer harvest and
  restart (three-way jug when salinities differ, the still-green refusal), the cone's default dose
  from a home bottle, the printable Secchi stick + log fit off the accrued cm readings, Reef Report
  yield.
- **Stage D — the index:** the camera/phone green index (shared with drip Stage D), optional pH /
  colour-sensor entities, "split now" advice off the curve, the bottle's estimated density feeding
  the drip's line.
- **Hardware track (shelved):** the reactor as the drip's reservoir source (pump pauses on a
  crashed culture — to lock then), the phyto node with the OD shroud, the continuous reactor.

## 10. As built — Stage A (0.7.207, 2026-09-21)

The vessel, the bottle, the tank. Everything below is code; nothing here has run on Reece's HA yet.

- **Preset + scales** (`cultures.py`): `nanno`, kind `phyto`, the §5.1 numbers; `PHYTO_TINTS`
  pale → green → dark → off and `PHYTO_SIGNS`; every reader asks `tints_for` / `signs_for`; the
  normaliser accepts the union. `CADENCE_FIELDS` grew `splitPct / splitIntervalDays /
  restartCycles / lightHours` (only a phyto preset carries them) and `cadence_for` maps split* onto
  harvest* after the clamps, so the chore clocks stay one machine. `CULTURE_JARS_MAX` 4 → 6.
- **The state machine** (`_phyto_state`): *establishing* = the first cycle, *producing* from the
  first split **or the moment a look says dark** (ready on a sign). Clocks: `look` (daily),
  `harvest` = the split (interval since the last split; a dark tap brings it forward, reason
  `dark`), `restart` = the fresh vessel (`cyclesSinceFresh ≥ restartCycles`, reason `cycles`; a
  sign brings it forward). `harvestBlocked` = a sign with no green/dark look after it, or an off
  tint. Extras: `cycle {day, ofDays, percent}`, `darkDays` / `peakHeld` (≥ 3 days dark without a
  split), `workingL`, `mode`. No feed, no water change.
- **Advice + maths**: `density_advice` (wait / check / split_now incl. peak-held / hold),
  `split_guide` (out = splitPct × the WORKING volume; fresh = like-for-like or a scale-up; f/2 by
  the fresh litres only; refused past the working volume or the container, warned above 70 %),
  `seed_guide` (1:4 default, capped to the container; the kit's 3.5 L as the alternative),
  `darkening_samples` → `learned.daysToDark` + a suggested `splitIntervalDays` (Apply is Stage B),
  `sizing_line` (§4.1/§5.11), `home_dose_ml` (52 L → 35 ml, an estimate), `starter_state` (four
  weeks), `rig_state` gains `phyto[]` + `phytoJug` and the stages `greening / split / scale_up /
  off_colour / fresh_vessel`. The risk line has its Stage A phyto branch (heat, off-colour, a
  blocking sign, peak-held, not dark long after the split).
- **Ceremonies** (`__init__.py`): `cultures_seed` accepts `arrival_tint` (**`off` refuses before
  anything is written**), `starter_ml`, `working_l`, `starter_opened_at`, `from_bottle` (a
  bottle under a week old; its ml come off the bottle `to: jar`); the seed stamps `workingL`,
  debits the f/2 by the NEW litres and the station by the NEW water only, and **creates the home
  bottle**. `cultures_log` takes the phyto scale + `secchi_cm` and refuses fed / harvested /
  skip / egg / enrich on a vessel. `cultures_split` on a phyto jar is THE split
  (`_cultures_phyto_split_apply`): `ml`, `to: [{to, ml}]` over bottle / tank / drip / vessel (a
  share not named is waste), `fresh_ml` (a scale-up moves `workingL`), `nutrient`, `tint`,
  `secchi_cm`; every check runs before the first write; the colour goes back to pale; the cycle
  counter steps. New `cultures_fresh_vessel` = the same ceremony with the restart semantics
  (counter reset, sign answered; a blocked vessel's crop goes to waste, never the bottle).
  `cultures_restart` on a phyto jar delegates to it. The B share uses `_cultures_split_apply`
  (`check=False`, `starter_ml`), a litre vessel, its own home bottle. Undo of a look re-reads
  `lastLookedAt` and drops the look completion.
- **The home bottle** (`home_phyto_<jid>`, `nps.HOME_PHYTO_PREFIX`): a real product — phyto,
  refrigerated, stirDaily, 21-day opened clock, cellsPerMl 0, `doseMl` from `home_dose_ml`,
  `doseEveryDays 1` — with its `nps_dose_<pid>` reminder made server-side in the panel's shape.
  Made at the seed and by `_cultures_ensure_home_bottles` on every panel save; a stale client
  that never saw it cannot delete it while the vessel stands (`_nps_preserve_runtime`); a removed
  vessel takes it. Filled by the split with the rotifer bottle's rules (oldest load owns the
  clock, overflow logged, a `refill` row the runway never counts, `lastShakenAt` stamped).
  `consumable_mark_shaken` + `nps.shake_state` (48 h) on any refrigerated stirDaily bottle;
  `dosing_mark_refreshed {debit: true}` tops the drip's jar from its linked bottle as a
  `transfer`. `_harvest_went_to_tank` reads `dests`; the feed log / timeline name a phyto row
  "Phyto from <vessel>"; a bottle-first vessel plans nothing on the tank strip.
- **Payload**: per jar `tints`, `signs`, `mode`, `workingL`, `densityAdvice` (= `feedAdvice` for a
  vessel), `splitGuide`, `seedGuides {starter, kit}`, `homeBottle` (as the shelf sees it),
  `nutrient` (+ `splitsLeft`), `sizing`, `starter`, `drips`, `reseedFromBottle`, `hygiene`,
  `nutrientNote`; `hasBottle` is the ROTIFER bottle (false for a vessel), `hasHomeBottle` true;
  top-level `phytoTints` / `phytoSigns`. Push: "Nanno A — split? · Split to the bottle · Later"
  (`OPENREEF_CULTURE_SPLIT`, `OPENREEF_CULTURE_FRESH`); a look alone is not a push.
- **Panel**: `_culturesPhytoTile` (the lit vessel, Colour + Secchi, Out / → bottle / → tank /
  → drip / → B / After (L) / f/2 tick, the notes, Looked / Split / Fresh vessel / Crashed /
  Share card; the seed card with the arrival check, both recipes and the fridge reseed),
  `_culturesPhytoSvg`, the rig's carboy above its fridge bottle, the journal's phyto words
  (shares, fresh + f/2, Secchi), the walkthrough's "Phyto into the vessel" step (hygiene said
  once) gated like the animal steps, the settings row (`_culturesPhytoSettingsRow`: vessel /
  reactor, container, salinity, starter, split goes to bottle | source, fridge bottle, f/2 link
  + ml/L, mode, the four cadences), `Add a phyto vessel`, reminders look / harvest(split) /
  restart(fresh vessel) with no feed, the hub line, the shelf's **Shaken** tap and chip, the
  drip's Loaded sending `debit` for a home bottle, the demo rack's vessel.
- **Tests**: `test_cultures.py` +16 (84), `test_cultures_audit.py` +2 (28),
  `test_panel_cultures.mjs` +6 (46). Every suite that touches cultures, the shelf, dosing, saves
  and reports is green.
- **Not in A (built in B, §11):** the light block and the sun entity, the Nanno heat guard
  copy on the projection, B's refresh chore, the `daily` offer and Apply on days-to-dark, the
  shelf's split nudge, the full risk line.

## 11. As built — Stage B (0.7.208, 2026-09-21)

Light, heat, backup, learning. Code only; nothing here has run on Reece's HA yet — the first
sunset with the plug bound is the first live test.

- **Light** (`cultures.py` `sun_day` / `light_window` / `light_state`, `__init__.py`
  `_async_cultures_light_tick`): per jar `light {mode: sun | lamp | sun+lamp, switchEntity,
  onAt, latestOff, tempEntity}`; the target hours are the cadence's `lightHours` (one field, not
  two). `sun_day` reads HA's `sun.sun` from its two FUTURE stamps — day when the setting comes
  first — so the day length (astronomical, an upper bound) and the sunset the window hangs off
  (the LAST one at night, the coming one by day) need no calendar logic. `light_window` is the
  one rule the tick and the card both ask: `lamp` = `onAt` + the target; `sun+lamp` = from
  sunset until daylight + lamp = the target, never past `latestOff` (the first occurrence of
  that clock time after the sunset — `00:00` = the coming midnight; a cap before the sunset means
  tomorrow's, i.e. no cap); midsummer's sun alone reaching the target leaves the lamp off
  (`sun_enough`); no sun to read in `sun+lamp` falls back to the lamp rule and says so. The tick
  (`CULTURES_TICK_SECONDS` 60, armed while a phyto vessel stands) switches ONLY the lamp: on when
  the window opens (own stamp `lightOnAt`), off when it closes (minutes banked in
  `lightMinutesToday` under `lightDay`), a failed call retried next tick with no stamp, an
  unbound plug clears the stamps; a plug reading off or unavailable after we lit it earns one
  warning per window (`lightWatchAt`), never a fight with the keeper; at the local day roll
  yesterday's lamp minutes + daylight go into the journal as a `light` row (`lampH`,
  `daylightH`, `lightH`), the basis of the learned light line. Readout: *"daylight 12.4 h
  (astronomical — the window gives less) · lamp 3.6 h from sunset 19:09 → 22:45 · 1.5 h lamp so
  far"*; `sun` mode under 12 h → the nudge *"the days are under 12 h — put the LED on the plug"*
  (a `watch`); under the target → a `watch`; the lamp off in its window → a `watch`; under 12 h
  delivered by window end → an `act` (*"the culture lost a day of light — expect the split to
  slip"*, one activity line a day, `lightLostDay`). Air is never switched; the tile's title says
  why. The rig's lamp glyph and the tile's follow `light.lit` (grey when dark, red when it should
  be on and is not).
- **Heat**: the optional vessel-side sensor (`light.tempEntity`) overrides the rack reading for
  that jar (`temp.source: vessel | rack`); the tile's heat line names the source (*"the vessel's
  own sensor"* vs *"this is the rack's air, not the culture — a vessel sensor in Culture settings
  reads the water"*); `heat_guard` and its push speak the alga's copy for `kind == "phyto"`
  (*shade it, move it off the sunlit shelf, a cooler room — the alga declines abruptly near
  30 °C*), the animals keep theirs; `_entity_temp_c` is the one unit-converting reader.
- **Backup** (`state.backupOf`, server-written by the split's `vessel` share): the engine's
  `refresh` clock on a backup — due `max(7, restartCycles × splitIntervalDays)` days after its
  seed (32 by default), reason `backup`; the calendar never asks B for a split (a dark look
  still does). The `vessel` share now targets an idle same-species jar, else the RUNNING backup
  of this vessel (a refresh: a `restart` row on B with its old litre to waste, then the seed
  again 1:4 from today's crop — B's clocks restart, its generation is A's + 1, `backupOf`
  kept), else a new jar. New WS `cultures_refresh_backup {jar_id (B), ml?, nutrient?}` =
  a small split of A with the whole share into B (every refusal the split's own:
  `not_a_backup`, `parent_idle`, `jar_idle`, `not_ready_to_split`…); the phone's
  `OPENREEF_CULTURE_REFRESH` and the daily push *"Nanno B — refresh?"*; the maintenance chore
  `culture_<jid>_refresh` (the panel seeds it only for a jar with `backupOf`, cadence from the
  same formula; `_cultures_task_clock` reads the engine's clock); the tile's *"backup of Nanno A ·
  refresh in ~N d (every ~32 d) · 250 ml from Nanno A + 750 ml fresh + 1.1 ml f/2"* line and the
  **Refresh from Nanno A** tap; A's split form labels the share *"→ Nanno B … to refresh Nanno B"*.
- **Learning** (`learned_cadences`, phyto): `suggest.splitIntervalDays` now has its **Apply**
  (`cultures_apply_learned` re-times the split reminder with the panel's +3 d margin);
  `dailyOffer {available, pct}` after two learned cycles — `daily_draw_pct` = the daily fraction
  matching the batch cycle's growth, held to 20–30 % — and **Switch to daily**
  (`field: "mode"`: `mode = daily`, `splitIntervalDays 1`, `splitPct = pct`, the reminder daily;
  the offer disappears in daily mode); `yieldLWeek`; `depth` = recovery by split depth
  (`darkening_by_depth`: ≤ 50 % / 50–65 % / > 65 % buckets, two runs at each of two depths
  before it speaks, *"this does not establish the cause"*); `light {weekH, days, line}` = the
  mean of the last seven `light` rows, the line only under 14 h AND beside a cycle slower than
  the record (*"the light is the first thing to check; nothing here proves it"*).
- **The risk line** (`risk_line(…, light=)`): the Stage A items plus the light's watch / act
  (the nudge or the lamp-off words; the lost day as an `act`), no f/2 logged at the last split,
  `restartCycles` splits since a fresh vessel (*sterilise the spare*), the backup's age when its
  refresh is due, the starter bottle past four weeks while the vessel is still establishing.
- **The shelf's split nudge** (`nps.home_bottle_nudge`, attached by `_cultures_shelf_nudges` on
  the NPS summary as `splitNudge` on a `home_phyto_*` card): a low or empty home bottle says what
  the vessel is doing about it — *"empty — Nanno A reads dark: split into this bottle"*, *"runs
  out in ~1.7 d — Nanno A's next split is due in ~4 d (your record says ~6 d to dark) — a small
  early split tides it over"*, off-colour / not running variants; silent when the bottle is fine.
- **Payload**: per jar `light`, `backupOf`, `refresh {isBackup, fromId, fromName, available, due,
  hoursUntil, everyDays, starterMl, freshMl, nutrientMl, workingL, backupId, backupName}`,
  `dailyOffer`, `temp.source`; `due` gains `refresh`; top-level `sun`. Normaliser: the `light`
  block, the state stamps (`backupOf`, `lightOnAt`, `lightOffAt`, `lightMinutesToday`,
  `lightDay`, `lightWatchAt`, `lightLostDay` — all under the existing whole-`state` preserve
  guard), the `light` history row fields.
- **Panel**: the Light group in the vessel's settings row (mode, plug, on-at, latest-off, vessel
  sensor; the hints no longer promise a later stage), the tile's light line / Apply chips /
  learned lines / backup line / Refresh tap / share label / heat-source words, the reminders'
  `culture_<jid>_refresh`, the due-state regexes, the chore word *refresh the backup*, the
  shelf card's nudge line, the demo vessel's light.
- **Tests**: `test_cultures.py` +12 (96), `test_cultures_audit.py` +1 (29),
  `test_panel_cultures.mjs` +3 (49); the full regression green.
- **Not in B (built in C, §12):** refill-with-phyto on the rotifer harvest and restart, the
  cone's default dose from a home bottle, the printable Secchi stick, Reef Report yield; the
  camera/phone green index is Stage D.

## 12. As built — Stage C (0.7.209, 2026-09-21)

The rotifer coupling and the stick. Code only; nothing here has run on Reece's HA yet.

- **Refill with phyto** (`cultures_log` / `cultures_restart` take `phyto_ml`, `phyto_from` =
  `bottle:<pid>` | `vessel:<jid>`; blank ml = one tint of the jar): the rotifer / pod harvest's
  own refill carries the phyto and the jar is FED in the same tap — `lastFedAt`, tint green, the
  feed reminder done, the harvest row `fed` with `phytoMl` / `phytoFrom`. A home bottle is
  debited `to: jar`; a vessel is DRAWN through the split ceremony's cone share, written LAST
  (`cone_stamps=False` — the cone's own ceremony already fed it). `_cultures_phyto_source` runs
  every refusal before a write: **`still_green`** (Reefphyto's first crash cause is one big dose —
  plain water this time), `no_phyto_source`, `phyto_short`, `vessel_not_ready` (green or dark, no
  sign), `invalid_volume` (more than the refill / the vessel), `salinity_unavailable`. The
  clean-cone **restart** takes it too (FAO's batch method; the default still one tint; the still-
  green rule waived — the whole water goes) and the linked feed product is NOT also debited.
- **The three-way jug** (`refill_guide(…, phyto_ml, phyto_ppt)`, `harvest_guide` through it): the
  phyto's own salt counted — cone 27 ppt, 675 ml, 350 ml of 35 ppt phyto → **171 ml mix + 154 ml
  RODI** (§4.2's numbers); too much salty phyto is refused with the most the jar could take; a
  brackish phyto into a full-strength jar is "not reachable"; whole millilitres throughout; the
  no-phyto path byte-identical. The audit grid checks volume AND salt over cones, refills and
  shares.
- **The vessel feeds the cone** (`SPLIT_DESTINATIONS` + `cone`; a share `{to: "cone", ml, jarId}`;
  a zero share = one tint; a green cone refuses; `_cultures_cone_feed_apply` writes the cone's
  feed row + stamps + reminder). **The draw rule** (`PHYTO_DRAW_MAX_PCT` 30): a split that takes
  under 30 % of the working volume in batch mode is a DRAW — the ledger moves (`workingL`, the
  row `draw: True`, its dests), the colour, the split clock, the cycle counter and the harvest
  completion do not; daily mode always re-anchors (the draw IS the day's split). `cone_dose_ml`
  = one tint of an animal jar (2.5 L → 170 ml; 4 L tub → 270; rounded to 10 ml; an estimate).
- **The cone's default dose** (`_cultures_default_cone_feed`, on every save and at a phyto seed):
  an animal jar with no feed product is linked to the rack's first `home_phyto_*` bottle at one
  tint of its volume (an activity line says so); a jar already on a home bottle at the untouched
  5 ml default gets one tint; a keeper's own number is never moved; nothing without a home bottle.
- **The Secchi stick** (`secchi_samples`, `secchi_fit`, `learned.secchi`): the accrued cm
  readings beside their tints → per-tint median **bands** (two readings at a tint before it
  draws), the stick's zones (`darkMaxCm` / `greenMaxCm` = the midpoints), and the **log fit** —
  ln(cm) against days since the split, four points over two days, a downward slope only
  (`halvingDays`), with a dark band the days a reading is from dark (`daysToDark`, the density
  advice appends *"your stick says ~N d"*). Depth on the stick, never cells. The panel's
  **Print Secchi stick** (`_culturesSecchiStickSvg`: true size — mm units, 40 × 270 mm, 5 mm
  ticks over 20 cm, a quartered disc, the keeper's bands as zones once they exist;
  `_culturesPrintSecchiStick` via `window.open` + `print`, the report's own pattern).
- **Reef Report** (`cultures_section`): each jar's `kind`; a vessel's `yieldL` + `dests` (bottle /
  tank / drip / cone / waste); an animal's `phytoFedMl`; `phytoYieldL`; the text line *"Nanno A:
  1 looks, 3 splits — 1.6 L (1.1 L bottle, 0.17 L cone, 0.21 L tank, 0.08 L waste)"* and
  *"Rotifers A: … 340 ml of home phyto"*; the viewer's line to match.
- **Payload**: an animal jar carries `phytoSources` (every home bottle with something in it,
  every running vessel with its tint and readiness), `coneDoseMl`, `phytoRefill` (the three-way
  guide at one tint from the first ready source, `stillGreen`), `phytoRestart`; a vessel carries
  `cones` (the animal jars it can feed, their dose and colour) and `secchi`. Normaliser: dests
  carry `jarId`; rows carry `phytoMl`, `phytoFrom`, `draw`.
- **Panel**: the animal tile's Phyto row (source select — a pale vessel greyed — and an ml box
  with one tint as its placeholder) and the three-way line (the still-green word beside it); the
  harvest and restart senders carry `phyto_from` / `phyto_ml`; the vessel tile's → cone share
  (a picker when two jars stand) and the split sender's `jarId`; the Secchi line (or how to
  start) and the Print Secchi stick button; the report viewer's split line; the feed dose field
  to 1000 ml with the one-tint hint; the demo vessel's cones and stick.
- **Tests**: `test_cultures.py` +6 (102), `test_cultures_audit.py` +1 (30),
  `test_panel_cultures.mjs` +3 (52); the full regression green.
- **Not built (parked with the arc):** Stage D — the camera/phone green index shared with drip
  Stage D, the optional pH / colour-sensor entities, "split now" advice off the curve, the
  bottle's estimated density feeding the drip's line; the hardware track (§5.7).
