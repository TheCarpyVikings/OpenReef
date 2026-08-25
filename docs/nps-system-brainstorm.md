# Automated NPS System — research + design brief

Date: 2026-08-12 · Status: **Stage A SHIPPED (0.7.40, 2026-08-13)** — Stages B–E next · Research: 3 web agents + 3 codebase mappers (full dossiers summarized here)

> **Naming decision (2026-08-13)**: plain **"NPS"** for the tab and marketing ("Automated NPS System" long form). Feast/Ægir branding rejected — searchable beats clever here.
>
> **Stage A shipped**: `nps.py` engine + `config["nps"]`/`config["consumables"]` + gated NPS tab; `food` chemical + channel cap 8→32; system-wide consumables shelf (seeded product library, runway forecasts, fail-closed opt-in expiry, manual-dose logging, new-bottle/top-up); pump↔bottle bridge (`reservoir.productId` + `productIsBottle`: dose-flush debits or refill-transfer debits); canonical AWC amount card on the tab. WS: `nps_summary`, `consumable_log_dose`, `consumable_refill`, `consumable_delete`. Tests: `tests/test_nps.py` (20 green).
>
> **Stage B shipped (0.7.41, 2026-08-13)** — the brine feed-exchange as an **owed matched drain**: every live-food dose **plus its line-flush chaser** (Reece's catch — the ~200 ml chaser dwarfs the brine dose) banks owed drain volume; the AWC drain pump runs it back out from the minutely tick's idle path (calibration-run pattern: timed volume-primary run, `NPS_DRAIN_UNSUB` mutual exclusion with changes/cal-runs, orphan recovery with elapsed-time partial credit, full guard chain via `start_guard_reasons(fill_role="drain")`, waste-headroom + max-runtime clamps, owed cap with reported-never-silent overflow). Brine dose volume is credited into the AWC fill ledger so net-imbalance stays honest. Hatchery card: channel picker, 24 h nutritional-prime countdown, freshness clock, "Hatched & loaded", one-tap maintenance reminders. Tests: 33 green.
>
> **Design change from §5.4 (Stage B, deliberate)**: the raw **net-export dial is dropped**. Draining more than you dose doesn't export nutrients "for free" — the level drop makes the ATO top up with RO, so exportBias is actually a slow salinity-freshening mechanism. The exchange itself is already a genuine micro water change (old tank water out, clean brine suspension in); extra export = raise the AWC amount, which the NPS tab's water card edits directly. The Stage D nutrient-budget advisor will make that suggestion data-driven instead.
>
> **Stage C shipped (0.7.42–0.7.43, overnight 2026-08-13/14)**: the **feed truce** — new `uv`/`ozone` equipment profiles; armed UV/ozone/skimmer pause for configurable windows after every food dose, stamp-driven restore via the dosing-tick backstop, only truce-claimed entities ever restored. And the **`ha_switch_timed` generic pump driver** — any HA switch + 30 s flow calibration is a dosing channel; HA executes the schedule (best-effort by design, never a catch-up bolus, kalk refused outright); guard chain is enforcement; per-dose runtime cap; persisted run stamps with honest-elapsed restart recovery. Also fixed: dosing graft-save dropped bottle debits; flow-calibrated channels read as permanently uncalibrated in the guard mirror.
>
> **Stage D shipped (0.7.44)**: **species plans** — 10-species library (research §3 distilled) + compiler: shelf coverage by food category AND particle window, per-pump cadence suggestions with Apply (night-weighted for nocturnal feeders), difficulty-5 honesty banner. **Nutrient budget v1** — per-category rough N/P densities (labelled rough), feed load from the shelf's own logged usage, feeding-only steady-state NO₃ projection vs the AWC export, graded against the 2–20 ppm band including the "too clean" warning.
>
> **Stage E, first slice (0.7.45)**: Pulse insight card (owed drain, hatch prime countdown, truce pauses, blocked-drain warning; tone-aware copy) + opt-in camera capture trigger on matched drains. **Deferred, deliberately**: the living-diagram plankton shimmer (diagram visuals get iterated eyes-on via the iPad, not blind) — plus Polyp Watch, sun-coral trainer, standing-density phyto mode, line-hygiene tracker from the Tier lists.

The headline feature: a dedicated **NPS tab** that turns OpenReef into the first integrated automated feeding system for non-photosynthetic corals — coordinated live-food dosing, feeding-matched water exchange, food inventory, and species-based feeding plans, with safety interlocks throughout.

---

## 1. The claim (verified 2026-08-12)

**"The first integrated, automated NPS feeding system for home aquariums"** is defensible with precise wording. The prior-art survey found:

| Capability | Best existing instance | Integrated with the others? |
|---|---|---|
| Scheduled live/liquid food dosing | Pacific Sun PR reactor → Kore doser (phyto only); DIY DOS/Kamoer fridge rigs; Avast "Plank" (freeze-dried only) | No |
| Matched/automatic water exchange | Neptune DOS AWC, drip AWC | Never food-coupled |
| Food inventory tracking | GHL days-until-empty (generic mL math); Neptune DDR 20% optical alert | Not food-aware |
| Species-based feeding plans | **Nothing anywhere** — forum lore and papers only | No |

Hobby literature states flatly that commercial refrigerated NPS feeders "do not exist" — every real-world NPS success is a hand-rolled fridge + doser + timer + heavy manual water changes.

**Wording rules:**
- ✅ "First **integrated, automated NPS system** for home reefs" — every clause verified absent from the market.
- ❌ "First automated plankton feeder" — false (Avast Plank, Pacific Sun exist).
- Nearest competitors to name-check honestly: Pacific Sun PR+Kore (phyto-only supply chain, no coordination); a hand-programmed Neptune stack (AFS+DOS+DDR gets an expert ~70% of the way with zero NPS semantics — this is what the Apex-owning beta tester will benchmark against).
- Genuinely novel and worth headlining: **feeding-load-matched water exchange** (nobody does this), food-aware inventory, species plans, and the safety orchestration that makes it a *system*.

## 2. Locked decisions (Reece, 2026-08-12)

1. **Livestock scope: everything** — sun corals through Dendronephthya, dedicated mixed NPS tank. Species plans must span easy→"impossible".
2. **Pump hardware: both** — reefnode ESPHome pumps first-class (calibration, wear, tubing age) AND generic HA switch entities (the deferred `DOSING_DRIVER_TYPES` "generic HA adapter is v2" slot becomes part of this arc).
3. **Live brine v1: manual hatch → aerated reservoir.** User hatches, rinses, resuspends in tank-matched saltwater; system doses, matches drain, and runs hatch/refresh reminders. Config architected so an auto-hatchery ESPHome node can slot in later.
4. **Inventory: system-wide consumables engine.** One bottle tracker for ALL products (foods, phyto, bacteria, 2-part, trace); the NPS page surfaces the food shelf, the dosing tab gets bottle runway for free.

## 3. Research digest — what NPS animals actually need

### Difficulty ladder & feeding requirements

| Group | Eats | Cadence | Notes |
|---|---|---|---|
| **Tubastraea sun corals** (easiest) | Meaty: mysis, brine, krill, LRS blends | 2–3×/wk min, daily ideal; Tidal Gardens optimum "12–24 small feedings/day" | Nocturnal but **trainable to open in daytime** by consistent scheduled feeding shifted gradually earlier; scent triggers extension |
| Chili coral | BBS, decapsulated cysts, rotifers, Oyster-Feast | Every other day min, daily preferred | Strictly nocturnal; feed with flow killed, at night |
| Easier gorgonians (Menella, Swiftia, Diodogorgia) | Micronized Calanus, BBS, copepods — **particle ≤ polyp mouth** | Few×/wk | The recommended starter NPS |
| Dendrophyllia/Balanophyllia | Same as sun coral, more often + more volume | Daily+ | Balanophyllia very light-sensitive |
| Rhizotrochus | Whole silversides/shrimp | Per-polyp target feeds | Deepwater — cool-tolerant, chillers relevant |
| Harder gorgonians (Euplexaura, Guaiagorgia) | Fine zooplankton | Daily | |
| Flame scallops, sponges, tunicates | Phyto 5–40 µm continuous | Standing density | Decline invisibly; most starve <6 months |
| Blueberry gorgonian | Live micro-plankton, rotifers, oyster eggs | Near-continuous | "Cut flowers of the hobby" |
| **Dendronephthya/Scleronephthya** | **Mostly PHYTO** (50–200× more carbon from phyto than zoo; weak nematocysts) — Nannochloropsis/Iso/Tetraselmis + copepod nauplii | **Continuous**: standing density 5,000–50,000 cells/mL (slight green tint), the only proven method | Flow 10–25 cm/s laminar/alternating; most slowly starve over 2–6 months |
| Feather stars (hardest) | ~400 µm zooplankton | Protocol: 4 feeds/day, each spread over 2 h, 24/7 | Two known long-term successes ever |

### The engineering constraints that shape the design

- **Many small pulses beat 1–2 big feeds** for every group (Dendrophyllia 12–24 micro-feeds/day; crinoid 4×2h windows; carnation continuous). Micro-dose scheduling is the core primitive — and the dosing engine already compiles daily-total → 0.1–10 ml doses at 1–240 min intervals.
- **The paradox: constant food vs water quality.** NPS keepers run oversized skimmers wet, 100 µm socks, carbon dosing, and **small daily water changes (~1%/day) or continuous drip AWC** — exactly OpenReef's interval-mode micro-change AWC. Nutrient guardrails: NO3 2–20 ppm, PO4 0.01–0.1, **never zero** (starving the bacterioplankton loop kills NPS too).
- **Baby brine (Artemia) clock**: hatch 18–24 h @ 26–30 °C, ~25 ppt (lower than reef — hence rinse + resuspend in tank-matched saltwater; **never dose raw hatch water**: bacteria, ammonia, shells). Caloric value drops **30–50% between 24 h and 48 h post-hatch** — freshness is a real nutritional deadline, not fussiness. Refrigeration (2–10 °C) + gentle aeration stretches a hatch to 24–48 h. Enrichment (SELCO) is a second ~24 h stage — v2 territory.
- **Peristaltic pumps don't shred nauplii** (low-shear; centrifugal impellers and strong airlifts are the killers). Community practice: **larger-ID tubing** (≥3/16", one build 6.8 mm) so nauplii pass whole and lines don't clog.
- **Nothing organic may sit in a line.** Phyto metabolizes and dies in the tube; slurries rot. Proven fixes: reverse the pump after each dose, or the WARF two-pump **dose-then-flush** (200 mL clean chaser) — OpenReef's brushed live-food head already has a `chaserSeconds` fresh-water rinse. Chemical clean cadence scales with dose count (NaOH soak every ~6 wks at 12 doses/day).
- **Reservoir viability clocks differ per food**: live phyto ~4 wks refrigerated **with daily agitation** (settled phyto dies in days — stirring is mandatory); mixed Reef Nutrition blend ~1 month refrigerated; live BBS 24–48 h; Reef-Roids slurry hours-to-a-day. Per-product expiry must be first-class.
- **Equipment truce during feeds**: UV kills dosed live plankton (standard practice: UV off a few hours post-dose); ozone likewise (and ORP crashes after feeding, driving ORP-controlled ozone harder — gate on feed events, not ORP); skimmer off 30–60 min or it strips the feed and overflows, then **wet-skim after**; return off / wavemakers low 10–30 min to hold the food "soup" in the display. All documented practice — nobody automates the ensemble.
- **Failure modes to design against**: slow starvation (#1), nutrient runaway → algae blankets colonies, overnight bacterial melts, wrong flow, wrong temp for deepwater species, **keeper burnout on 24/7 schedules — the strongest argument for this feature existing**.

### Food library facts (seed data)

Reef Nutrition Oyster-Feast 1–200 µm (refrigerate 1–5 °C, 9-mo unopened); Phyto-Feast/Roti-Feast/R.O.E./Arcti-Pods same handling, never freeze; Coral Frenzy 50–300 µm; Reef-Roids ~150–200 µm (mix-fresh, clogs 1.1 mm doser fittings — large-bore only); Fauna Marin Ultra Sea Fan (the gorgonian-specific feed); NYOS GoldPods **shelf-stable** (easiest automation target); live phyto Nanno 1–2 µm / Iso ~5 µm / Tetraselmis ~10 µm; rotifers 150–300 µm; Artemia nauplii ~450 µm; Tisbe/Apocyclops nauplii. Carbon dosing (vinegar/NoPox) + Dr Tim's Waste-Away double as **bacterioplankton generators** — export mechanism that is also food.

## 4. What already exists in the codebase (from the mapping agents)

Almost everything below the orchestration layer:

- **AWC** (`awc.py` + `__init__.py`): volume-primary calibrated pumps, micro-change interval scheduling (15 min cadence floor), N-source fill (`fill2`/`fresh2` + `sourcePolicy` single/primary/alternate/ratio), per-source `saltPpt` with `source_salt_matched` gating (salt-matched micro-changes skip ATO/dosing suspends), net-salt ledger, layered guards, anomaly abort, drift grading. **Limit**: `plan_leg` is strictly symmetric — no "drain X, fill Y" today. Extension point identified: a new pure planner beside `plan_leg` taking per-role targets; the leg executor already handles per-role `movedMl`/`endsAt` maps ("modest surgery").
- **Dosing** (`dosing.py`): channels are dynamic dicts (cap `DOSING_MAX_CHANNELS = 8` — one constant + one slice to raise), stepper + brushed drivers, daily-total→micro-dose compiler, guard chain, **`channel.reservoir` already is a bottle** (`volumeMl`, `remainingMl`, `lowThresholdMl`, `daysUntilEmpty` runway, `mixedAt + shelfLifeDays` freshness with fail-closed stale gating), **dose-event-driven decrement already end-to-end** (sensor-delta accounting → hourly flush). Spacing engine exempts group-less chemicals — correct default for food. `livefood` chemical exists with 1-day shelf life + chaser rinse that already cross-debits the AWC fresh reservoir (the pattern for cross-ledger accounting).
- **Consumption Advisor**: product library with strength metadata (no bottle sizes — the gap this feature fills), trend-slope analysis, suggest/apply to pump cards. The analysis pattern to clone for the nutrient budget.
- **Feature-tab recipe** (per the panel map): `const.py` defaults + normaliser section + `websocket_nps_*` handlers + registration, `nps.py` pure-math module like `spawning.py`, panel tab array entry + route + state slot + field-handler scope + click actions; scheduler re-arm in `_async_save_config`/`async_setup_entry`. Modes: `_async_apply_mode(hass, entry, "feed", ctx)` is the sanctioned programmatic feed-mode entry; feature hooks live in the 7968–8033 block. Maintenance engine hosts custom tasks (hatch reminders free). Feed-watch camera capture already starts on feed mode. Pulse insight cards are one try-block each; diagram states are CSS classes.
- **Firmware**: dosingnode-s3zero (pumps-only node) + reefnode-s3 references; suffix tables currently allow ~1 brushed food head per node — **manual per-role entity binding already works for any entity set**, so unlimited pumps is a UI/normaliser change now and a suffix-parameterization contract bump later (hardware track).

## 5. The design — "Automated NPS System" tab

**Identity**: opt-in gated tab (`nps.enabled` splice-gate like dosing/vision). Label: **"NPS"** (tab), "Automated NPS System" (feature name, settings header, marketing). The page is a *command center* — the underlying engines (AWC, dosing, modes, maintenance, camera) stay authoritative; NPS compiles plans onto them and reads their state back. No duplicated state, one new `nps.py` pure-math engine, `config["nps"]` block.

### 5.1 Page layout (four zones)

1. **Feed Plan** (hero): today's feeding timeline — every scheduled event across all food pumps + brine exchanges + AWC slots on one 24 h strip, night window shaded, next event countdown. Plain-language honesty line (`schedule_text` tradition): *"14 feed events today: phyto every 90 min (0.8 ml), brine exchange 22:00 (drain 400 ml → dose 400 ml), AWC 2×1.2 L."*
2. **Food pumps**: unlimited channels, add-a-pump flow with product picker; per-pump card = next dose, bottle runway, freshness state, calibration/tube nags (reused dosing cards, food-filtered).
3. **Live brine / hatchery**: hatch-age clock with nutritional-prime countdown, "Hatched & loaded" button (stamps `mixedAt`), reservoir level, next brine-exchange event, reminders status.
4. **Water & nutrients**: the AWC amount control (canonical, edit-in-place), feed-load vs export budget bar, NO3/PO4 trend sparkline with the 2–20 / 0.01–0.1 guardrail band ("never zero" warning included).

### 5.2 Food pumps — unlimited, both hardware classes

- New chemical **`"food"`** in `DOSING_CHANNEL_CHEMICALS` (+ labels + panel selects); `livefood` stays for live/perishable (freshness fail-closed + chaser); `food` gets optional `shelfLifeDays` (0 = shelf-stable) by un-gating the existing freshness engine from livefood-only.
- Raise `DOSING_MAX_CHANNELS` 8 → 32 (and the slice at `__init__.py:696`). Spacing exemption already correct (`spacing_group("") `).
- **New driver `"ha_switch_timed"`**: generic HA switch + `mlPerS` calibration (AWC-pump-style timed runs, `runtime_for_volume_s` math) for Kamoer/DIY heads — the promised generic adapter. Reefnode channels keep the full sensor-verified path; ha_switch channels get dead-reckoned decrement (documented honestly on the card: "estimated — no dose sensor").
- Presets: "Phyto", "Zooplankton blend", "Bacteria", "Live brine" one-tap buttons seeding sensible schedules (phyto = many micro-pulses; blend = fewer larger; brine = exchange-coupled, §5.4).

### 5.3 Consumables engine (system-wide) — `config["consumables"]`

- Product registry: `{id, name, brand, category (phyto|zooLive|zooPrepared|blend|bacteria|amino|trace|twoPart|other), bottleMl, remainingMl, openedAt, shelfLifeDaysOpened, refrigerated, stirDaily, particleUmMin/Max, notes}`.
- Seeded library from research (§3 food facts) with per-product handling metadata; fully user-editable + "custom product".
- **Bridge**: `channel.reservoir.productId`. Two modes per channel: *bottle-is-reservoir* (dose decrements bottle directly via the existing pending-flush path) or *refill-from-bottle* ("Refilled 250 ml from Phyto #2" decrements the bottle, resets the reservoir — one WS command, mirrors `dosing_reset_reservoir`).
- Surfaces: NPS food shelf (bottles with % bars, days-left forecast from average daily use, low/expiry chips); dosing tab reuses the same rows for 2-part/trace; maintenance-style notification on low ("~6 days of phyto left") — reorder nudges.
- Days-left math reuses `reservoir_state` runway; expiry reuses `freshness_state` (both already generalized).

### 5.4 The brine feed-exchange (the signature mechanic)

"Drain X ml → dose Y ml salinity-matched live brine", as a first-class AWC cycle type:

- New pure planner `feed_exchange_plan(drain_ml, fill_role, fill_ml)` in `awc.py` beside `plan_leg` — asymmetric per-role targets, executed by the existing leg machinery (per-role `movedMl`/`endsAt` already support it). Runs under `_awc_lock`, full `start_guard_reasons` + `in_run_safety`, anomaly verdicts, ledger + `perSource` + `netSaltGrams` accounting (a drain-side twin of the chaser-credit hook).
- Source = `fresh2`-style reservoir with `saltPpt` set; `source_salt_matched` gate means matched brine exchanges ride the **micro-change path** (no ATO suspend churn at high cadence). The brine reservoir is a `consumables` product too (live BBS, shelf life 1–2 days, fail-closed stale → exchange blocked, reminder fired).
- **Net-export dial**: `drain = dose × (1 + exportBias)` — drain slightly more than you dose and every feeding *is* a little water change. This is the feeding↔AWC coupling nobody has.
- Scheduling: NPS-owned slots (e.g. nightly 22:00, or N×/day) compiled onto the AWC scheduler's due-slot machinery; roadmap note for per-slot source pinning (`sourcePolicy` "pinned" mode) which the AWC map identified as the natural insertion point.
- v2 (hardware track): auto-hatchery ESPHome node (heater + air valve + drain servo) slots in as a new driver on the same config — v1 config shapes chosen to survive that.

### 5.5 AWC amount on the NPS page

Canonical edit-in-place (tank-volume pattern — no forked state): read `awc_summary` (daily/weekly litres, scheduleText, runway), write `schedule.amount` via `awc_set_schedule`. Verified safe: amount-only edits deliberately don't re-arm the scheduler or consume pending slots. The NPS page shows it as *"Water exchange: 8%/week (staying)"* with the nutrient-budget suggestion beside it (§5.7).

### 5.6 Feed-event orchestration (the "system" part)

Per feed event, optional orchestration profile:

1. Enter Feed mode via `_async_apply_mode` (return pump off / wavemakers low per existing mode preview config) — the wall/Pulse mode chip shows it, feed-watch camera capture starts for free.
2. **Equipment truce**: new `interlocks` keys — skimmer off during + `skimmerResumeMinutes` (then a "wet-skim after feeds" advisory), UV off during + `uvResumeMinutes` (hours-scale for live food), ozone same. Needs a `uv`/`ozone` equipment-profile alias (one-line additions to `_normalise_equipment_profile`). All driven through `_armed_equipment_by_profile` — armed-only, never-raise, same discipline as AWC's kill paths.
3. Dose (single pump, group, or brine exchange).
4. Hold 10–30 min (food-soup window), staged resume: wavemakers → return → skimmer (+delay) → UV (+hours).
5. Exit to Running (restores `returnPlan`).

Micro-doses (phyto drip) skip orchestration entirely — truce is for pulse feeds. Per-event flag in the plan.

### 5.7 Nutrient budget (the intelligence leapfrog)

- Every dose event accrues a **feed-load ledger**: per-product rough N/P/organics densities (per-category defaults, user-tunable — honest "rough model" framing, consistent with AWC's honest-dilution stance).
- Budget bar: daily feed input vs export capacity (AWC removal % via existing dilution math + skimmer/carbon as unquantified credits).
- Closed loop with health trends (Consumption Advisor pattern): NO3/PO4 slope → *"Feeding adds ~X/day; nitrate rising 0.4 ppm/day. Suggest AWC 6→9%/week or −15% zooplankton."* One-tap **Apply** writes `schedule.amount` — the same suggest/apply UX as the dosing advisor.
- Guardrails both directions: NO3 < 2 / PO4 < 0.01 fires *"too clean for NPS — corals and the bacterioplankton loop starve"*; runaway high fires export suggestions. Advisory-only (memory: advisor features never auto-dose).

### 5.8 Species-based feed plans (zero prior art anywhere)

`nps.py` species library (research §3 distilled: per-group foods, particle windows, cadence, day/night, flow notes, difficulty) + **plan compiler** (spawning.py precedent — reef-location → Apex program is the same shape):

- User picks livestock ("2× Tubastraea, 3 gorgonians, 1 Dendronephthya") → compiler unions requirements → proposes: per-pump schedules (which product, ml/day, pulse windows, night bias), brine-exchange cadence, standing-phyto density mode if carnations present, suggested AWC scaling, truce windows.
- **Particle-size matching**: products carry µm ranges, species carry capture windows — the compiler warns *"Swiftia can't capture mysis-size particles; add a rotifer/Calanus-class food"*. Cheap to build, reads like magic, directly prevents the #1 failure mode (wrong particle = invisible starvation).
- Difficulty honesty: picking Dendronephthya/crinoids shows the real husbandry banner (survival stats, continuous-feeding requirement) — credibility with exactly the audience that knows how hard this is.

### 5.9 Hatchery & reminders

- Custom `maintenance.tasks` entries (evaluation/snooze/notify/history free): "Start brine hatch" (offset ~24 h before the exchange window), "Harvest + rinse + load reservoir", "Stir/agitate phyto" (daily, unless `stirDaily` product is on a stirrer switch — then it's automated), "Clean food lines" (cadence computed from doses/day per the WARF data: ~6 wks at 12/day), "Replace food-pump tubing" (existing wear odometers).
- Hatchery card shows hatch age vs the 24 h nutritional-prime window (calories −30–50% by 48 h) — a countdown that makes freshness visceral.
- v2: enrichment stage (second 24 h SELCO step) as an optional task chain.

### 5.10 Reef Pulse / diagram / personality

- **Insight card** (one try-block): next feed event, bottles low, hatch freshness, budget verdict.
- **Living diagram**: `dg-nps-feeding` state — a drifting plankton-cloud shimmer in the display during feed events + a food-pump station node with badge (same patch pattern as the AWC station). On the wall, the tank visibly "gets fed".
- **Feed-watch clips** already capture feed mode; NPS events tag their clips → the feeding journal writes itself.
- Personality (calm states only, Cheeky/Pro toggle respected): *"14 course tasting menu served today. Your gorgonians tip well."* Never on safety copy.

### 5.11 Safety posture (unchanged philosophy)

All water motion stays behind the AWC guard chain (leak/high-level fail-closed, anomaly 2×/3×, single-change cap, quiet hours). Food dosing stays behind the dosing guard chain (stale-food fail-closed OFF, daily caps, reservoir-empty). New surface is small: truce timers must **always** restore equipment (max-off timers pattern already exists in modes), and stale brine blocks the exchange but never blocks the plain AWC schedule.

## 6. Really cool suggestions (ranked)

**Tier 1 — in the v1 arc, cheap relative to wow:**
1. **Feed-load-matched AWC + net-export dial** (§5.4/5.7) — the genuinely-first thing; lead marketing with it.
2. **Species plan compiler with particle-size matching** (§5.8) — no prior art, prevents the #1 killer, demo gold.
3. **Sun-coral day-training program**: automates the documented technique — anchor the feed event post-lights-out, then auto-shift it earlier by ~10 min/week toward your chosen showtime; progress shown on the card ("week 4 of 8: feeding at 6:40 pm"). Trivial scheduler math, unique feature, *visible* payoff: sun corals open for the evening viewing window.
4. **Hatchery cockpit with nutritional-prime countdown** (§5.9).
5. **Equipment truce windows** (UV/ozone/skimmer feed-aware pausing with staged resume) (§5.6).

**Tier 2 — fast follows:**
6. **Standing-density phyto mode**: target cells/mL (5k–50k carnation band) + bottle cell-density → computed ml/day drip; "slight green tint is correct" coaching. The only proven Dendronephthya method, as a mode.
7. **Feed-before-export sequencing**: order the daily AWC slot right after the main feed window so uneaten food exports (documented best practice, pure scheduling).
8. **Polyp Watch** (camera): before/after frames per feed event scored for polyp extension (vision.py) → Polyp Response Index per colony; over weeks: **food A/B ranking** ("your Dendro responds 3× better to live phyto than blend"). Extends feed-watch; the moment it works it's the best reef-camera feature anywhere.
9. **Line-hygiene tracker**: dose-count-driven clean reminders + one-tap "flush now" (chaser burst) + NaOH clean log.
10. **Stirrer/fridge automation**: bind a magnetic-stirrer switch per product (`stirDaily` → scheduled agitation), optional fridge temp sensor with "food fridge warm" alert.

**Tier 3 — the moat compounds:**
11. **Bacterioplankton loop tracking**: carbon-dosing channel tagged as export-that-is-also-food in the budget.
12. **Trust Moat tie-in**: every automated feed logged + camera-verified = a provable care history for livestock sales/insurance ("this Dendro received 4,380 documented feedings").
13. **Feeding analytics**: heatmap of feeds vs polyp extension vs nutrient trend — the dataset nobody has ever had, publishable.
14. **Auto-hatchery hardware** (hardware track): ESPHome hatch node closing the last manual loop.
15. **Community plan sharing**: export/import species feed plans — the Rich-Ross-guide model, for feeding.

## 6b. Sun-coral day-trainer — design brief (2026-08-13, research-backed) · **STATUS: SHELVED 2026-08-13** (Reece: too much work for now; NPS page polish takes priority. Design + research preserved here — build-ready when wanted.)

**Who it's for first**: Reece's beta tester's two new sun corals — the heaviest test case. Locked decisions: both pump paths (fully functional hand-feed-only; a pump enriches), colonies link to `livestock.corals`, response logging lives on the NPS trainer card, full choreography v1.

**Research verdicts that shape the design** (dedicated sweep, sources in the research log):
- The mechanism is *consistency of feed time* — anticipation appears in ~2 weeks at any fixed time. Nobody in the hobby quantifies the shift step; the universal rule is "shift once it's reliably opening at the current time" — an **advance criterion, not a calendar**. Our criterion-based engine is the novel IP; **no training automation exists anywhere**.
- Scent → extension latency is consistently **5–30 min (median ~15)**. Scent cues that aren't followed by food are a real harm (extension costs energy; unrewarded cues extinguish the response) — **never fire an unrewarded cue** is a hard rule, enforced structurally.
- **Missed feeds are the #1 documented failure** (training lapses long before health does — a healthy colony shrugs off 10 unfed days). Colony moves / flow / lighting changes cause relapse; keepers recover by retreating to the last reliable time.
- Keep a **supplementary after-dark safety feed** throughout training (Tidal Gardens' hedge) — a failed daytime session is then harmless. Training is optional; eating is not.
- Honest promise: **"opens for daytime feeding," not "open all day."** Mid-photoperiod arrives in ~6–10 weeks; open-most-of-day is a months-scale, heavy-feeding, new-polyp-growth outcome. 10–30% of colonies (black micranthus especially) plateau at feed-time-only — the copy calls that success, because it is.
- Stubborn-colony tip worth surfacing: the inverted-bottle isolation technique gets first extensions when weeks of open-water attempts fail.

**The engine** (pure math, `nps.py`): one state machine, no phase enum — session time starts at *lights-out + 30 min* (anchored to the lighting schedule; manual fallback), advances **20 min earlier** (config 15–30) only after **3 consecutive Open responses**, retreats **2 steps** after **2 consecutive Closed**, toward the keeper's chosen showtime. Open increments the advance streak; Partial holds (resets the fail streak, no credit); Closed increments the fail streak; Skipped touches nothing (the coral wasn't cued) but a >5-day gap advises a retreat. `lastReliableMinutes` (time of the last completed streak) is the retreat target for the **"colony moved / flow changed"** button. The settle-in gate for brand-new corals falls out organically: the first advance needs the same 3-streak, which a new colony takes ~2 weeks to build.

**Two colonies, one clock**: colonies are `livestock.corals` entries (suncoral species); each session logs a per-colony response (with "same for both" as one tap); the clock advances only when **every** colony hits the streak — train to the slower coral, because they share the water and abandoning the laggard is how you lose it.

**Session choreography**:
- *Hand-feed mode (hers, day one)*: notification at the training time → she taps **Start session** on the trainer card → card walks the ritual: scent step (pump fires `scentMl` through the bound food channel, or "add a few drops of thaw juice" instruction) → **15-min countdown** (the extension latency) → "Feed now" → she target-feeds → one-tap Open/Partial/Closed per colony. No tap within the window = Skipped, cue never fired, nothing unrewarded.
- *Pump-fed unattended mode*: scent dose → 15 min → main dose, guard-checked as one unit (if the main dose would be blocked — stale food, caps — the scent is skipped too). Unattended sessions **maintain** consistency but can't **advance** the clock: progression requires logged evidence. (Camera auto-scoring is the v2 that closes this loop — the response log carries `source: manual|camera` from day one.)
- Composes with what exists: a scent/feed dose on a food channel already engages the **feed truce** (skimmer stops stripping the scent); optional feed-mode entry for the hand-feed window; optional per-session camera capture.
- **Night safety feed** (default on): reminder or scheduled dose after lights-out until the keeper tapers it — surfaced on the card with taper advice once the target is reached and stable.

**The card**: today's session time with countdown, a progress strip from anchor to showtime ("40 minutes conquered, 50 to go"), per-colony streak chips, the session-history journal (date × time × response — the screenshot-worthy chart), pause/hold, the moved-colony retreat button, and expectation-honest copy including the plateau-is-success framing and the bottle trick for stubborn colonies.

**Config sketch**: `nps.trainer = {enabled, colonies[], anchorMode: lightsOut|manual, manualAnchor, anchorOffsetMin: 30, targetTime, stepMinutes: 20, advanceAfterOpens: 3, retreatAfterClosed: 2, retreatSteps: 2, scentChannelId, scentMl, mainChannelId, mainMl, openDelayMin: 15, nightSafetyFeed, enterFeedMode, captureSession, state: {currentMinutes, lastReliableMinutes, startedAt, paused, colonies:{id:{streakOpen, streakClosed}}, sessions[≤60], sessionActive}}`.

## 7. Staged build plan

- **Stage A — foundation**: `config["nps"]` + normaliser + `nps.py` + gated tab skeleton; `food` chemical + channel cap raise + presets; consumables engine + product library + bottle runway; AWC amount card (read/write canonical). *Ships visible value alone.*
- **Stage B — brine exchange**: `feed_exchange_plan` asymmetric planner + executor wiring + ledger/salt accounting; brine reservoir freshness; hatchery card + maintenance reminders; net-export dial.
- **Stage C — orchestration**: feed-event truce (interlock keys + uv/ozone profiles + staged resume), feed-mode coupling, `ha_switch_timed` driver.
- **Stage D — intelligence**: feed-load ledger + budget bar + trend-coupled suggestions; species library + plan compiler + particle matching; sun-coral trainer.
- **Stage E — presence**: Pulse insight card, diagram plankton cloud + station node, feed-clip tagging, personality copy, docs/manual page.
- **Hardware track (parallel)**: firmware suffix parameterization for multi-food-head nodes; auto-hatchery node design.

Tests per harness: `tests/test_nps.py` (fake-HA WS + engine + guard chains) and `tests/test_panel_nps.mjs`; the brine-exchange planner gets the `test_awc_safety.py` treatment. Lockstep rule applies to any due-evaluation shown in the panel.

## 8. Open questions for Reece

1. Tab naming: "NPS" vs "Feeding" vs a branded name? (Everything above assumes "NPS".)
2. Channel cap: 32 acceptable, or truly uncapped?
3. Nutrient-budget suggestions: advisory-with-Apply only (assumed, consistent with the advisor), or ever auto-adjust AWC within a user-set band?
4. v1 hardware reality check: how many physical food heads on your bench today? (Shapes how hard Stage C's generic driver needs to push vs manual binding.)

---

## 9. Hatchery v2 — design brief (2026-08-16) · STATUS: brainstorm, awaiting Reece's answers

The hatchery is the screen Reece touches every single day — v2 turns the v1 clock
into a small production system: real volumes, multiple vessels, a brine ledger,
and advice that learns. Everything stays advisory (recommend, never act).

### 9.1 The model (v2 config shape)

```
nps.hatchery: {
  eggType, hatchHours,            # defaults seeded into each new start (unchanged)
  vessels: {                      # NEW — up to N hatcheries, each its own clock
    v1: { name: "Hatchery 1", volumeL: 1.0,
          state: { hatchStartedAt, eggType, hatchHours } },   # per-BATCH stamps
    ...
  },
  reservoir: {                    # NEW — the brine dosing container, hand-dose path
    volumeMl, remainingMl, loadVolumeMl,   # pump users: channel reservoir stays canonical
  },
  history: [ { vesselId, startedAt, harvestedAt, plannedHours, actualHours, eggType } ],
}
```

- **Per-batch stamps fix a v1 flaw**: changing egg type / hours mid-hatch currently
  rewrites a running countdown. v2 stamps `eggType` + `hatchHours` into the vessel
  state at start; settings changes only affect the NEXT batch.
- Back-compat: v1's single `state.hatchStartedAt` migrates to `vessels.v1`.
- The reservoir mirrors the dosing-channel reservoir schema so `_nps_brine_supply`
  reads either source with one shape.

### 9.2 Sizes and the brine ledger

- **Hatchery volume** (per vessel): drives the cyst-dose guide (density g/L from
  research §9.6) and the yield estimate on the card.
- **Dosing-container volume**: pump users already have `channel.reservoir.volumeMl`;
  hand-dosers get `hatchery.reservoir`. Both feed the depletion half of
  `next_hatch_suggestion` (v1 passes None for hand-dosers — v2 closes that).
- **"Hatched & loaded" moves volume**: adds `loadVolumeMl` to the container's
  `remainingMl` (clamped at `volumeMl`, with an overflow warning). Default for
  `loadVolumeMl` is Reece's open question §9.7-Q1 — hatchery volume vs top-to-full
  vs fixed amount. Never dose hatch water stays doctrine: the loaded volume is the
  RESUSPENSION volume, whatever the answer.
- **Stale-first gate**: if the container still holds brine past its shelf life,
  the load flow leads with "Discard the old brine first" (zero it, then load).
  Mixing fresh into old (non-stale) keeps the OLDEST mixedAt — the freshness clock
  never resets on a top-up (fail-closed; mirrors the expiry doctrine).
- **Refrigerated toggle** on the container (research §9.6): default shelf life
  24 h at room temp, 48 h fridged — the freshness clock and next-hatch maths
  both read it.
- **Hand-feed ledger**: a one-tap "Fed X ml" action on the card debits the
  reservoir (default dose size configurable) → hand-dosers get depletion-aware
  next-hatch advice and an honest fill level in the visuals.

### 9.3 Multiple hatcheries (overlap made real)

- Up to N vessels (cap TBD — Q3), each with name, volume, own clock, own vessel SVG.
- `next_hatch_suggestion` v2: same ready-by maths, plus **which vessel** — the
  first idle one; if all are incubating, "all hatchers busy — next free ~T".
- Structural guidance: continuous supply needs `ceil((hatchHours + buffer) / shelfHours)`
  vessels — the card can say "with 36 h eggs and 24 h brine life you need 2
  hatcheries; you have 1" (the v1 overlap flag, now with a number).
- Reminders stay vessel-aware: "Start hatch (Hatchery 2)".

### 9.4 Ending a hatch early + learning

- **Harvest now** during incubation (single tap, honest activity log) — first
  major hatch is often well before the nominal clock (research §9.6).
- Every harvest appends to `history` (planned vs actual hours, egg type).
- **Learned hatch times** (Q6): rolling average of actual hours per egg type →
  advisory chip "your standard cysts run ~20 h — tighten the clock?" with Apply.
  Same advisory-with-Apply doctrine as the nutrient budget.
- Optional later: hatch quality rating (good/poor) → "this tin is fading" trend.

### 9.5 Visuals, notifications, presence

- **Hatchery strip**: all vessel SVGs side by side (name, %, status ring), the
  brine dosing container drawn at the right with the AWC-reservoir idiom (fill =
  remaining/volume, stroke = freshness colour), a brief vessel→container pour
  animation on load (and in the demo).
- **Hour-precise "hatch ready" push**: maintenance reminders fire on a daily
  tick — fine for chores, wrong for a 20-minute harvest window. v2 dispatches
  hatch-ready (and start-now) notifications from the minutely tick, same
  plumbing as AWC events.
- Pulse insight rotator gains hatch-ready / start-now lines.
- Diagram: hand-doser brine station in the main feeding-station is Q9 (defer?).

### 9.6 Research digest (agent sweep, 2026-08-16)

**Density & yield** (SRAC 702 Texas A&M; Salt Lake Brine Shrimp; Reed Mariculture):
1–3 g cysts/L typical, **2 g/L optimum** (>2 reduces hatch-out, 5 g/L hard ceiling —
foaming/O₂ crash). ~250k cysts/g; premium GSL 90% grade ≈ 220–235k nauplii/g,
cheap grades ≈ 50% hatch ≈ 125–150k/g. → *Card guide: "your 1 L hatcher wants
~2 g (≈ a level tsp) — ~450k nauplii at 90% grade."*

**Timing vs temperature** (SRAC 702; brineshrimp.com.au; PodDrop; INVE): at
27–28 °C first free swimmers ~16–18 h, **peak 20–24 h**, stragglers to ~30–36 h.
At ~21 °C → ~36 h; 20 °C → 36–48 h. Rule of thumb: **28→20 °C roughly doubles the
cycle**. → validates the temperature-advisory idea (Q7) with a concrete curve;
egg-type presets already bracket this (16/20/24/36 h).

**Early harvest is BEST practice, not a compromise** (Brine Shrimp Direct; SRAC
702; TFH): harvest at ~18 h catches instar I — smallest (~430 µm) and most
nutritious (body fat peaks in the first ~12 h post-hatch, down ~39% by end of
instar I). Trade-off: leaves the straggler 10–30% behind. → "Harvest now" copy
can honestly say *earlier = more nutritious*; learned-hours has a real target.

**Storing harvested nauplii** (BSD FAQ; SRAC 702; breeder forums): room temp —
instar II moult at ~8–12 h @28 °C, yolk largely burned by ~12 h. **Fridge ~4 °C:
metabolism nearly stops; 24 h conservative, 2–3 days survival; nutrition argues
24–48 h.** → reservoir gains a `refrigerated` toggle: default shelf life 24 h
un-fridged, 48 h fridged (sources disagree mildly; we take the middle).

**Enrichment** (INVE S.presso; SRAC 702): instar II can gut-load from ~8–12 h;
INVE window ≈ start at 22–25 h, 18–22 h duration. → stays a v3 optional chain.

**Vessel presets** (product → water volume): Ziss ZH-700 **0.7 L**, Ziss ZH-2000
**2 L** (note: no "ZH-1000" exists), Hobby Artemia Breeder **0.47 L**, JBL
ArtemioSet **~0.5 L**, inverted 2 L bottle rig **~1.5–1.8 L**, BSD flat dish
~0.5 L. → volume preset picker seeds these.

**Rotation practice** (Reefphyto; Reef2Reef; SimplyDiscus): the documented
standard for continuous supply is exactly **two vessels staggered 12–24 h** —
matches the `ceil(lead/shelf)` formula; cap of 4 vessels is generous.

**Prior art — the niche is EMPTY at hobby level.** Aquaculture-scale automation
exists (INVE SEP-Art AutoMag magnetic harvester; US Patent 12,433,261 full-auto
hatch-and-supply; a 1973 semi-automated 250M/day rig), and hobby "auto
hatcheries" (TOM Hatch'n Feeder, Reefing Art) are PASSIVE swim-out vessels —
zero scheduling, zero monitoring, zero electronics. **No hobby product or open
project does hatchery scheduling/monitoring** (start advice, temp-compensated
timing, rotation management). Claim available: *"the first hatchery scheduler
for home aquariums"* — wording stays clear of the industrial patents (we
schedule and advise; we don't robotically harvest).

### 9.7 Open questions for Reece (the grill) · **ANSWERED 2026-08-16 — decisions LOCKED**

> 1. loadVolumeMl per-setup, **default top-to-full**. 2. Stale-first is a **HARD
> GATE** (discard unlocks load). 3. **Cap 4 vessels, ONE global egg type**.
> 4. Hand-feed: **both** — one-tap "Fed X ml" AND scheduled hand-feed reminders.
> 5. Cyst tin: **later** (not v2). 6. Learned hatch times: **v2**. 7. Temperature
> link: **v2**. 8. Hour-precise hatch-ready push: **yes**. 9. Hand-doser brine
> station in the main diagram: **yes**.

1. **Load volume physics**: when you tap "Hatched & loaded", what actually lands
   in the container — top it up to FULL with fresh tank-salinity water, a fixed
   configurable volume, or literally the hatchery's volume? (You said hatchery
   volume — but the rinse-and-resuspend doctrine means hatch water never goes in,
   so the loaded volume is whatever you resuspend into. Proposal: per-setup
   `loadVolumeMl`, defaulted to top-to-full, editable.)
2. **Stale-first**: hard gate (must discard before load unlocks) or warn-and-allow?
   And mixing fresh into non-stale leftovers: allow with oldest-clock-wins, or block?
3. **How many hatcheries** do we cap at (2? 4?) — and per-vessel egg types, or one
   global egg type across all vessels?
4. **Hand-feed logging**: is one-tap "Fed 30 ml" (configurable default) enough, or
   do you want scheduled hand-feed reminders too?
5. **Cyst tin on the food shelf** (grams, grams-per-hatch debit at start, runway in
   "hatches left"): v2 or later? (Needs a units extension to consumables.)
6. **Learned hatch times** (advisory Apply from your actual harvests): v2 or later?
7. **Temperature link** (optional HA sensor per hatchery → expected-hours advisory,
   e.g. "room runs 22 °C — expect ~30 h, not 24"): v2 or later?
8. **Hatch-ready push at the right hour** (minutely dispatch): assume yes?
9. **Main diagram**: add a brine station for hand-dosers too, or hatchery-strip
   visuals only for now?

### 9.8 Staged build (once answers land)

- **H-A model**: vessels + migration, per-batch stamps, reservoir + sizes, early
  harvest, load ledger + stale gate, history. *(Engine + WS + normaliser + tests.)*
- **H-B brain**: multi-vessel `next_hatch_suggestion`, vessel-aware reminders,
  hour-precise hatch-ready push, structural "you need N hatcheries" line.
- **H-C presence**: hatchery strip + container visual, pour animation, demo stage,
  Pulse insights.
- **H-D options** (per grill): cyst inventory, learned hours, temperature advisory.

---

## 10. Enrichment chain — design brief (2026-08-16) · STATUS: **SHIPPED 0.7.63** (all §10.6 answers locked + built same day)

Instar II nauplii can gut-load — the enrichment stage turns "live food" into
"live food carrying exactly what you want in it". This slots between harvest
and load as an OPTIONAL stage in the batch lifecycle, riding everything the
hatchery v2 already has: per-batch clocks, the container ledger, the reminder
sync, the hour-precise push.

### 10.1 The batch lifecycle grows one stage

```
incubating ──harvest──▶ [enriching] ──rinse+load──▶ loaded (container)
                └───────── skip ─────────▶
```

- Per-batch: at harvest time the keeper chooses "Load now" (today's flow,
  unchanged) or "Harvest → enrich". Enriching batches get their own clock
  (enrichHours), their own countdown, and an "Enriched & loaded" completion
  that runs the same stale gate + volume move + history append (history gains
  `enrichedHours` + product).
- Enrichment config: `hatchery.enrichment { hours, productId (a SHELF bottle —
  doses debit it, runway forecasts it), doseMlPerL, splitDose (second dose at
  T+10 h, INVE-style, as an optional reminder) }`.
- The chain maths: when a batch is enriching (or enrichment is the standing
  mode), the next-start lead time becomes hatchHours + enrichHours + buffer —
  `next_hatch_suggestion` and `vessels_needed` both take the longer lead.
- Push: "enrichment done — rinse and load" fires from the minutely tick like
  hatch-ready, once per batch.
- Consumables tie-in: the enrichment bottle is a first-class shelf product
  (category exists already); each enrichment debits doseMlPerL × enrichment
  volume. SELCO presets land in the product library with handling facts.

### 10.2 Where does enrichment happen? (the load-bearing modelling question)

Option A — in the hatching cone: the vessel stays BUSY through enrichment
(idle-vessel picking + vessels_needed must count it). Option B — a separate
enrichment container: the cone frees up at harvest for the next batch; the
enrichment container is one more visual in the strip. Research (§10.6) says
which is common practice; Reece's answer (Q1) decides the model. B is more
honest for continuous supply — cones are the scarce resource.

### 10.3 Freshness impact — research-gated

Enrichment emulsions foul water and enriched nauplii may burn the boost within
hours; the enriched batch's shelf life (and whether the fridge rule changes)
comes straight from §10.6. Whatever the numbers, the honest rule stands: the
container's freshness clock uses the ENRICHED shelf life when the loaded batch
was enriched.

### 10.4 Species tie-in (light touch)

Species-library entries gain a `benefitsFromEnrichment` flag surfaced in the
coverage report ("your sun corals take instar II+ — enriched batches carry the
HUFAs instar I burns off"). Advisory line only, no plan changes.

### 10.5 Research digest (agent sweep, 2026-08-16)

**Why enrich** (SRAC 702; FAO Live Food Manual): GSL nauplii are essentially
DHA-free; enrichment restores ~17.7 mg/g DW DHA / ~50 mg/g total n-3 HUFA, and
DHA now outranks EPA in importance. **Coral evidence is THIN**: controlled
trials are fish/shrimp larvae; NPS guidance recommends enriched zooplankton on
nutritional theory. Honest copy rule: *"proven for larvae, recommended for NPS
corals"* — never claim proven coral benefit.

**When it pays** (SRAC; BSD): nauplii can't eat until instar II (~6–12 h
post-hatch, temp-dependent — sources disagree inside that band). Fed out
≤12 h = enrichment pointless AND unnecessary (instar I yolk is the peak).
Decision rule for the card: harvest early → load straight; holding past the
molt → enrich.

**Products + doses**: INVE S.presso 2 × 0.5 g/L at T0/T10, ≤400 nauplii/ml,
18–22 h; Easy DHA Selco 0.6 g/L ≥24 h; FAO emulsion 300 mg/L at T0 + T10–12;
Selcon (hobby) ~12 h soak, heavy aeration. Live phyto: **T-Iso (Isochrysis) is
the DHA source; Nannochloropsis is EPA-only and does NOT fix the DHA gap** —
preset warning required. Schizochytrium powder enriches DHA without emulsion
fouling. Hobby short protocol (~0.5 ml/L, 4–12 h) = partial gut-load; full
tissue incorporation needs the 18–24 h split-dose.

**Vessel practice** (SRAC; FAO; Reef2Reef): aquaculture standard = RINSE at
harvest, then a SEPARATE enrichment vessel (hatch water + emulsion = bacteria);
an in-cone variant exists but even SRAC prefers separate. Density 100–400/ml,
strong aeration (emulsions strip O₂, keep DO > 4 mg/L), 25–28 °C.

**Risks**: oil emulsions foul water/appendages and depress O₂; overdose =
cloudy water/surface scum (Selcon: "use less if the water does not clear");
enrichment media boost Vibrio. **The HUFA boost is transient: DHA falls to
under HALF within 24 h warm** (Evjemo 1997) and artemia retro-convert DHA→EPA.

**Storage after enrichment** (FAO; BSD): rinse on a 100–125 µm screen, then
<10 °C holds ≥24 h with <5% HUFA loss, usable 2–3 days. → **Freshness rule for
the scheduler: enriched batch at room temp = 12 h shelf; refrigerated = 48 h
(full value first 24 h).** The fridge toggle goes from nice-to-have to the
thing that makes enrichment worth doing at all.

**Prior art: none.** No app or product models an artemia enrichment stage,
dose or cold-storage clock. *"First hatchery scheduler with an enrichment
stage"* is safe wording.

**Defaults these numbers dictate**: separate-vessel flow as the default model
(Q1); presets = S.presso (split), Easy DHA Selco, Selcon, T-Iso phyto,
Schizochytrium powder, with the Nanno warning; hobby 12 h single-dose default
with optional T+10 h split reminder; enriched shelf life 12 h room / 48 h
fridge wired into the container freshness when the loaded batch was enriched.

### 10.6 Open questions for Reece (the grill) · **ANSWERED 2026-08-16 — decisions LOCKED**

> 1. **Separate enrichment vessel** (cone frees at harvest). 2. **Selcon** is
> the primary preset. 3. Shelf-bottle link **yes** (per-run debits). 4.
> **Per-batch choice** at harvest. 5. **Hobby single dose** default + optional
> split-dose extra. 6. Chain counts enrichment **only while a batch is actually
> enriching** (an enriching batch rides the chain as a pseudo-batch that loads
> at enrich-end; no standing lead change). 7. Enrichment-done push **yes**.
> 8. **Build now** (v0.7.63).

1. **Cone or separate container?** Do you enrich in the hatching cone (vessel
   stays busy) or decant into a separate enrichment vessel (cone freed for the
   next batch, one more visual in the strip)?
2. **What's your enrichment food** — SELCO-type emulsion, live phyto, both?
   (Decides the presets and whether doseMlPerL needs per-product defaults.)
3. **Shelf bottle link**: enrichment product as a tracked bottle on the food
   shelf with per-enrichment debits — yes?
4. **Per-batch choice or standing mode?** "Harvest → enrich" offered every
   harvest, or a global "always enrich" toggle (with per-batch skip)?
5. **Protocol depth**: hobby single-dose (~1 ml/L, one clock) as the default,
   with the INVE split-dose (T0 + T10) as an optional extra reminder — enough?
6. **Chain maths**: include enrichment lead time in next-hatch advice ALWAYS
   when the standing mode is on, or only while a batch is actually enriching?
7. **Enrichment-done push** from the minutely tick (like hatch-ready) — assume yes?
8. **Scope**: build this next (v2.1 of the hatchery), or park it documented?

### 10.7 Staged build (once answers land)

- **E-A**: batch stage model + enrichment config + WS (harvest→enrich,
  enriched&loaded) + shelf debits + history fields + engine lead-time change.
- **E-B**: strip visual (enriching state / enrichment container), split-dose
  reminder, enrichment-done push, freshness rule.
- **E-C**: species flag + coverage line + demo + docs.

---

## 11. The hatch-clock contract (0.7.79) — one number, four places

Reece's live catch: tapping **"Set clock to 34 h"** moved the headline number
and left the rest of the page quoting 24 h. It looked like a broken button; it
was actually a missing contract. The clock is not a setting — it is a number
four different things hang off, and they must move as one:

| # | Surface | Owner | Rule |
|---|---------|-------|------|
| 1 | `nps.hatchery.hatchHours` | config | the clock for the **next** batch |
| 2 | `vessels.<id>.state.hatchHours` | per-batch stamp | the countdown already running |
| 3 | `state.readyNotifiedAt` | per-batch stamp | the once-per-batch ready push |
| 4 | `maintenance.tasks.brine_hatch_*` `cadenceHours` + harvest `snoozedUntil` | maintenance | when the phone actually nags |

**The rule.** A *settings* edit touches (1) only — per-batch stamping exists so
a mid-hatch countdown is never rewritten under the keeper. Applying the
*learned* clock touches all four, because it is not a preference change: it is
a better measurement of the very process already under way. The exception is a
batch already `ready`/`overdue` — those nauplii have hatched, and no arithmetic
un-hatches them, so that batch keeps its own result.

**Where it lives.** `websocket_nps_hatch_clock` (backend-authoritative,
fetch-fresh). The panel must NOT do this with a whole-config save: the page's
`_config` is a snapshot, so saving it writes a stale ledger (reservoir
remaining-ml, history, notify stamps) back over whatever the tick has done
since the page loaded. `_nps_hatch_retime_reminders` stays LOCKSTEP with the
panel's `_npsSeedHatchReminders` cadence half, and only ever re-times reminders
the keeper already added — a clock change never conjures a reminder.

**Residual drift is now spoken, not hidden.** A vessel whose stamp disagrees
with the config says *"on its own 24 h clock"*; reminders whose cadence
disagrees say *"still run a 24 h cycle"* and offer the one-tap sync. The
failure mode this kills is a page that quietly contradicts itself and reads as
a broken button.
