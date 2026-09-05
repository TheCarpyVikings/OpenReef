# Live cultures — rotifers + copepods on the hatchery rig · brainstorm (2026-09-03)

**Status: v1 BUILT 0.7.117 (2026-09-03) — §7 shipped end to end (cultures.py engine + normaliser + 8 WS actions + save guard + Cultures tab + settings + reminders + Pulse lines; 30 backend + 7 panel tests). Parts list in §4 is final for purchase.**
Extends the brine Hatchery (docs/nps-system-brainstorm.md §9–§12, shipped through 0.7.116)
into a **Live food** tab: brine (batch, hours), rotifers (chemostat, days), copepods (slow, weeks).
Reece has cultured copepods before; rotifers are new. Parts get bought when §6 is answered.

---

## 1. Rotifers — the biology that sets the clocks

Species the UK sells: **Brachionus plicatilis, "L-type"** (Reefphyto 4/10/20 L kits, AdzAquatics
Roti-Lab kit). 130–340 µm. Optimum **18–25 °C** — a UK room, no heater (the brine cone needs 28 °C;
rotifers do NOT — that's the first simplification). S-type (*B. rotundiformis*, 100–210 µm) wants
28–35 °C and only matters for small-mouth fish larvae.

| Variable | Number | Design consequence |
|---|---|---|
| Salinity | optimum **15–20 ppt** for max productivity; tolerate 4–45 ppt; culturable at 35 ppt with lower output | Q2: brackish (max yield, needs a diluted mix) vs 35 ppt (same water as LIVE vessel + tank, mixing station already makes it) |
| Temperature | 23–25 °C standard; L-type slows above ~26 °C | no heater; the hatchery's 25.4 °C room is ideal |
| Density | healthy hobby culture **200–500 /ml**; commercial 1000s/ml | a 2–3 L culture at 300/ml harvesting 25 % ≈ **200–250 k rotifers/day** — far more than a 52 L reef needs |
| Feed | live *Nannochloropsis* (keep water **lightly green**; clear = hungry) **or** RGcomplete concentrate (~6 ml/day in 2 feeds for a small culture; 11 ml/day per million harvested; has ClorAm-X built in) | "tint" is the daily health tap: green / clearing / clear |
| Harvest | **20–30 % daily** through a **53 µm** sieve; the removed water is the water change | harvest == water change == ammonia control — one ceremony |
| Killer | **ammonia** (rotifers gas themselves); pH 7.5–7.9 keeps free ammonia down; ciliate/bacteria bloom after ~3–4 weeks | a periodic **sieve-and-restart** into a clean jar (ciliates pass 53 µm, rotifers don't) |
| Aeration | gentle, ~1 bubble/s, open airline, **no airstone** (fine foam strips rotifers) | existing air pump + valve |
| Light | not required | none |
| Health index | **egg ratio ≥ 30 % gravid = healthy; 15–20 % = sluggish; < 15 % (≈ 0.13) = collapse near** | weekly spot check (phone macro / later camera) |
| Storage | harvested rotifers keep at **4 °C** for a limited number of days (100 k in 1 L open container) | the feeding-bottle idiom transfers as-is |
| Enrichment | **6 h** soaks are standard (Algamac 3050, DHA Selco, RotiGreen); rotifers are "what they ate 2–6 h ago" | shorter soak than brine (Selcon flask reused, different hours preset) |
| Dosing shock | 20 ppt → 35 ppt: they stop swimming briefly, not killed; 48 h at a new salinity restores egg production | backflush with 35 ppt water is acceptable; **never dose culture water** (ammonia) — same doctrine as hatch water |

**Doctrine that transfers unchanged**: never dose culture water; two vessels so a crash never zeroes you;
a fridge bottle with its own clock; consumables debit the shelf.

### 1.1 Prior art — automation

- **Reef2Reef 24 h reactor**: a 2-channel doser puts 6 ml/h of 1.015 salt mix into a phyto reactor and
  pulls 5 ml/h of phyto into a rotifer reactor; the rotifer reactor overflows to the sump. Only chore:
  trim salinity every 14 days. **Zero-touch but low-yield** (≈ 120 ml/day ≈ 5 % turnover, well under the
  20–30 % ammonia-control rate — it survives on dilution + phyto uptake, not on harvest).
- **Patent 8,973,531** (automated continuous zooplankton culture): coned reactor, retention screen,
  biofilter, pH + emergency O₂ dosing. Industrial; nothing hobby-scale schedules a rotifer culture.
- **Rotiferometer (bioRxiv 2025)**: YOLOv8 on a 1 ml Sedgewick-Rafter slide, 94.7 % mAP gravid vs
  non-gravid, < 3 min per count, tracked a 45-day culture through growth/decline/recovery. Proof that
  egg-ratio-from-image works — but it is a microscope stage, not a webcam. v3 at best.
- **Nobody at hobby level** does culture scheduling (feed/harvest/restart cadence, egg-ratio trend,
  crash → reseed guidance, harvest ledger). Same empty niche as the hatchery scheduler claim.

---

## 2. Copepods — slow clocks, hardy animals

| | *Tigriopus californicus* (Reefphyto UK) | *Tisbe biminiensis* | *Apocyclops panamensis* |
|---|---|---|---|
| Habit | benthic/edge, 1–2 mm adults, cold-tolerant | benthic, adults 500–750 µm, nauplii 50–75 µm | planktonic cyclopoid, warm |
| Temp | 20–25 °C (tolerates 16–29) | 22–27 °C | 24–28 °C |
| Salinity | full reef **1.025** | reef | reef |
| Feed | phyto **every 2–3 days**, lightly tinted | same, needs surface area | same |
| Generation | **~1 month** (nauplii stages 1–2 d each) | fast (r ≈ 0.33/day); weekly offspring harvest doesn't dent growth | fast |
| First harvest | wait **5–7 days**, then **~20 %/day once > 1/ml** | weekly | weekly |
| Water change | 25–50 % every **2–4 weeks** | same | same |
| Reef use | refugium seeding, fish grazing; nauplii for SPS | best "reef underground" seeder; nauplii ideal coral food | larval fish + coral |

Copepods are the opposite regime to rotifers: **low-touch, forgiving, slow**. Their card is a
week-scale reminder set, not a daily ceremony. Harvest nauplii through 53 µm; adults stay on 100–150 µm.

---

## 3. Method — what OpenReef can actually make simpler

The biology is fixed; the leverage is in (a) removing variables, (b) making one action do three jobs,
(c) refusing the week-4 crash by design, (d) reusing the rig that already exists.

### 3.1 "The culture joins the rig" (proposed)

- **Two rotifer jars** (A/B), 4 L each, run at ~2.5 L, **room temperature, no heater, no light**,
  open airline at ~1 bubble/s off the existing air pump + a valve each.
- **Harvest = the brine transfer ceremony with a different disc.** Each jar gets a bottom valve into the
  same clear union; the union takes a **swappable mesh disc: 120 µm for brine, 53 µm for rotifers**
  (copepod nauplii also 53 µm; adults ~150 µm). Open valve → 25 % of the jar drains through the disc to
  waste (rotifers retained, ammonia water gone) → backflush the disc into **LIVE** with 35 ppt from the
  mixing station. One motion: harvest + water change + salinity step + load.
- **Refill = a measured jug**, not a guess: the jar is marked at 2.5 L; 25 % is a 600 ml jug. At 35 ppt
  the mixing station makes it; at 20 ppt OpenReef prints the cut ("430 ml mix + 170 ml RODI").
- **Feed = tint.** Two taps a day: look at the jar, tap green / clearing / clear. Clear → feed the
  preset dose now; green at both taps → skip. The dose is a fixed ml of fridge phyto or RGcomplete,
  debited from the consumables shelf.
- **Restart on a clock, not on a crash.** Every 14 days (preset, learnable) the jar is sieved whole
  through 53 µm into a clean jar with fresh water; the dirty jar is washed and becomes the spare.
  This is the aquaculture "batch restart" hobbyists skip and then crash at week 3–4.
- **A/B stagger**: jar B restarts 7 days after jar A, so a crash in one is reseeded from the other with
  no gap. Same structural line as "you need N hatcheries", now "your backup is 7 days out of phase".
- **The LIVE vessel is shared.** Brine + rotifers + copepod nauplii all ride the same NPS live-food
  channel; the peristaltic head passes all of them (already the AWC live-food source assumption). The
  freshness clock keeps the **shortest** shelf life in the mix (brine's) — fail-closed, like top-ups.

### 3.2 Continuous mode (optional, later)

The Reef2Reef reactor is a good **v2 hardware track**: the NPS doser already exists, so a phyto/brackish
dose into a reactor whose overflow line lands in the sump is a wiring job, and the **feed-exchange
matched drain already banks the overflow volume**. Not v1 — ammonia at 5 % turnover needs RGcomplete's
ClorAm-X or a phyto reactor, and the yield is a trickle. Log it, don't build it yet.

### 3.3 The software model (sketch — a generic Culture engine, species presets)

```
nps.cultures: {
  c1: { species: "rotifer_L", name: "Rotifers A", volumeL: 2.5, salinityPpt: 35,
        feed: { productId, doseMl, timesPerDay: 2 },
        cadence: { harvestDays: 1, harvestPct: 25, restartDays: 14, waterChangePct: 0 },
        state: { startedAt, lastRestartAt, lastHarvestAt, lastFedAt, lastTint, eggRatioPct,
                 crashedAt, pairedWith: "c2" },
        history: [ {harvestedAt, ml, tint, eggRatioPct} ] },
  c2: { species: "rotifer_L", ... offsetDays: 7 },
  c3: { species: "tigriopus", cadence: { feedDays: 2, harvestDays: 7, waterChangeDays: 21 } },
}
```

Species presets carry the numbers from §1/§2 (temp band, salinity band, cadences, sieve µm, shelf life,
enrichment hours). Clocks: culture age, days since restart, next feed, next harvest, next restart.
Ledger: ml harvested into LIVE (credits the container like "Hatched & loaded"), feed ml debited.
Health: tint trend, egg-ratio spot checks, "crash — reseed from B" flow. All advisory. Reminders ride the
maintenance engine (daily tick is fine — no 20-minute windows here). Card copy stays calm-state cheeky.

---

## 4. Parts shortlist (UK) — FINAL for purchase (2026-09-03)

| Item | Qty | Note |
|---|---|---|
| Reefphyto **Rotifer Culture Kit 4 L** (L-type starter + feed + vessel; no air pump option) | 1 | jar A |
| Second matching **4 L jar** (or a food-grade 4–5 L clear tub) | 1 | jar B — buy now so the split has somewhere to go |
| **53 µm** hand sieve / mesh cup (Brine Shrimp Direct-style "rotifer sieve" or a cut of 53 µm nylon mesh in a ring) | 1 | rotifers + copepod nauplii; keep the 120 µm for brine |
| Reefphyto **live phytoplankton** (fridge bottle, Nanno-led blend) | 1–2 | feed for both cultures; tint-dosed |
| Reefphyto **Copepod Culture Pack — Lite** (Tigriopus, 4 L, feed, guide) | 1 | you have the air pump |
| Airline + **3 inline valves** + rigid airline tips | — | one gentle line per jar, no airstones |
| **600 ml measuring jug** | 1 | the 25 % harvest / refill |
| Small **lidded fridge bottle** ~500 ml–1 L | 1 | the rotifer bottle (separate from brine) |
| Jar **temperature strip / cheap thermometer** ×2 (or an HA temp sensor by the jars later) | 2 | the heatwave guard |
| Optional: Seachem Ammonia Alert badge | 2 | passive; only if you want a crash sensor in v1 |
| Nothing else | | no heater, no light; salt + RODI come from the mixing station |

## 5. Sources

- Reed Mariculture — [Rotifer Culturing Support](https://reedmariculture.com/pages/rotifer-culturing-support), [Reliable Rotifers](https://reedmariculture.com/blogs/finfish-larviculture/reliable-rotifers), [Debunking the Myth About Rotifers](https://reedmariculture.com/blogs/finfish-larviculture/debunking-the-myth-about-rotifers), [RotiGrow Plus](https://reed-mariculture.myshopify.com/products/rotigrow-plus)
- Reef Nutrition — [Culturing Rotifers](https://reefnutrition.com/pages/culturing-rotifers), [RGcomplete](https://reefnutrition.com/products/rgcomplete), [Culturing Tigger-Pods](https://reefnutrition.com/pages/culturing-tiggerpods)
- Reefphyto UK — [Rotifers for Fry Food](https://reefphyto.co.uk/a/blog/rotifers-for-fry-food-uk), [Rotifer Culture Kit](https://reefphyto.co.uk/products/rotifer-culture-kit), [Copepod Culture Pack](https://reefphyto.co.uk/products/copepod-culture-pack), [How to Culture Copepods](https://reefphyto.co.uk/a/blog/how-to-successfully-culture-copepods)
- [AdzAquatics Roti-Lab kit](https://www.adzaquatics.co.uk/product-page/rotifer-culture-kit-roti-lab)
- Aquatic Live Food — [Rotifer Culturing](https://www.aquaticlivefood.com.au/rotifer-culturing/), [Copepod Culturing](https://www.aquaticlivefood.com.au/copepod-culturing/)
- Aquaculture Kings — [Why cultures crash](https://aquaculturekings.com.au/blogs/articles/help-my-culture-keeps-crashing), [Culture copepods at home](https://aquaculturekings.com.au/blogs/articles/how-to-culture-copepods)
- PodDrop — [Tigriopus californicus culture](https://www.getpoddrop.com/blogs/blog/tigriopus-californicus-culture); Pod Your Reef — [Tisbe biminiensis](https://www.podyourreef.com/blogs/care/tisbe-biminiensis-jewel-of-the-reef-underground)
- Virginia Tech — [Rotifer Production for Intensive Finfish Larviculture](https://www.pubs.ext.vt.edu/600/600-105/600-105.html) (egg-ratio thresholds); [Swimming speed and egg ratio as predictors](https://link.springer.com/article/10.1007/BF00025976)
- [Effects of Salinity, Temperature, and Diet on B. plicatilis (PMC 2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12292424/); [FAO rotifer mass culture](https://www.fao.org/fishery/docs/CDrom/aquaculture/a0844t/docrep/009/AE993E/AE993E22.htm); [S-type vs L-type](https://www.sciencedirect.com/science/article/abs/pii/S0044848600003690)
- [Survival of rotifers at 4 °C](https://www.sciencedirect.com/science/article/abs/pii/004484869090175M); [Rotifers and salinity acclimation (R2R)](https://www.reef2reef.com/threads/rotifers-and-salinity-acclimation.755382/)
- Enrichment: [Algamac / Selco DHA comparison](https://www.researchgate.net/publication/364114075_The_effect_on_fatty_acid_contents_of_Rotifer_Brachionus_plicatilis_of_Algamac_3050_and_Olio_o_-3_supplemented_with_or_without_L-Carnitine), [striped trumpeter 6 h protocol](https://www.sciencedirect.com/science/article/abs/pii/S0044848605004059)
- Automation: [R2R continuous phyto/rotifer reactor](https://www.reef2reef.com/threads/continuous-phytoplankton-rotifers-reactor-24h-food-supply.526123/), [Automating phyto + rotifers](https://www.reef2reef.com/threads/automating-phyto-and-rotifer-setup.715788/), [US 8,973,531](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8973531), [Rotiferometer (bioRxiv 2025)](https://www.biorxiv.org/content/10.1101/2025.05.12.653399v1)
- Tisbe mass culture: [Souza-Santos et al.](https://www.sciencedirect.com/science/article/abs/pii/S0044848611007241)

---

## 6. The grill — **ANSWERED 2026-09-03, decisions LOCKED**

> 1. **Corals + NPS only** (no larvae → L-type stays, enrichment optional, no continuous supply).
> 2. **35 ppt for v1** (one water; mixing station makes the refill; brackish = later option).
> 3. **Fridge phyto bottles** for now (own phyto culture = later card).
> 4. **Standalone jars for v1** (hand sieve, not the union; the disc idea = later hardware).
> 5. **Not A/B from day one — build the split in**: start with ONE jar; when it's dense enough,
>    a "Split into B" action seeds the second jar and stamps the stagger.
> 6. **Separate**: rotifer harvest goes to its OWN fridge bottle with its own days-long clock —
>    never into the brine LIVE vessel.
> 7. **Tigriopus from Reefphyto**. Previous culture died in a **UK heatwave** (flat ran hot for a
>    long period) → a species temperature band + room-temp advisory is in v1 (cheap: the hatchery
>    already reads a temperature).
> 8. **Keep it basic**: one daily tap + tint; egg-ratio and badges = optional/later.
> 9. **Separate tab** under NPS beside the hatchery; **rename "Hatchery" → "Brine hatchery"**.
> 10. Continuous reactor **shelved**.


1. **What are the rotifers FOR?** Coral/NPS feeding only, or fish larvae later (clownfish etc.)? Larvae
   changes species (S-type), enrichment rigour and whether continuous supply matters. Copepods: refugium
   seeding, or harvested nauplii as coral food, or both?
2. **Culture salinity**: 35 ppt (one water everywhere, mixing station makes it, ~30 % less yield) or
   ~20 ppt brackish (max yield, OpenReef prints the RODI cut, mild dose shock)? Proposal: 35 ppt.
3. **Feed**: fridge phyto bottles (UK-easy, tint-dosed), RGcomplete (import, ClorAm-X, all-in-one
   enrichment), or run your own phyto culture (a third culture card, needs light)? Proposal: bottles now,
   phyto culture as a later card.
4. **Rig**: standalone jars, or plumb A/B into the existing union with a swappable 53 µm disc (§3.1)?
   And jar size — two 4 L at 2.5 L fill?
5. **A/B from day one** with a 7-day restart stagger — yes?
6. **Harvest cadence + destination**: daily 25 % into the shared LIVE vessel (mixed with brine, shortest
   clock wins), or a separate rotifer bottle in the fridge with its own days-long clock?
7. **Copepod species**: Tigriopus (Reefphyto, hardy, monthly generation), Tisbe (SPS nauplii, needs
   surface area), Apocyclops, or a blend? Which did you run before, and what killed/ended it?
8. **Daily logging appetite**: one tap "Harvested + fed" with a tint choice — enough? Weekly egg-ratio
   spot check (phone macro photo, count by eye): yes/no? Ammonia badges in the jars?
9. **Where it lives**: Hatchery tab becomes **Live food** (brine cones + culture jars in one strip and
   one rig drawing), or a separate Cultures sub-tab?
10. **Continuous reactor** (§3.2) on the hardware backlog, or out of scope entirely?

---

## 7. v1 build shape (from the locked answers)

- **Tabs**: NPS pill row becomes `Feeding · NPS · Brine hatchery · Cultures · Spawning`. Pure rename on
  the hatchery (labels, headers, Pulse copy); no config-key rename.
- **Cultures tab**: a strip of culture jars (one SVG per jar, same idiom as the hatchery strip) + a
  rotifer fridge bottle + a copepod jar. Starts with two species presets: `rotifer_L`, `tigriopus`.
- **Engine** (`cultures.py`, pure maths like `nps.py`): species presets → cadences + bands; clocks
  (culture age, days since restart, next feed, next harvest, next restart, copepod first-harvest
  countdown); state machine `seeding → growing → producing → restart due → crashed`.
- **Rotifer preset**: 35 ppt, band 18–26 °C, feed 2×/day by tint, harvest 25 %/day through 53 µm, restart
  every 14 d (learnable later), sieve 53 µm, bottle shelf life ~3 d at 4 °C (conservative — sources say
  "a limited number of days"), enrichment 6 h (optional, off by default).
- **Tigriopus preset**: 35 ppt, band 20–25 °C (hard warn ≥ 28 °C — the heatwave lesson), feed every 2–3 d
  by tint, first harvest after 7 d, then ~20 %/week, water change 25–50 % every 3 weeks.
- **Split into B**: available once a rotifer jar is ≥ 10 days old (or on demand); creates jar B seeded
  from A, restart clocks offset 7 d; "crashed" on either jar offers "Reseed from the other".
- **Daily tap**: "Harvested + fed" with tint (green / clearing / clear) → feed advice + ledger row;
  harvest volume credits the rotifer bottle; feed ml debits the consumables product.
- **Temperature advisory**: reuse the hatchery's temperature reading (or an optional per-culture HA
  sensor) against the species band; copy escalates to a real warning above the hard line.
- **Reminders**: maintenance-engine tasks per culture (feed / harvest / restart / water change), same
  lockstep rule as the hatchery evaluator; daily tick is sufficient.
- **Out of v1**: union disc, brackish mode, own phyto culture, egg-ratio capture, ammonia badge logging,
  continuous reactor, dosing rotifers through the NPS pump.

### 7.1 What shipped in 0.7.117 (and what was left)

- `cultures.py` (pure engine): `SPECIES` presets (rotifer_L, tigriopus), `culture_state` (none /
  establishing / producing / crashed + feed / harvest / restart / waterChange clocks, split eligibility,
  restart-cycle percent), `feed_advice` (tint × clock), `temperature_advice` (band + hard line),
  `refill_guide` (the measured jug, brackish cut ready for later), `bottle_state` (fail-closed).
- `nps.cultures` config block + `_normalise_cultures` (jar cap 4, cadence caps, unknown species →
  rotifers); `_nps_preserve_runtime` carries per-jar `state`/`history` + bottle level/stamp.
- WS: `cultures_summary`, `cultures_seed` (from starter or sibling), `cultures_log` (tint / fed /
  harvested — feed debits the phyto bottle, a rotifer harvest fills the fridge bottle oldest-stamp-wins,
  the refill debits the mixing vessel under the hatchery coupling toggle), `cultures_restart`,
  `cultures_water_change` (copepods only), `cultures_split` (creates "… B" or reuses an idle sibling),
  `cultures_crash`, `cultures_bottle` (fed / empty). Every chore logs its `culture_<jar>_<chore>`
  maintenance task done (source `cultures`) when the keeper has seeded reminders.
- Panel: `Feeding · NPS · Brine hatchery · Cultures · Spawning`; Cultures tab (mission row, jar strip
  with tint-as-fill SVGs, daily tap, measured jug, heat warning, bottle tile, species notes, journal);
  Culture settings (jars, species, feed bottle, cadence overrides, temp sensor, bottle); "Sync culture
  reminders" seeds per-jar tasks anchored on the jars' real stamps; Pulse insight lines (due chores,
  heat line, stale bottle).
- **Left for later** *(audited against the code 2026-09-06)*: removing a jar leaves its maintenance
  tasks behind — **done 0.7.125** (the panel deletes every `culture_<id>_*` task and completion in the
  same save); no demo-stage data for the Cultures tab — **still open** (the rig's play-the-stages
  preview is the only staged view); brackish mode UI — **done 0.7.125** (per-jar salinity with the
  1.020 recommendation, the jug shows the RODI cut); the union disc — **hardware, no code owed** (the
  drawing already labels the 50 µm net); egg-ratio capture — **done 0.7.126**; continuous reactor —
  shelved (hardware track). Demo-stage data — **done 0.7.140** (the Cultures tab's "Demo view").
  The audit of what V2 left open, and its closure, is §8.12.

---

## 8. V2 — the culture joins the rig (2026-09-05) · STATUS: RELEASED 0.7.125–0.7.129 (2026-09-05); the §8.12 gaps closed in 0.7.140 (2026-09-06)

v1 (0.7.117) shipped a generic jar model with presets taken from a snippet-level sweep. V2 starts
from three things that changed on 2026-09-04: Reece's Reefphyto order landed (invoice 55330), the
rotifers will live in the **same inverted-bottle cone rig as the brine hatchery**, and the bar is
"the go-to system for hobbyist culturing". Every number below was re-read from the page it names
(Reefphyto's own guides and product pages, FAO's live-food manual §3.5/§3.6, one 2025 salinity
study); the few snippet-only facts are marked *(snippet)*. Working notes and the salvaged agent
output live in `~/.claude/projects/-home-reece-Workspaces-Ragnars-Reef/cultures-v2-salvage/`.

### 8.1 What arrived, and what each product is for

| Product (invoice 55330) | Role in the system | Verified facts |
|---|---|---|
| **Live Rotifers 500 ml** | seeds jar A (the cone) | L-type *B. plicatilis*, 90–360 µm, 200–1000/ml; unused starter keeps in the fridge, cap loose, ≤ 5 days; shipping SG not stated (guide cultures at 1.019–1.021 → assume ~1.020) |
| **Rotifer Feed Concentrate 50 ml** | the rotifer jar's food | two-species live blend, *Nannochloropsis oculata* (1–5 µm, EPA) + *Tetraselmis suecica* (8–12 µm, protein/lipid) — nothing else; dose to a **leafy green** (spinach/kale); "little and often, two or three times through the day"; top up when it lightens; fridge; "not interchangeable with Copepod Feed" |
| **Rotifer & Artemia Enrichment 100 ml** | the pre-feed-out DHA step, shared with the hatchery | two-species live blend, *Nannochloropsis* (EPA) + *Isochrysis galbana* (DHA) — an algae concentrate, **not an emulsion**; "1 to 5 drops directly to the culture vessel"; product page: "allow 6 to 12 hours"; culture guide: "two to four hours before harvesting", rinse before feeding; fridge, 3 months |
| **Live Copepods 250 ml** | seeds the copepod tub | *Tigriopus californicus* only, 1–3 mm, shipped concentrated, add on delivery day; density not stated |
| **Reef Juice 250 ml** | **tank dose only** — an NPS phyto consumable, never a culture feed | *Nannochloropsis + Phaeodactylum + Chlorella + Isochrysis*; product page: 1 ml per 27 / 18 / 9 L per day (light / medium / heavy stocking); dosing blog: "two to three additions per week is the right cadence for most reefs", daily "not necessary"; dose into flow at dusk/lights-off, skimmer + UV + ozone off 30–60 min; fridge 4–10 °C, gentle shake, never freeze, 3 months; overdose = hazy for more than a day. Page: "not designed as a culture feed" |
| **Rotifer Sieve Net** | the harvest sieve | 50 µm *(snippet: one page says 54)* — the preset moves from 53 to 50 |
| **Brine Shrimp Eggs 60 g** | the hatchery, unchanged | sealed, dry, ≤ 4 °C; fridge for 3–4 weeks of use, freezer beyond, out a day before use; hatch 1 g/L at 26–28 °C, 25 ppt, 18–36 h *(snippet: humidity is the killer — squeeze the air out of the opened pouch, let a cold pouch warm before opening)* |

**Gap on the invoice:** Reefphyto's copepod guide feeds *Copepod Feed* and says the rotifer
concentrate is not interchangeable. Nothing on the order feeds the pods (§8.10 Q1).

### 8.2 Research digest, refreshed — what v1 got wrong

**Rotifers.** Reefphyto's guide: SG 1.019–1.021 ("lower than reef tank salinity"), 18–25 °C
(22–25 faster), first harvest **5–7 days** after setup once "visibly dense", harvest ≤ 25–30 % per
harvest and the culture "will rebuild its population within 24 hours" so daily harvest is fine,
replace the removed volume immediately with matched saltwater and feed, **every 14 days** transfer to
a clean container (or 50 % change + wall clean), a backup culture keeps in the fridge at 4–8 °C
"up to a week"; crashes = overfeeding (ammonia/nitrite) and skipping the fortnightly clean. FAO §3.5:
tolerates 1–97 ppt but "optimal reproduction" only **below 35 ppt**, acclimate in ±5 ppt steps; at
20 °C first spawn 1.9 d, spawn interval 5.3 h, lifespan 10 d (25 °C: 1.3 d / 4.0 h / 7 d); NH₃
< 1 mg/L safe, pH > 7.5; a starter at 50/ml reaches 200/ml in 3 days, a mass culture doubles every
2 days. The 2025 study (PMC12292424): 25.5 offspring/female at 5 ppt vs 9–10 at 30–35 ppt (≈ 62 %
lower) — but lifespan 273 h at 35 ppt vs 134 h at 5 ppt. **35 ppt is a slower, longer-lived,
lower-yield culture; 1.020 is the practical middle.** Cone rigs are standard aquaculture practice
for rotifers *(salvaged sweep)*: the cone exists so detritus and dead rotifers collect at the tip —
air off, settle 15–30 min, bleed the tip to waste, then harvest; open rigid airline to the tip at
1–2 bubbles/s, no airstone; no light, loose cover.

**Enrichment.** FAO §3.6: emulsion soaks are 200–300 rotifers/ml for 6 h, then harvest, rinse,
concentrate; EFA "remain rather constant for at least 7 h" in clear water at 20 °C, "only a 30 %
drop in DHA after 12 h"; a day's starvation at 25 °C costs up to 26 % body weight. *(snippet,
paywalled: DHA in phospholipid stable 24 h at 10 °C; significant loss at 20 °C after 24 h; rotifers
survive days at 4 °C.)* Reefphyto's product is an algae enrichment, dosed in drops, and its two
pages disagree on the window (2–4 h vs 6–12 h).

**Tigriopus.** Reefphyto's copepod guide: 4 L container or small aquarium, loose cover, **SG
1.020–1.025 ("35 ppt optimal")**, **22–26 °C**, mix water ≥ 24 h ahead, open airline 1–3 bubbles/s,
no light; feed *Copepod Feed* to "Granny Smith apple skin", feed again when it clears, half rate in
week one; **first harvest 4–6 weeks** after setup, never more than 25–30 %, **7–10 days between
harvests**; weekly test + debris removal; 50 % change when parameters drift; **any detectable ammonia
= immediate 50 % change**; crash signs = cloudy/white water, declining numbers, pods clustered at the
surface or not moving. Biology *(salvaged sweep, peer-reviewed)*: 6 naupliar + 6 copepodid stages,
maturity 20–30 d at 20–25 °C, generation ~30 d, lifespan ~70 d, clutches 20–40; acute heat death
only at ~34–36 °C (1 h) — **a 28–33 °C flat kills through chronic fecundity collapse plus low oxygen
and ammonia, usually with overfeeding**, which is what the heatwave did to Reece's jar. Benthic:
needs floor and surface area — **a cone is the wrong vessel for pods**; a flat tub is right.

**The preset table (v1 → v2):**

| Field | Rotifer v1 | Rotifer v2 | Tigriopus v1 | Tigriopus v2 | Basis |
|---|---|---|---|---|---|
| vesselKind (new) | jar | **cone** (the hatchery rig) | jar | **tub** (flat, wide, no tap) | Reefphyto guides, benthic habit |
| salinityPpt | 35 | **27 (SG ≈ 1.020)**; 35 selectable "reef-matched, lower yield" | 35 | 35 | Reefphyto guides, FAO, PMC12292424 |
| tempMin/Max °C | 18 / 26 | 18 / 26 (22–25 sweet spot in copy) | 20 / 25 | **18 / 26** | Reefphyto guides |
| tempHardMaxC | 30 | 30 (unchanged) | 28 | **28 = warn, 30 = act now, 32 = critical**; copy says *why* (oxygen/ammonia, not the animal) | heat-shock papers, Reefphyto ">30 problematic" |
| feedIntervalH | 12 | 12 (two feeds; copy: "little and often", three is better, 24 survives) | 60 | **24** (48 max), tint decides the amount | Reefphyto: rotifers 2–3×/day; pods daily |
| feedProduct | any phyto | **Rotifer Feed Concentrate** | any phyto | **Copepod Feed** (not the concentrate) | product pages |
| tint target | green | "leafy green (spinach)" | green | "Granny Smith apple skin" | Reefphyto guides |
| harvestPct | 25 | 25 (cap 30) | 20 | **25** (cap 30) | Reefphyto |
| harvestIntervalDays | 1 | 1 | 7 | **10** (7–10) | Reefphyto |
| firstHarvestDays | 3 | **6** (5–7; 3 only for a split at harvest density) | 7 | **28** (21 earliest, 42 typical) | Reefphyto, life cycle |
| restartIntervalDays | 14 | 14 **as a cap**, restart on a sign first (§8.5) | 0 | 0, decline-triggered restart from the backup | Reefphyto fortnightly clean |
| waterChange | 0 | 0 (the harvest is the change) | 35 % / 21 d | **harvest volume replaced each harvest + 50 % on a sign** (drift, ammonia, cloudy) | Reefphyto copepod guide |
| splitMinAgeDays | 10 | **14** — the split rides the first restart | 21 | **35**, gated on "visibly dense" | §8.8 |
| sieveUm | 53 | **50** (the net) | 53 | 50 all stages · 300 adults only | product page |
| bottleShelfDays | 3 | **5** viability (7 fed) | 0 | **3** optional (max 7) — *built as 0: a pod harvest goes straight to the tank, no bottle* | Reefphyto, Reed *(snippet)* |
| enrich (new) | — | algae, 1–5 drops per portion, soakH **6** (2–12), rinse; boost warm **8 h**, cold **24 h** | — | not enriched | FAO §3.6, product page |

### 8.3 The method — rotifers in the cone, pods in the tub

**The day the parcel lands (a walkthrough the panel should show once).**
1. Rotifers: the cone holds 2.5 L of 1.020 water (the mixing station makes 35 ppt; the measured
   jug says how much RODI to cut — `refill_guide` already computes it), room temperature, air ON to
   the tip at 1–2 bubbles/s. Float the pouch 15 min, then add culture water to the pouch in steps
   (FAO: ±5 ppt) if we go to 35; pour in. Feed the concentrate to leafy green. Tap **Seed**. First
   harvest unlocks at day 6, earlier only if the water is visibly dense.
2. Pods: the 4 L tub half to two-thirds full of 35 ppt, open airline 1–3 bubbles/s, loose cover,
   out of the sun, indirect light. Pour in on delivery day. Feed at half rate for a week. Tap
   **Seed**. First harvest unlocks at day 28 (the clock says "establishing — a generation is a month").
3. Reef Juice goes in the fridge and onto the NPS shelf as a phyto consumable (§8.6).
4. The enrichment goes on the shelf as the product both the hatchery soak and the rotifer soak
   debit; the eggs get an `openedAt` stamp (§8.6).

**The rotifer cone — the daily ceremony (the stages the drawing plays):**
1. **Look** — tint tap: leafy green / clearing / clear. Clear before the next feed is due = hungry;
   still green at feed time = skip (ammonia). Foam, milky-not-green, smell = a crash sign (§8.5).
2. **Air off, settle** — 15–30 min; crud and dead rotifers sink to the tip, live ones stay up.
3. **Purge the tip** — crack the valve, the first ~50 ml to waste (the crud bleed, exactly the
   hatchery's move). Air back on.
4. **Harvest** — the measured jug: 25 % (625 ml of 2.5 L) through the 50 µm net; the water goes to
   waste (never the tank — culture water is ammonia), the rotifers on the net are the day's crop.
5. **Refill** — the same 625 ml of fresh 1.020 (mix + RODI per the jug), debited from the mixing
   vessel under the existing hatchery coupling toggle.
6. **Feed** — concentrate to leafy green; the second (third) small feed later in the day is a
   phone push, not a tab visit.
7. **Bottle or enrich** — the crop either rinses into the fridge bottle (5-day clock) or goes into
   the enrichment portion first (§8.3 enrichment) and then the bottle with a boost clock.
8. Tap **Harvested + fed** with the tint. Everything above is one row in the journal.

**Fortnightly (or on a sign) — the restart:** air off, settle, purge, then drain the *whole* cone
through the net into a clean cone of fresh 1.020, feed, tap **Restarted**. With the net already in
hand, the first restart is when the split happens: half the crop seeds jar B (§8.8 "never zero").

**The copepod tub — the weekly rhythm:** look every day (a glance, not a tap — the tub is quiet by
design), feed daily-to-every-other-day to Granny Smith, weekly parameter check + siphon the mulm,
harvest 25 % through 50 µm (nauplii + adults) or 300 µm (adults only) once a generation has grown
(day 28+), replace the harvested volume, 50 % change on a sign, never a calendar restart — the
backup tub is the restart.

**Enrichment (the DHA step, optional but honest):** the concentrate feeds EPA and protein, not DHA;
NPS corals get DHA from the enrichment. Portion the day's crop into a 500 ml enrichment vessel of
clean 1.020, 1–5 drops, 6 h (grill Q4 for the 2–4 h vs 6–12 h question), rinse on the net, then
bottle. The bottle then runs the **boost clock**: gut-loaded for ~8 h warm or ~24 h cold from the
end of the soak, viable for 5 days regardless — the hatchery's two-window model (`hatch_prime_state`)
transfers as-is.

**Feeding the tank:** rotifers from the bottle by hand (the NPS hand-feed ledger, a "Fed N ml"
tap), pods by pouring a harvest into the refugium/display after lights-out. Reef Juice on its own
schedule: 3 ml three times a week for 52 L (medium stocking), lights off, skimmer off 60 min — the
existing maintenance reminder engine carries it, the consumables ledger counts it.

### 8.4 The rig drawing — a sibling of the hatchery's

Same idiom as `_npsHatchRigSvg`: dark vessels, monospace labels, circled valve numbers that go hot
when a stage is live, `.awc-flow` animated runs, `.nps-bub` bubbles when air is on, and "the drawing
follows the stage". New method `_culturesRigSvg(rig)` beside it, fed by a `rig` block that the
backend emits in `cultures_summary` (lockstep rule):

- **Rotifer cone(s)** left, scaled 1–4 like the hatch cones: fill polygon = culture density (the
  restart-cycle percent), fill colour = tint (leafy green → pale → clear), stroke = status (steady
  teal / establishing grey / crash-sign amber / crashed red / heat red). Air stub to the tip, hot when
  `airOn`. Label `ROTIFERS A`.
- **Valve ①** on the tip run: hot during *purge* (brown flow to the **waste** cup) and *harvest*
  (green flow to the **sieve capsule** — the same blue union drawing as the 120 µm mesh, labelled
  `50 µm net`).
- **The measured jug** beside the cone: "harvest 625 ml → refill 625 ml @ 1.020 (480 mix + 145
  RODI)" — the numbers from `harvestGuide`.
- **Refill arc** from the **mixing vessel** stub (dashed, hot on the refill stage) into the cone.
- **Feed bottle** (small, green) with a drop arrow — hot on the feed stage; caption carries the tint
  target.
- **Enrichment beaker** (purple, like the SOAK) between the net and the fridge bottle — visible only
  when an enrichment is running, with its percent.
- **Fridge bottle** right, blue-stroked, fill = remaining ml, caption "fresh · ~H h boost · D d
  left" or "stale — tip it out"; "Fed N ml" and "Empty" live on its tile, not the drawing.
- **Copepod tub** bottom right: a wide shallow rectangle, own air stub, fill = tint, stroke =
  status, label `TIGRIOPUS · tub`, a 300 µm net icon on its harvest arrow. Never a tap.
- **Caption line** (`rig.caption`): the stage in words — "settle 20 min — crud to the tip", "harvest
  625 ml through the net", "feed to leafy green", "ROOM 29 °C — over the pod line: extra air, shade,
  feed lightly". Heat lines are never comic.
- **Play the stages**: purge → harvest → refill → feed → bottle, plus "restart" and "split" as the
  long ceremonies. Same button and preview state machine as `nps-rig-play`.
- Compact card / Pulse: the cone's tint dot and the bottle's clock only.

`rig` payload: `{ cones: [{name, tintFill, pct, stroke, airOn, purgeHot, harvestHot, refillHot,
feedHot}], tub: {name, tintFill, stroke, airOn, harvestHot} | null, jug: {harvestMl, mixMl, rodiMl,
ppt}, enrich: {pct} | null, bottle: {ml, pct, status}, caption }`. Viewbox 940 × 760; cones use the
hatch-cone geometry pinned to y = 334 so the air manifold lines up; tub at (560, 560, 200 × 90).

*As built (0.7.125):* `rig` = `{stage, caption, cones, tub, jug, bottle}` — no `enrich` key and no
beaker in the drawing; the soak has its own tile beside the rig, and the drawing's only nod to it is
the "(or enrich this crop first)" caption. `jug` carries `purgeMl` and `sieveUm` as well. A cone is
drawn dashed when its jar is configured and unseeded; since 0.7.140 a lone RUNNING cone earns a
ghost B beside it (`status: "ghost"`, faint and dashed, "comes with the first restart") — the
never-zero doctrine in the drawing, not a jar in the config.

### 8.5 The culture journal and the learned cadences

**Journal rows** (per jar, newest first, the hatch journal's honesty): `event` ∈ seeded / fed /
harvested / restarted / split / reseeded / water_change / enriched / fed_tank / crash_sign / crashed,
`at`, `tint`, `ml` (harvest or feed), `sign` (foam / milky / smell / surface-cluster), `eggRatio`
(optional spot check, %), `tempC` (the room at the tap), `from`/`into`. The table shows date · event ·
tint · ml · the story line ("day 12 · restart cycle 85 % · clearing in 9 h"). One row per tap — the
ceremony writes it.

**Learned cadences (rolling three, advisory with Apply — the `learned_hatch_hours` contract):**
- **Clearing clock → feed interval.** Every tint tap is stamped. The hours from a *fed/green* tap to
  the next *clear* tap is one sample of how fast the jar eats; the rolling three become "your jar
  clears in ~9 h — feed every 8 h" with an Apply chip on `feedIntervalH`. Faster clearing over a week
  = the population is climbing; slower = decline (a crash-risk input).
- **First harvest actual.** Seed → first *Harvested* stamp per species; after two samples, the
  establishing clock advises "your last two took 5 days".
- **Restart run length.** Seed/restart → next restart or crash; the rolling three cap
  `restartIntervalDays` ("your cone runs 11 days before it turns — restart on day 10").
- **Harvest yield.** ml/day actually taken, feeding the NPS runway and the next-harvest suggestion.
- **Copepod first harvest and interval.** Same shape on the tub's slow clock.

**Restart on a sign, not a date** (from the skeptic, adopted): the *Restarted* chore becomes due on
the earliest of (a) a crash-sign tap, (b) clearing time stretching past 1.5× the learned clock two
taps running, (c) the day cap (14, learned down). The copy says which one fired.

**Crash-risk line** (the hatchery nose, explainable): a per-jar `risk` ∈ ok / watch / act built only
from stamps — missed harvests since the last (harvest debt → ammonia), a feed logged while green
(overfeed), clearing slowing, a sign tap, room over the band. Shown as one sentence with the cause,
never a score.

### 8.6 Folding into NPS — the hatchery's seams, reused

- **Feeding hub compact card** (`_culturesPanel(compact)` beside `_hatcheryPanel(compact)`): cone
  tint dot + "harvest due", bottle "N ml · fresh", tub "day 19 of 28", one "Open Cultures →".
- **Consumables shelf:** four Reefphyto presets in `nps.py` PRODUCT_LIBRARY — *Reef Juice* (phyto,
  250 ml, 90 d, refrigerated, stir daily), *Rotifer Feed Concentrate* (phyto, 50 ml, 90 d), *Rotifer
  & Artemia Enrichment* (phyto, 100 ml, 90 d — the hatchery's `enrichment.productId` and the jar's
  `enrich.productId` point at the same bottle), *Copepod Feed* (phyto, 30/50 ml). Jar feeds and the
  soak debit the shelf exactly as the hatchery does; the runway line says "concentrate: ~5 weeks at
  your rate" *(built as the shelf card's generic days-left — there is no concentrate line on the
  Cultures tab)*.
- **The eggs get a stamp:** `hatchery.cysts.openedAt` + the 3–4 week fridge window → a Pulse line,
  nothing more.
- **Reef Juice on the reminder engine:** a "Dose Reef Juice" custom task, cadence 2–3 d, default dose
  from the stocking band (`1 ml / 18 L × tank.volumeLitres`), completion debits the product.
  *(Realised 0.7.129 as the shelf's own hand-dose plan — see the addendum under §8.11; nothing of it
  lives in `nps.cultures`.)* The NPS
  feed plans gain `zooLive` foods "Live rotifers (bottle)" and "Live Tigriopus (harvest)" with
  particle sizes 90–360 µm and 120–1200 µm so the species compiler can pick them.
- **Hand-feed from the bottle:** `cultures_bottle {action: fed, ml}` already debits; V2 also logs the
  NPS hand-feed reminder done (`_nps_log_hand_feed` with source `cultures`) and writes a `fed_tank`
  journal row.
- **Next-harvest suggestion:** `cultures.next_harvest(now, bottle, ml_per_day, jar_clock)` — the
  `next_hatch_suggestion` shape: harvest before the bottle runs dry or goes stale, "in ~14 h" /
  "now" / "past due", driver = depletion | freshness | jar.
- **Pulse:** existing cultures block gains the boost clock ("rotifer bottle: gut-loaded, 3 h left")
  and the risk line; the heat line stays critical.
- **Mixing station:** refills and restarts already debit the vessel; the RODI cut shows in the jug.

### 8.7 Config, WS and guard changes (concrete)

`nps.cultures.jars.<id>` gains `vesselKind` (cone | tub | jar), `enrich {productId, dropsPerPortion,
soakH, boostWarmH, boostColdH}`, `learned {clearingH: [..3], firstHarvestDays: [..3], runLengthDays:
[..3], yieldMlDay}` *(server-written → `_nps_preserve_runtime`)*, `state.lastSignAt`,
`state.lastSign`, `state.riskAt`; journal rows gain `sign`, `eggRatio`, `tempC`. `nps.cultures.bottle`
gains `enrichedAt`, `refrigeratedAt`, `lastLoadEnriched` (the hatchery bottle's stamp shape, so
`hatch_prime_state` runs it) *(runtime → guard)*. `nps.cultures.enrichment.state` mirrors the
hatchery soak state (`startedAt`, `portionMl`, `firstDoseAt`) *(runtime → guard)*.
`hatchery.cysts.openedAt` *(runtime → guard)*.

New/changed WS: `cultures_log` accepts `sign`, `egg_ratio`; `cultures_enrich {jar_id, ml}` /
`cultures_enrich_done` (soak start/finish on the portion, debit the shelf, stamp the bottle);
`cultures_bottle {action: fed}` logs the NPS hand-feed; `cultures_apply_learned {jar_id, field}`
(the Apply chip, never automatic); `cultures_summary` emits `rig`, `learned`, `risk`, `nextHarvest`,
`bottle.boost`; `cultures_remove_jar` deletes its four maintenance tasks (the v1 orphan). Engine
(`cultures.py`): `clearing_samples`, `learned_cadence`, `risk_line`, `next_harvest`, `restart_signal`,
`bottle_boost_state` — pure, tested in `test_cultures.py`; panel cases in `test_panel_cultures.mjs`
(rig svg per stage, journal rows, Apply chips, compact card, Pulse boost line).

**As built (0.7.125–0.7.129, audited against the code 2026-09-06) — where the shipped shape differs
from the plan above:**
- The enrichment is ONE shared block, `nps.cultures.enrichment {productId (blank = the hatchery's
  bottle), drops, soakH 2–12, boostWarmH, boostColdH, state {startedAt, portionMl, jarId}}` — not a
  per-jar `enrich`; `state` is guarded.
- `learned` is NOT stored: `cultures.learned_cadences` computes the rolling three from the journal on
  every summary, and the Apply chip (`cultures_apply_learned {jar_id, field}`) is the only write. There
  is no `state.riskAt` (the risk line is computed) and no `bottle.refrigeratedAt` (the cultures bottle
  is always in the fridge); the bottle carries `enrichedAt`, `lastLoadEnriched`, `history[:30]`.
- No `cultures_enrich` WS: `cultures_log {enrich: true}` sends the crop to the soak and
  `cultures_enrich_done {bottled}` ends it. No `cultures_remove_jar` WS: the panel removes the jar and
  its `culture_<id>_*` tasks and completions in the same `save_config`.
- Engine names: `learned_cadences`, `bottle_boost`, `soak_state`, `next_harvest`, `heat_guard`,
  `stagger_advice`, `tint_strip`, `continuity_days`; the restart reason (cap / sign / slow) lives
  inside `culture_state` rather than a separate `restart_signal`.
- Added beyond the plan: per-jar `vesselKind` + `purgeMl` (settings-owned), `state.generation`,
  `cultures.continuity{species:{since}}` + `cultures.guard{notified}` (guarded), `hatchery.cysts.openedAt`
  (guarded), the phone actions `OPENREEF_CULTURE_{HARVEST|FED|RESTARTED|LATER}:<jar>` and
  `OPENREEF_HATCH_LOADED:<vessel>` handled by the same cores the tab's buttons call, and a source-level
  test that every `websocket_*` handler is registered (three Stage B–C handlers were not until 0.7.129).
- **0.7.140 (the §8.12 closure):** journal rows carry `purgeMl` (harvest + restart rows on a cone;
  normaliser clamps 0–500) and `learned.purge` (`run_length_runs` + `purge_note`: two runs at each of
  two volumes before it speaks); `rig.cones[]` may end with a `status: "ghost"` B; `heat_guard(...,
  offset_c)` + `rack_offset_c` (the rack sensor's lead over the projection's "now" row, clamped ±5,
  under 0.5 = noise) and `summary.rackOffsetC`; `summary.arrival.rotifer` = `acclimation_plan(27,
  cone ppt)` (equal steps ≤ 5 ppt, each addition sized for one step, four additions max, honest when
  the cap cannot close the gap); the hatchery's three soak notices push through
  `_async_push_actionable` with `OPENREEF_ENRICH_{DOSE|TOPUP|LOADED}` (cores
  `_nps_enrich_{dose,second_dose,loaded}_apply` shared with the WS handlers); the daily maintenance
  digest carries `Done: <task>` for the first two tasks (overdue first) + Later, tag
  `openreef_maintenance_digest`, handled by `OPENREEF_TASK_DONE:<task_id>` →
  `_maintenance_complete_apply` (the service's own core; the entry has no `source` — it is the
  keeper's completion — the notes and the event say "phone"). Panel: the Cultures tab's Demo view
  (summary-only swap, every tap refused, never saved).

### 8.8 Suggestions — what would make it the go-to system (ranked)

Three salvaged proposal sets (a hatchery scientist, a community builder, a skeptic) plus my own
read of the codebase. Graded on: removes a chore or prevents a crash, stands on something shipped,
nobody else has it.

**The headline leapfrog — "the jar that says why".** Nobody at hobby level has *explainable*
culture health: OpenReef already has the stamps (every tap), the room (cooling headroom's per-hour
learned offsets and forecast), and the journal idiom. Put together: a crash-risk line built from
harvest debt, overfeeding, clearing slowdown, sign taps and room temperature — and a **heatwave
guard that warns a day ahead** ("room passes 28 °C tomorrow 15:00 — extra air, shade, feed lightly,
50 % change ready"), which is the exact failure that killed the last pods. Demoable in two minutes on
a stream, defensible, and it is mostly maths over data we already hold.

1. **Restart on a sign + learned cap** (M) — §8.5. Kills the calendar guess, the first "learned
   cadence" people will feel.
2. **Heatwave guard, 24 h ahead** (M) — cooling headroom's forecast × species band → one push, with
   actions. Stands on 0.7.120–122.
3. **Harvest debt and the overfeed refusal** (S) — deterministic ammonia arithmetic on stamps: two
   missed harvests = "harvest before you feed"; a feed logged on green = "skip". Pure engine, no
   sensors.
4. **Never zero: the split rides the first restart** (M) — the restart ceremony (net in hand) seeds
   jar B by default; the mission headline becomes "backup: yes/no". Two-jar doctrine without a second
   ceremony.
5. **The one-question day** (M) — every culture push collapses to one actionable notification per
   rig ("Harvest the cone? Harvested + fed / Snooze"), using the existing HA notification actions;
   the tab is for looking, the phone is for tapping.
6. **Clearing clock → feed-by-demand** (M) — §8.5; the concentrate's "little and often" tuned to
   *this* jar.
7. **Starter acclimation protocol** (S) — the arrival walkthrough (§8.3) with the salinity step
   maths; a hatchery never pours a bag straight in.
8. **Vendor presets + scan-the-product** (S/M) — Reefphyto presets on the shelf now; a barcode/QR
   scan to add a bottle later.
9. **Culture cards** (S) — the share-card idiom from Camera V2 applied to a jar: species, age,
   restart ring, a 14-day tint strip, "gen 3 from the 500 ml starter". This is the thing people post.
10. **Lineage and stagger planner** (S) — every seed/split/reseed writes a parent link and a
    generation counter; the rack shows A and B out of phase.
11. **Continuity days, the anti-leaderboard** (S) — one honest number per species: days since the
    rack was last without a producing jar. Consistency, not volume.
12. **Culture doctor** (M) — a ranked differential from the ledger ("cloudy + day 13 + two missed
    harvests → ammonia; restart, feed at half"), answered by Lagertha when summoned.
13. **Demand-driven production** (M) — size the harvest to the NPS feed plan (ml of bottle per feed ×
    feeds/day) and say when a second cone is worth it.
14. **Camera tint and the 1 ml count** (L, later arc) — a white card behind the cone and the ELP
    camera give a tint reading; egg ratio from a phone macro is the v3 "Rotiferometer" move.
15. **Seed swap + opt-in benchmarking** (L, later) — bag a 20 % starter with a printable lineage
    label; anonymised "you vs the field" cadences.

**Refused, on the skeptic's advice:** automating the harvest valve (a servo on culture water next to
a reef is a leak and an ammonia risk for a 60-second chore), a phyto drip pump on the jar (overfeeding
is the #1 crash cause; a pump makes it automatic), and any volume leaderboard.

**Three quick wins (a day each):** the Reefphyto presets on the shelf; the four preset corrections
(§8.2) plus the 50 µm net; the v1 orphan-task cleanup on jar removal.

### 8.9 Staged build

- **A — the numbers and the rig (0.7.125 · RELEASED 2026-09-05, 3f23125):** preset table §8.2 (incl. `vesselKind`), Reefphyto
  presets on the shelf, `_culturesRigSvg` + play-the-stages, the arrival walkthrough, orphan-task
  cleanup, 50 µm. Tests for every preset change.
- **B — the journal that learns (0.7.126 · RELEASED 2026-09-05, 7a81461):** sign/egg-ratio/temp on the log, clearing clock, first
  harvest and run-length learning with Apply chips, restart-on-a-sign, harvest debt/overfeed refusal,
  the risk line, the one-question notification.
- **C — the DHA step and the tank (0.7.127 · RELEASED 2026-09-05, afc622e; the Reef Juice pieces moved to the shelf in 0.7.129):** rotifer enrichment soak on the shared bottle, the
  bottle's boost clock, hand-feed → NPS ledger, next-harvest suggestion, Reef Juice reminder + feed
  plan foods, the eggs' opened stamp, compact card + Pulse lines.
- **D — never zero and the guard (0.7.128 · RELEASED 2026-09-05, 5a9eeae, tag v0.7.128):** split rides the restart, lineage/stagger, heatwave
  guard on the cooling forecast, continuity days, culture card.
- **0.7.129 (RELEASED 2026-09-05, 2e0dd39, tag v0.7.129):** Reef Juice out of the cultures, onto the
  shelf's hand-dose plan — the addendum under §8.11.
- **Later arcs:** culture doctor via Lagertha, demand-driven sizing, camera tint, seed swap — none
  started; the audited remainder is §8.12.

### 8.10 The grill — answer these and A starts

1. **Copepod feed.** Nothing on the invoice feeds the pods. Order Reefphyto *Copepod Feed* (their
   guide's product), or feed the rotifer concentrate against the page's advice? *Default: order the
   Copepod Feed; preset points at it.*
2. **Rotifer salinity.** Follow Reefphyto at 1.020 (27 ppt, mixing-station cut, ~2.5× the fecundity
   of 35 ppt) or keep 35 ppt for a matched backflush and longer-lived animals? *Default: 1.020; 35
   stays selectable.*
3. **Feeds per day.** Two small feeds (12 h) or three (8 h) for the cone? Reefphyto says two or
   three; the learned clearing clock will tune it either way. *Default: 12 h.*
4. **Enrichment window.** Ask Darren which of Reefphyto's two numbers (2–4 h vs 6–12 h) is right for
   their algae product; until then, 6 h? *Default: 6 h, editable 2–12.*
5. **Enrich by default?** Every crop through the DHA step, or only the crop destined for the corals
   that week? *Default: optional, off; the bottle shows "not enriched" honestly.*
6. **Purge volume.** How much do you bleed off the tip before harvest? Sources say "the settled
   layer", no ml. *Default: 50 ml, a setting on the cone.*
7. **Cone volume and count.** One 2.5 L cone for A now, B at the first restart on the same rig (a
   second cone shares the air manifold like the hatch cones)? *Default: yes, B is drawn greyed until
   it exists.*
8. **Copepod tub temperature line.** Keep 28 °C as *warn* with 30 *act* and 32 *critical*, and the
   copy that explains it is oxygen and ammonia? *Default: yes.*
9. **One-question notifications.** Are you happy for culture pushes to become actionable HA
   notifications (buttons), or keep them as plain reminders? *Default: actionable, with the plain
   fallback for the wall.*
10. **Heatwave guard.** Use the cooling-headroom forecast for the day-ahead warning even though the
    jars sit in a different room from the humidity sensors? *Default: yes, with a per-rack sensor
    override you already have.*
11. **Reef Juice cadence.** Reefphyto's page says daily, its blog says 2–3× a week. *Default: 3 ml
    three times a week for 52 L, lights off, skimmer off 60 min.*
12. **Culture cards.** In D, or sooner because Culture Sunday could use it? *Default: D.*

### 8.11 The grill — ANSWERED 2026-09-05, decisions LOCKED

1. **Copepod feed:** Reece already has Reefphyto Copepod Feed → the tub preset points at it; add it to the shelf presets.
2. **Rotifer salinity:** user-selectable per jar with the recommendation shown ("Reefphyto cultures at 1.020 — ~2.5× the fecundity of 35 ppt; 35 ppt = matched backflush, longer-lived, lower yield"). Default 1.020 (27 ppt), the jug shows the RODI cut.
3. **Feeds:** 12 h.
4. **Enrichment window:** 6 h default, editable 2–12 (Darren's answer can move the default later).
5. **Enrich per harvest, opt-in each time** — the hatchery's pattern: "Harvested + fed" offers "Enrich this crop"; the bottle shows enriched/not.
6. **Purge volume:** unsure → default 50 ml, a setting on the cone, and the journal logs it so the learned run length can say whether more helps.
7. **Cones:** yes; **cone volume user-selectable** (Reece will run small for the 52 L) — `volumeL` already exists, the jug scales; B is drawn greyed on the shared manifold until it exists.
8. **Tub heat tiers:** 28 warn / 30 act / 32 critical, copy explains oxygen and ammonia.
9. **Actionable pushes: yes.** Checked: today the brine hatchery's pushes (hatch ready, soak dose due, and the maintenance daily digest) are plain `notify` title + message with **no action buttons**. V2 adds a shared `_async_push_actionable(...)` helper (HA mobile-app `data.actions`, with the plain fallback when the target is not a mobile app) and both the hatchery and the cultures use it — same behaviour on both tabs.
10. **Heatwave guard:** yes, on the cooling-headroom forecast, per-rack sensor override.
11. **Reef Juice cadence:** user-selectable (daily / 2–3× week); Reece runs daily. Default dose from the stocking band; the reminder follows the chosen cadence.
12. **Culture cards:** Stage D.

Stage A (0.7.125) is unblocked.

#### Addendum 2026-09-05 (0.7.129) — Reef Juice leaves the cultures for good

Reece: "the 'reef juice' is nothing to do with the cultures. it is just a product to be dosed to the
tank — it belongs in the automated NPS system (food shelf) instead." So the Stage C `phytoDose` block,
its "The tank's phyto" panel, its settings, WS (`cultures_phyto_dosed`), reminder
(`culture_phyto_dose`) and Pulse line are all gone from Cultures. In their place, **every shelf
product carries a hand-dose plan**: `doseMl` (0 = from the guide), `doseEveryDays` (0 = no
reminder), `doseStocking`, `doseGuide` (litres per ml a day per band — the Reef Juice preset ships
`{light: 27, medium: 18, heavy: 9}`, `doseEveryDays: 1` and a dusk/skimmer-off note), `doseNote`,
and the server-written `lastDosedAt` (in the stale-save guard beside `remainingMl`/`history`).
`nps.hand_dose_state` computes the size, cadence and due clock; the NPS summary's `shelf.products[pid].handDose`
carries it and `shelf.doseDueCount` counts it. The shelf card shows the plan and a one-tap **Dosed N ml**
(`consumable_log_dose` without `ml` uses the plan, stamps the clock, logs the `nps_dose_<pid>`
reminder done with source `shelf`, writes the activity line). The panel seeds/removes
`nps_dose_<pid>` in Maintenance as the cadence is edited (and when a preset with a plan is added);
deleting the bottle drops the task and its history. Pulse: "Food shelf · Reef Juice: dose due".
A 0.7.128 config migrates once in the NPS normaliser (plan fields onto the product,
`culture_phyto_dose` renamed). Found on the way: the Stage B–C handlers `cultures_apply_learned`,
`cultures_enrich_done` and `nps_cysts_opened` were never registered in `async_setup_entry` (the
fake HA's lenient stub hid it) — registered now, with a source-level test that every
`websocket_*` handler is registered.

### 8.12 What stayed open — audited 2026-09-06, closed in 0.7.140 the same day

Everything §8.9 scheduled is released (0.7.125–0.7.129). The audit against `cultures.py`,
`__init__.py` and the panel found six locked answers only partly delivered and one v1 leftover;
0.7.140 closed every one that code can close.

**Closed (0.7.140):**
- **#6 purge in the journal** — harvest and restart rows on a cone record `purgeMl`; the journal
  shows "harvested · bled 50 ml"; `learned.purge` compares run lengths by purge volume once there are
  two runs at each of two volumes ("runs bled ~100 ml lasted ~13 d, ~50 ml lasted ~11 d — the bigger
  purge buys ~2 more days" / "no difference — keep the smaller purge" / "bleed less").
- **#7 "B greyed until it exists"** — a lone running cone earns a ghost B on the manifold: faint,
  dashed, "comes with the first restart"; the shape line counts real cones and says B is pencilled in.
- **#9 actionable pushes on both tabs** — the hatchery's dose / top-up / soak-done notices carry
  "Dose added" / "Top-up added" / "Enriched & loaded" + Later; the daily digest carries "Done: <task>"
  for the first two tasks (overdue first) + Later. Every button runs the same core as the tab's
  button; a stale tap is refused into the activity feed. The heat-guard push stays button-less (nothing
  to tap).
- **#10 per-rack sensor for the guard** — `cultures.tempEntity` (or the hatchery's) read against the
  projection's "now" row gives the rack's offset (clamped ±5 °C, under 0.5 = noise); every guard
  shifts the forecast by it and the line says "rack +2.0 °C over the room"; `summary.rackOffsetC`.
- **§8.8 #7 starter acclimation maths** — the walkthrough now reads the backend's plan: "the starter
  is at ~27 ppt and the cone at 35: float the pouch 15 min, then add 500 ml of cone water, wait 15 min
  (~31 ppt); then net them into the cone — the last step is 4 ppt". Starter salinity = 27 (Reefphyto
  cultures at 1.019–1.021; the shipping SG is not on the page — an honest assumption, in the code
  as `STARTER_PPT`).
- **Demo-stage data for the Cultures tab (§7.1)** — "Demo view" on the tab: two cones out of phase,
  the tub, a soak running, tomorrow's heat warning, a journal that learned. Summary-only swap; every
  tap and the reminder sync are refused while it shows; nothing is ever saved.

**Still open (not code):** Darren's answer on the enrichment window (2–4 h vs 6–12 h) — `soakH`
stays 6 (2–12) until then.

**Never built (the "later arcs", untouched by design):** culture doctor via Lagertha (§8.8 #12);
demand-driven sizing (#13 — `yield_ml_per_day` and the bottle's depletion driver exist, "when a
second cone is worth it" does not); camera tint and the 1 ml count (#14); seed swap and benchmarking
(#15); scan-the-product (#8, second half); the continuous reactor (shelved, hardware track). The
union disc is a purchase, not code.

**Unverified on real HA:** the companion-app action buttons (now on hatch-ready, the three soak
notices, the cultures question and the digest), the heat guard against the live cooling projection
with the rack offset, and the culture-card share from the iPad. That soak is the next step.
