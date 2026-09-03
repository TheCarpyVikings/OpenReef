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
- **Left for later**: removing a jar leaves its maintenance tasks behind (delete them by hand or re-sync);
  no demo-stage data for the Cultures tab; brackish mode UI (engine already computes the cut); the union
  disc; egg-ratio capture; continuous reactor (shelved).
