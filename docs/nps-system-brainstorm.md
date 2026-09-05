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

### 10.3.1 CORRECTION (0.7.89) — "stale" was the wrong word, and one clock was the wrong model

Reece, live-testing 2026-08-28: *"the current hatchery will always show that the
current hatch is stale. What you are calling 'stale' is actually nutritionally
depleted — but if the container has been enriched, it is no longer nutritionally
depleted, it is now gut loaded."*

He is right, and the app was contradicting its own protocol. Trace it:

| t | what happens | what the card said |
|---|---|---|
| T+0 | harvest → load the container (`mixedAt`) | prime, ~24 h left |
| T+8 | molt to instar II — the batch grows a mouth, first dose | prime |
| T+20 | 12 h soak ends (`enrichedAt`) — the batch is GUT-LOADED | prime, ~4 h left |
| T+24 | — | **"past the 24 h prime window. Feed it out or hatch fresh."** |

The 24 h yolk window exists because UNFED nauplii burn their reserves down
(30–50% of calories by 48 h). Enrichment is the one thing that falsifies that
premise: the batch has eaten. Running a single clock meant the app condemned
every batch four hours after finishing the soak it had itself asked for — and
because §10.1's flow enriches IN the loaded container, the collision was
guaranteed, not occasional.

**Two clocks, not one.** Which one runs depends on whether the batch was fed:

- **Unenriched** → the yolk clock. `prime` for 24 h from the load, then
  `fading`. Unchanged, but now labelled as the yolk window and offering
  *enrich it* as a third way out.
- **Enriched** → the boost clock, counted from the END of the soak
  (`enrichedAt`), not from the load. `gutloaded` while it holds
  (`ENRICH_SHELF_H_ROOM` 12 h / `ENRICH_SHELF_H_FRIDGE` 48 h), then
  `boost_fading`. What ticks here is not starvation but retro-conversion —
  Evjemo 1997, DHA to under half within a day warm, <5% loss for 24 h+ under
  10 °C. The honest ending is *"still live food, no longer enriched food"*,
  never *"hatch fresh"*.

**The container shelf had the same bug.** `_enriched_shelf` computed
`min(plain_shelf, soak_offset + enriched_cap)` — so enrichment could only ever
SHORTEN the window, never survive past the yolk shelf that no longer applied.
The `min()` against the plain shelf is gone; the cap is now
`ENRICH_SHELF_MAX_H` (72 h) so a bad stamp cannot grant a week.

**Molt timing re-checked at the same time.** §10.5 puts instar II at "6–12 h
post-hatch, temperature-dependent". The default dose delay was **6 h** — the
early edge of a band whose whole point is that it moves. It is now
`INSTAR_II_HOURS = 8.0` at the 28 °C optimum, and `instar_two_delay_hours()`
rides the SAME temperature factor as the hatch clock (Reece's bench runs
26.4 °C, so his molt lands nearer 9 h). Advisory only, like every other
suggestion here: the card argues, the keeper decides.

**The rule that generalises:** a status word has to name the mechanism it
measures. "Stale" conflated three different things — yolk burn, HUFA
retro-conversion and water hygiene — and once they were conflated, no amount of
correct arithmetic could produce a true sentence.

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

### 11.1 Reachability (0.7.80) — the rule was right, the route was missing

0.7.79 made the *learned-clock chip* move all four surfaces. It was still
wrong, because the chip **retires itself** the moment the clock and the
history agree — so a batch stamped before the change had no route back at all.
Reece hit exactly that: clock 34 h, batch stamped 24 h, chip gone, three taps
and nothing to tap.

The rule is only as good as the routes into it:

- **Every route that changes the clock now carries the batch.** The settings
  field goes through `_nps_hatch_clock_follow` in `websocket_save_config`,
  in the same slot as `_merge_recent_completions` — old config vs incoming,
  clock changed, move the incubating batches.
- **A stranded batch has an explicit override.** `nps_hatch_clock` accepts no
  `hours` at all ("align onto the clock we already have") and an optional
  `vessel_id`. The tile's *"on its own 24 h clock"* note now carries a
  **Move to 34 h** button; the reminder-drift line carries **Bring them onto
  34 h**, which lands instantly rather than arming the Save bar.
- **Egg type gates the sweeping case only.** A 36 h standard batch is not an
  18 h decapsulated one because the default moved — so a sweep skips a batch
  on a different egg type, and naming the vessel overrides that.

**Design lesson worth keeping:** an advisory chip that retires on success is a
fine affordance and a terrible *only* affordance. Any state the system can
describe ("this batch is on a different clock") needs an action attached to
the description itself, not to the transient control that created the state.


## 12. Hatchery audit — the biology re-checked and the fridge made per batch (2026-09-01, 0.7.115)

Reece: "many changes have been made over time, I want to make sure
everything has kept up." Research refreshed first, then every constant and
advisory checked against it, then the fixes.

### 12.1 The research, refreshed

| Question | What the sources say | OpenReef | Verdict |
| --- | --- | --- | --- |
| Hatch time vs temperature | Optimum 25–28 °C; "some 24-h incubation" (FAO 361); 24–30 h at 24–30 °C, ~36 h at 21–24 °C, 36–48 h at 20 °C; SRAC 702 quotes 15–20 h at 25–28 °C for decapsulated cysts; below 25 °C markedly slower, above 33 °C lethal | `standard` 24 h, `decapsulated` 16 h, `premium` 20 h, `cool_room` 36 h; +8 %/°C below 28 °C, capped 2.2×; warm flag above 30 °C | **Holds.** Reece's own journal (36.3 h at 26 °C) runs longer than the rule of thumb — which is exactly why the learned clock exists. |
| Instar I → II (mouths open) | FAO 361: "after about 8 h the animal molts into the 2nd larval stage"; SRAC 702: "approximately 12 hours after hatch"; practice: harvest at 16 h + 6–8 h at room temp | `INSTAR_II_HOURS` 8 h at 28 °C, temperature-stretched, capped 24 h | **Holds.** 8 h at optimum is the FAO number; the stretch covers SRAC's 12 h on a cooler bench. |
| Unfed nauplii nutrition | ~20 % dry weight / ~27 % energy gone in the first 24 h warm (FAO 361, widely cited); 30–50 % of calories by 48 h; "feed as soon as possible after hatching" (SRAC) | `BRINE_PRIME_HOURS` 24 h, "fading" after | **Holds.** |
| Cold storage, unfed | Léger et al. 1983 ("International study on Artemia XXIV"): 2–4 °C, densities ≥2000/ml, viability very high after 48 h, dry weight and biochemistry unchanged for most strains | `BRINE_SHELF_H_FRIDGE` 48 h | **Holds** — but see 12.2: it was a switch, not a rate. |
| Enriched boost, warm | Evjemo 1997: DHA retro-converts to EPA during starvation; large loss within a day at 22 °C; low temperature (6 °C, 12 °C, 14 °C in later work) retains it | `ENRICH_SHELF_H_ROOM` 12 h | **Holds, conservative.** Feed the boost out within half a day warm. |
| Enriched boost, cold | Retention "≥24 h with <5 % loss" below 10 °C in the sources we had; Evjemo's 6 °C series flat over the period | `ENRICH_SHELF_H_FRIDGE` 48 h | **Holds.** |
| Enrichment duration | SRAC: ≥4 h; DHA protocols: 12–24 h, split dosing (INVE) tops up at ~10 h | 12 h default, split at 10 h, 2–36 h range | **Holds.** |

Sources: FAO Fisheries Technical Paper 361 (Lavens & Sorgeloos 1996), ch. 4;
SRAC Publication 702 (Artemia production for marine larval fish culture);
Léger, Sorgeloos et al. 1983, Aquacultural Engineering 2; Evjemo, Danielsen &
Olsen 1997, Aquaculture 155; Navarro et al. 1999 (fatty-acid changes in
enriched-then-starved A. franciscana); reefs.com Breeder's Net (instar II at
~12 h); algova.com hatching guides; Kumar et al. 2017 (Sci. Rep. 7:40394,
temperature × salinity hatching response).

### 12.2 What had NOT kept up

1. **The temperature advisory stretched the keeper's clock, not the rated
   hours.** `expected_hatch_hours(hatchHours, temp)` — and Reece had set the
   clock to 38 h from a learned average measured at this very temperature.
   The card said "expect ~43.7 h, not 38 h" about batches that ran 36.3 h.
   Now the stretch is on the egg type's RATED hours (24 h), and when a
   learned clock exists the line defers to it: "measured beats modelled".
   A clock already longer than the rule of thumb is left alone.
2. **The fridge was a global setting that rewrote history.** "Container
   lives in the fridge" granted 48 h to whatever was loaded — including a
   load that had already sat warm for 20 h — and the yolk prime window
   ignored it entirely (fixed 24 h), so a cold unfed batch read "fading"
   while the container beside it read fresh for another day.
3. **The next-hatch chain and vessels-needed planned on the current load's
   boost window.** An enriched container holding 34 h told the chain the
   NEXT batch (unfed at load) also had 34 h, and could say one hatchery was
   enough when the structural answer on 24 h is two.

### 12.3 The two-rate clock (`nps.brine_window_hours`)

A batch spends its window at the room rate until the moment it goes cold
and at the fridge rate from then on. Fridged at load: the full 48 h.
Fridged after 12 warm hours of a 24 h window: half the life left, spent
slowly — 12 + 24 = 36 h from load. Fridged once it is spent: nothing comes
back. Taking it out banks what the spell saved (`fridge_saved_on_exit`:
20 h cold on a 24/48 clock spends 10 warm-equivalent hours and banks 10),
so the credit survives the spell ending. The function returns hours FROM
LOAD, so it drops into every existing consumer — `freshness_state`,
`next_hatch_suggestion`, `vessels_needed`, the stale gate — unchanged.

Per-batch state on the reservoir: `refrigeratedAt` (when THIS load went
cold) and `fridgeSavedH` (banked credit). Both reset on every load and on
discard. Enrich-engage takes the load out (a soak is warm and aerated) and
banks the cold hours; soak-done resets both (the boost window starts warm
from the soak end). Refrigerating mid-soak is refused. Both fields joined
the stale-save guard.

### 12.4 The keeper's side

- **Inline, not a setting:** the "❄ Refrigerate" / "Take out of the fridge"
  button sits on the nutritional advice line it changes. The settings
  toggle is gone (legacy `refrigerated: true` migrates to a stamp at the
  window's start, so nobody's current load changes state on update).
- **Its own tile:** a refrigerated load draws as the bottle inside a fridge
  in the row with the cones and the soak, stroke from the freshness clock,
  "~N h of life left" underneath, Take out on the tile.
- **The hero Container card** says "❄ in the fridge, ~N h left".
- **The overlap heads-up** points at the button, not at Settings.

### 12.5 Left alone, on purpose

- The prime clock counts from the LOAD stamp. On a 38 h hatch the first
  nauplii out are ~14 h old at harvest; there is no honest way to know the
  mix, and every source dates the window from hatch-out, so the load stamp
  stays the anchor. The learned clock already tells the keeper to harvest
  early.
- `HATCH_OVERDUE_GRACE_H` 12 h and `ENRICH_OVERDUE_GRACE_H` 6 h stand.

### 12.6 The fridge is a separate feeding bottle (2026-09-02, 0.7.116)

Reece's actual practice, which 12.3–12.4 got wrong: the container is never
refrigerated. The brine is DRAINED out of the live-brine container into a
separate feeding bottle, and that bottle is what goes in the fridge. The
container is then empty and free for the next hatch.

So the model is now two vessels, each with its own batch and its own clock:

- **`hatchery.reservoir`** — the container. Never cold. It keeps
  `fridgeSavedH` only for the case where a bottle is poured back (the credit
  the cold spell banked). `refrigeratedAt` is gone from it.
- **`hatchery.fridgeBottle`** — `remainingMl`, `mixedAt`, `refrigeratedAt`,
  `lastLoadEnriched`, `enrichedAt`, `fridgeSavedH`. The same stamp shape as
  the container, so the one helper (`_nps_batch_shelf_hours`) runs the
  two-rate clock for both: the batch's window from ITS load, room rate
  until it went cold, fridge rate after, the boost window instead of the
  yolk window when enriched.

One command, `openreef/nps_fridge_bottle`, four actions:

- **fill** — the inline "❄ Refrigerate": moves the container's whole load
  into the bottle with its stamps, stamps `refrigeratedAt = now`, empties
  the container (and clears its enriched/credit stamps). Refused for stale
  brine (`stale_brine` — the fridge won't bring it back), mid-soak
  (`soaking`), or onto a bottle whose brine is already past its shelf
  (`bottle_stale` — empty it first). Topping up a bottle that still holds
  good brine is allowed: the OLDER batch's clock rules the mix.
- **feed** — a hand feed debited from the bottle (default dose, or `ml`),
  logging the hand-feed reminder done like the container's button.
- **return** — the bottle poured back into the container: the cold hours
  bank as credit (`fridge_saved_on_exit`), the volume clamps at the brim,
  and if the container already holds brine the older batch's clock rules.
- **empty** — discard.

Planning: `_nps_brine_supply_for_planning` feeds `next_hatch_suggestion`
the bottle as supply — whichever of container/bottle dies LATER anchors
the clock, the volume is both. The container's own freshness line and the
stale gate are unchanged (container only). Migration: a 0.7.115 container
stamp (or the older global toggle) on a loaded container moves that load
into the bottle on normalise; the bottle joined the stale-save guard whole.

Panel: the ❄ button stays inline on the advice line and only ever says
"Refrigerate" (the container is never "taken out"). The bottle draws as
its own tile beside the cones and the soak — "Feeding bottle · in the
fridge", ml, "~N h of life left" (or "past its shelf life — empty it"),
and three buttons: Fed N ml / Back in container / Empty. The hero
Container card carries "❄ bottle N ml, ~H h left".

Two things the sweep turned up: both test runners had their `main` block
mid-file, so every test added below it (the whole 0.7.115 fridge set, and
0.7.113's backflush test) had never actually run; they run now, at the
end. And the mixing vessel ledger rounded `estimatedLitres` to 1 dp on
every save, so 0.7.113's 0.75 L backflush was logged as 0.75 and stored as
0.8 — the ledger keeps 2 dp now.

### 12.7 The chain counts the brine on hand (2026-09-03, 0.7.118)

Reece's screen: Hatchery 1 at 25.9/38 h, container empty, an enriched
feeding bottle with 46 h left — and the page said "start the next hatch
now, before the loaded brine fades" beside "no hatch loaded yet".

The chain branch of `next_hatch_suggestion` ignored `loaded_iso` entirely:
with a batch running it planned only on that batch's load (+12.1 h, plain
24 h shelf, fades +37.1 h; a 38 h batch needs 39 h of runway → now). By
coincidence that was the right answer here — 500 ml fed at 250 ml twice a
day is gone by +24 h, before the incoming load fades — but the reasoning
skipped the bottle and the wording contradicted the tile beside it.

Now the deadline is the LATER of the incoming load fading and the supply
on hand giving out (its fade or its depletion at the feed rate — the same
rule the no-running branch always used). `driver` says which: `chain`
(the incoming harvest — `chainVessel` names it), `freshness` or
`depletion` (the supply on hand, which the panel calls the feeding bottle
when the container is empty). The prime line, when the container is empty
and the bottle holds brine, says so instead of "no hatch loaded yet".

## 13. Feed timeline v2 — the unified day strip (2026-09-05) · STATUS: **RELEASED 0.7.130–0.7.135 (2026-09-05)** — see §13.10–§13.15

### 13.1 What v1 is, honestly

`_npsTimelineSvg()` draws a 24 h strip from exactly three sources: food-pump channel schedules (doses spread evenly across the window, or a band for continuous), AWC slots (times or an interval band), and the lighting window for night shading. One "Next:" line underneath. It never reads the shelf's hand-dose plans, the brine container's hand feeds, or the dose history — so a hand-feeder sees "Nothing scheduled" even with five bottles and a due dose (the screenshot: shelf says *1 dose due*, strip says nothing). Events are planned-only: nothing on the strip ever turns into "done".

### 13.2 The idea in one line

**One strip, every mouthful.** Every food that goes into the tank today — pumped or poured — sits on the same 24 h line, planned events as outlines that fill in when they happen, with the pump/hand distinction readable at a glance and a tap opening the full story of that dose.

### 13.3 The event model (backend-authoritative, one pure function)

`nps.feed_timeline(config, now, tank_l, lighting)` → `{date, events[], lanes[], next[], night, honesty}` folded into `nps_summary` as `timeline` (no new WS to forget — the 0.7.129 lesson). Panel renders; never re-derives.

One event shape for everything:

| field | values | notes |
|---|---|---|
| `at` | minute-of-day, or `null` | `null` = "any time today" (a hand plan with no preferred time) — shown as a floating chip, never faked to a time |
| `how` | `pump` · `hand` · `system` | the load-bearing distinction; `system` = AWC slot / matched drain / truce window |
| `source` | `channel:<id>` · `shelf:<pid>` · `hatchery` · `awc` · `culture:<id>` | where it came from → where the tap links |
| `productId` | shelf bottle if any | colour + bottle % + expiry for the popover |
| `ml` | planned or actual | continuous mode carries `mlPerDay` + `band: [start,end]` instead |
| `status` | `planned` · `due` · `done` · `late` · `missed` · `skipped` · `blocked` | see 13.5 |
| `doneAt` | actual minute when logged / run stamp | from `history` (`dose`/`pump` kinds), hatchery feeds, HA-switch run stamps |
| `note` | one plain sentence | "banks 210 ml of owed drain", "UV pauses 20 min", "guide dose for 300 L, medium stocking" |

**Sources swept, per day:**

1. **Pump channels** (as now) — plus reefnode/HA-switch run stamps matched to the nearest planned slot → `done`. Firmware owns the exact clock, so planned ticks stay "approximate by design"; actuals are exact.
2. **Brine feed-exchange** doses (the fx channel) — each carries the chaser + owed-drain note.
3. **Shelf hand-dose plans** — `doseMl`, `doseEveryDays` **or** `doseEveryHours`, `doseFirstAt`, `lastDosedAt` (13.4). On an off-day of a multi-day cadence the bottle still shows as a **faint ghost** at its anchor time, `status: ghost`, popover says "next Thursday" (Q7 — informative, revisit if it's noise).
4. **Hand-fed brine container** — the hatchery's "Fed 250 ml" events (done) and, if the keeper sets one, a feed cadence for the container (planned).
5. **Dose history** — every `dose`/`pump` history entry stamped today that matched no plan → an *unplanned* done dot ("extra 5 ml Reef Juice, 14:12"). The strip shows what actually happened, not just what was meant to.
6. **AWC slots / matched drains / truce windows** — `system` lane, visually quiet (thin bands, no colour fight with food).
7. **Cultures harvest → tank** — **counts, 100 %** (Q6). A harvest logged as fed to the tank is a `hand` done event (`source: culture:<id>`); a culture with a harvest cadence lands planned slots the same way a bottle does. Feeding the *culture* its phyto is not a tank event and stays off the strip.

### 13.4 Hand plans get a clock face — cadence decides the slots (LOCKED, Q1)

Today a hand plan is "X ml every N days" and the due clock is `lastDosedAt + N days` — correct for the reminder, useless for a timeline. Reece's call: **the cadence is the product's**, so the shelf editor gains a second cadence unit rather than a per-bottle list of times:

- `doseEvery: {n, unit: "days" | "hours"}` — stored as the existing `doseEveryDays` **or** a new `doseEveryHours` (mutually exclusive; the editor is one number + a days/hours toggle). Reef Juice = every 1 day; a phyto or rotifer bottle for a Dendro tank = every 6 hours.
- `doseFirstAt: "HH:MM"` — one anchor time per bottle (default **08:00**, editable). That is the only time the keeper ever types.
- **Slots per day** derive from the cadence: hours → `floor(24 / n)` slots at `firstAt + k·n h` for `k = 0 …`, restarting at the anchor each day (every 5 h = 08:00, 13:00, 18:00, 23:00 — the label says *"×4 a day from 08:00"*; drift-across-midnight cadences are deliberately not modelled, keepers think in days). Days → one slot at `firstAt` on due days only.
- `doseFirstAt` unset → the old behaviour: one `at: null` "any time today" chip per due slot. Nothing is faked to a time.
- **Due clock stays in lockstep**: `hand_dose_state()` clock `at` = the next slot after `lastDosedAt` (hours cadence: `lastDosedAt + n h` snapped to the next anchored slot; days cadence: `lastDosedAt + n d` at `firstAt`). The shelf reminder, the shelf's "1 dose due" pill and the strip must all read the same function — the maintenance-evaluator rule.
- Save-diff: `doseEveryHours` + `doseFirstAt` join `doseMl`/`doseEveryDays` as keeper-edited fields; `lastDosedAt` stays server-written and guarded.

### 13.5 Status ladder and the visual language

Auto and hand must be distinguishable at arm's length on an iPad and on the Pulse wall, without reading a legend. Three cues, redundant on purpose:

| | pump (auto) | hand |
|---|---|---|
| **lane** | upper lane (labelled ⚙︎ pumps) | lower lane (labelled ✋ by hand) |
| **glyph** | vertical tick / pill, as v1 | circle |
| **fill** | planned = hollow, done = solid | planned = hollow, done = solid + small ✓ |
| **colour** | product/channel colour (unchanged) | product colour |

Status overlays (both lanes): `due` = pulsing ring (CSS animation, `prefers-reduced-motion` respected); `late` = amber ring, still hollow; `missed` = red-outlined hollow with a slash; `skipped` = grey hollow, dotted; `blocked` (guard chain refused a pump dose, or truce/AWC exclusion) = red solid with the reason in the popover. `system` lane stays the thin translucent bands of v1, below the axis.

Timing rules (defaults, tune in 13.8): `due` from slot time; `late` after 60 min; `missed` after a 3 h grace, or at midnight if `at: null` was never logged. A missed dose is a fact on the strip, not a nag — the notification story stays with the shelf reminder.

Layout: viewBox grows from 62 → ~110 tall (two lanes + system band + axis). Night shading spans all lanes. The now-line stays red. Left gutter carries the two lane labels; on phones (≤600 px) labels collapse to the ⚙︎/✋ glyphs only.

### 13.6 Tap → the dose card (popover on desktop, bottom sheet on phone)

Every event is a `data-action="timeline-event"` target carrying an event index (buttons MUST carry a class — mixing-station rule). The card:

- **Header**: product name + colour swatch, `how` badge ("Food pump 2 · reefnode" / "By hand"), status word.
- **The dose**: planned ml, actual ml if different, scheduled time vs done time, bottle % after and days-left runway, expiry status if aging/expired.
- **Consequences** (only when true): owed drain this dose banks; truce pause length; AWC exclusion; particle/species note from the plan compiler if the bottle is on a species plan.
- **Actions** by kind:
  - hand `planned/due/late/missed` → **Log this dose** (calls `consumable_log_dose` with the plan's ml; optional "dosed at" time picker, today-only, past-only, for a late log at its real time — writes `history.at`), **Skip today** (new: `consumable_skip_dose`, stamps `skippedOn: date`; keeps the runway honest because no ml moves), **Open bottle** (scrolls to the shelf card).
  - pump `planned` → **Dose now** (the existing manual-dose path with the full guard chain; refused reasons shown inline), **Open pump card**.
  - `done` → the log line, **Undo** only for hand doses logged in the last 10 min (reverses the debit and clears `lastDosedAt` back to the previous history entry — needs a test).
  - `system` → **Open Water Change**.

### 13.7 "Next" becomes a queue, and the honesty line

Under the strip, the next three events as chips with countdowns, mixed lanes: `✋ Reef Juice 3 ml · in 40 min` · `⚙︎ Phyto 0.8 ml · in 1 h 10` · `≋ Water change 1.2 L · 22:00`. Then the plain-English line in the `scheduleText` tradition: *"9 feeds today — 6 pumped (phyto every 90 min, brine 22:00), 3 by hand (Reef Juice 08:30 and 20:30, copepods any time). 1 missed so far."* Zero-state for a hand-feeder with plans but no times: *"3 hand doses due today — set a time on the bottle and they'll land on the strip."* Zero-state with nothing at all keeps the v1 line.

### 13.8 The grill — ANSWERED 2026-09-05, decisions LOCKED

| # | Question | Decision |
|---|---|---|
| 1 | Hand-plan times | **Cadence is the product's**: new `doseEveryHours` alongside `doseEveryDays` + one `doseFirstAt` anchor; slots derive from the cadence (13.4). No per-bottle time lists. |
| 2 | Missed grace | Reece unsure → **proposed default below**. |
| 3 | Late logging at the real time | **Allowed** — "dosed at" picker, today-only, past-only, writes `history.at`. |
| 4 | Unplanned doses on the strip | **Show** them as done dots. |
| 5 | Placement | NPS hero **+ (a) Feeding-tab header for zero-pump keepers + (b) slim Pulse-wall strip**. No Home card. |
| 6 | Cultures harvest → tank | **Counts, 100 %** as a feed. |
| 7 | Multi-day off-days | **Faint ghost** at the anchor time — try informative first. |
| 8 | Skip semantics | **Hold** the cadence (next due as if dosed today). |
| 9 | Undo window | Reece unsure → **proposed default below**. |

**Proposed for Q2 (missed)** — with hourly cadences in the model, a flat 3 h grace collides with a 2 h cadence. So the grace follows the cadence: a slot is **late** from its time and **missed when its successor slot is due** (hours cadence), or **late until midnight, never red** for day cadences — the shelf's overdue clock takes over the next morning, which is the nag the keeper already has. Night-window slots for nocturnal feeders don't get a red slash at 22:00; they get amber until 23:59. Cheap to change later: one constant and one branch in the status ladder.

**Proposed for Q9 (undo)** — keep a **10 min undo** on hand logs. The likely error is a phone mis-tap on *Log this dose*, and while the shelf editor can fix the ml ledger, it can't cleanly roll `lastDosedAt` back to the previous history entry; undo can, with a test pinning it.

### 13.9 Staged build (once answers land)

- **Stage A — the model**: `nps.feed_timeline()` pure function + `doseEveryHours`/`doseFirstAt` on products (shelf editor toggle) + `hand_dose_state()` clock rewritten onto the slot function + `consumable_skip_dose` WS (registered!) + cultures harvest events + fold into `nps_summary.timeline`. Tests in `tests/test_nps.py`: hours-cadence slot derivation (6 h, 5 h, 24 h), day cadence at the anchor, `at: null` chips, ghost off-days, done-matching to history, late/missed ladder at fixed `now`, skip holds cadence, reminder/strip lockstep. Runner stays last.
- **Stage B — the strip**: two-lane renderer, glyph/fill language, status overlays, night shading, phone collapse, legend row, queue + honesty line. Demo view gets a mixed hand/pump day so the screenshot sells it.
- **Stage C — the dose card**: popover/bottom sheet, actions per kind, late-log picker, undo. Reuses the phone-buttons pattern from cultures 0.7.126.
- **Stage D — placements**: Feeding-tab header for zero-pump setups + Pulse single-lane strip (summon-only rule: no new chatter). Then real-HA soak on Reece's tank with the rotifer/pod bottles hand-fed and the pumps still unwired — the exact mixed case the feature is for.

### 13.10 What was built (2026-09-05) — and what was deliberately left

**Engine (`nps.py`)**: `hand_dose_slots()` (cadence → slots, 13.4), `hand_dose_state()` rewritten onto it with a `tz` argument — the hours clock snaps to the anchored slot *nearest* `last + n h` (a dose ten minutes late still owns its slot), the days clock lands on the anchor of `last + n d`'s date, a skip stamp (`doseSkippedAt`) is the clock base without touching `lastDosedAt`. `feed_timeline()` folds pumps (past ticks `expected`, the tick nearest the run stamp `done`, `blocked` under a suspension), shelf plans (greedy done-matching to history within half the spacing, any-time chips take anything), skips, carried-over overdue (`due` with "overdue since"), off-day ghosts, unplanned extras, copepod harvests (straight into the display) + the rotifer bottle's `fed_tank` rows, hand-fed brine (feeds-a-day chips while brine is on hand; done marks from the hand-feed reminder's completions), the AWC times/interval band, night, the next-three queue, counts and the honesty line. Q2 as proposed: hours cadence → `missed` when the successor slot is due; days cadence → `late` until midnight, never red.

**Backend (`__init__.py`)**: `doseEveryHours` (0–24) + `doseFirstAt` on products; `doseSkippedAt` server-written and carried through a stale save (newest wins); `consumable_log_dose` takes an optional `at` (≤ now, ≤ 24 h back; history re-sorted, `lastDosedAt` = newest); NEW `consumable_skip_dose` WS (registered — the 0.7.129 lesson) logs a `skipped` completion and snoozes the reminder to the engine's next slot; `nps_summary` carries `timeline` and passes the local tz into the shelf so the pill, the reminder and the strip read one clock. Tests: `tests/test_nps.py` 131 green (9 new).

**Panel**: shelf editor = one number + days/hours unit + "First dose at"; `_npsApplyProductField` owns the unit switch; reminder sync makes an hours cadence a daily chore labelled "(N a day)"; shelf card reads the engine's `cadenceText`. `_npsTimelineSvg()` reads `summary.timeline`: two lanes (⚙︎ ticks / ✋ circles), system row, night, now-line, ladder overlays, midnight-wrapping bands, any-time chips, the queue, the honesty line, the legend; `compact`/`readOnly` for the wall. Dose card inline under the strip (`_npsTimelineEventCard`): Log now / Dosed earlier (time picker → `at`) / Skip today / Dose now (pump, via `_doserDoseNow(id, ml)` with the guard chain) / deep links. Placements: NPS hero, Feeding hub (`_npsFeedingStrip`, also for zero-pump keepers with a plan), Pulse wall (`_pulseFeedStripMarkup`, rides `showToday`, read-only). Demo view stages a mixed day (`_npsDemoTimeline`). Tests: `tests/test_panel_nps.mjs` 47 green (4 new); nav/pulse/mobile/cultures/maintenance/diagram/attention untouched and green.

**Left, on purpose**: the 10-min **undo** (Q9 unsure — `history` + `lastDosedAt` rollback needs its own test; next slice); **truce windows** on the system row; brine done-marks exist only when the hand-feed reminder task exists (the only stamped record of a container feed — a `handFeedLog` would be a new server-written field and a new guard, not worth it until someone misses it); the rotifer bottle has done-marks but no planned chips (no cadence exists for it); the dose card is inline rather than a floating sheet (the 0.7.34 shadow-DOM fullscreen trap).

### 13.11 The 0.7.131 follow-up — the brine feed log, and the undo (2026-09-05)

Reece's first question after the release: *"where does the hand-feed reminder live?"* The brine done-marks rode the `brine_hand_feed` reminder's completions, which only exist once the keeper has tapped **Sync hatchery reminders** on the hatchery card — a hidden dependency nobody would find. Fixed at the source:

- **`hatchery.handFeeds`** — every **Fed** tap (container *and* fridge bottle) stamps `{at, ml, from}` on the hatchery block, newest first, capped at `HAND_FEED_LOG_MAX` (60). Server-written; `_nps_preserve_runtime` unions it by stamp through a stale save. The strip reads it and nothing else; the reminder completion is still written when the task exists, but the mark no longer depends on it.
- **Undo (Q9, resolved)** — `hand_dose_undo()` names the last `dose` row if it is within `HAND_DOSE_UNDO_MIN` (10) minutes; the plan state carries it as `handDose.undo`. NEW `consumable_undo_dose` WS (registered): the row comes off the history, the ml goes back (never overfilling the bottle), `lastDosedAt` falls back to the dose before, the shelf completion the tap wrote is removed, an activity line says so. Pump debits and transfers are the machine's and are never undoable. The dose card shows **Undo N ml** on the done mark it would reverse, with the minutes left.

Tests: `test_nps.py` 133 green (2 new); `test_panel_nps.mjs` 47 green (undo assertions added to the dose-card test).

### 13.12 The 0.7.132 fix — the hand-feed reminder that never appeared

Reece, live: no pump configured, **Sync hatchery reminders** tapped, still no "Feed live brine" reminder. The seeder gated the hand-feed task on `feedExchange.channelId` being *empty* — but a channel id that points at a channel that no longer exists (a deleted or never-finished pump) is a non-empty string, so the panel believed a pump was bound and skipped the reminder, while the settings select sat on its placeholder because nothing matched. Two fixes: the seeder now asks whether the linked channel *exists* as a food channel, and its message names what it seeded ("Feed live brine every 8 h." / "No hand-feed reminder — X is linked as the exchange pump."); and `_normalise_nps_config` clears a link to a channel that is gone (and the exchange's enabled flag with it), so the stale id cannot linger anywhere. Tests: `test_nps.py` 134 (1 new), `test_panel_nps.mjs` 48 (1 new).

### 13.13 0.7.133 — the brine chip feeds itself, and soak/jar bottles leave the strip

Reece, live again: the brine chip's card only said *"tap Fed on the hatchery card"*. Now the card carries the Fed buttons itself — **Fed N ml** from the container, from the fridge bottle, or both when both hold brine (the hatchery card's own commands, so the ledger, the reminder and the mark move together); no brine on hand says so. And the Selcon dot on his strip was the enrichment debit: bottles linked as the hatchery/cultures enrichment or as a jar's feed are `quiet_product_ids` — their logged doses feed the soak or a jar, not the tank, so they never appear as extras (a keeper-set tank cadence still lands its planned slots). Tests: `test_nps.py` 135 (1 new), `test_panel_nps.mjs` 48 (brine-card assertions).

### 13.14 0.7.134 — feeding windows: "3 feeds, 11:00–21:00"

Reece: *"instead of every N hours, let me split a product's feeds over 24 h or just day/night — e.g. 3 feeds of live brine between 11am and 9pm."* The slot model gains a third unit and a window:

- **`spread_slots(n, start, end)`** — N feeds a day: no start = any-time chips; start only = spread evenly across 24 h from the start; start and end = spread evenly *inside* the window, first at the start, last at the end (3 feeds 11:00–21:00 = 11:00, 16:00, 21:00; wraps midnight; one feed = the start).
- **Shelf bottles**: `doseTimesPerDay` + `doseWindowEnd` (the existing `doseFirstAt` is the window start). The editor's unit select is now *times a day / hours / days*; switching carries the number across (3 a day ⇄ every 8 h). Priority in the engine: times a day > hours > days.
- **Hand-fed brine**: `hatchery.handFeed.windowStart/windowEnd` — the brine chips become timed marks inside the window.
- **Rotifer bottle**: `cultures.bottle.feedsPerDay` (0 = no plan) + window — planned "Rotifers from the bottle" slots while the bottle holds rotifers; its `fed_tank` rows are the done marks.
- **The clock and the ladder** no longer assume even spacing: the last dose *owns* its nearest slot and the next slot is simply the one after it; a slot goes *missed* once its successor slot is due today, and the day's last slot stays *late* until midnight. One `_timed_plan()` does matching + grading for shelf, brine, bottle and jar chips alike. Fixed on the way: unplanned extras built inside the matcher lacked the base event fields (an unplanned brine feed would have crashed the summary).

Tests: `test_nps.py` 137 (2 new); `test_panel_nps.mjs` 48 (times-a-day editor assertions).

### 13.15 0.7.135 — a tap on a slot's card files the feed against that slot

Reece, live: with brine on 3 feeds 11:00–21:00 he tapped the missed 11:00 mark and hit **Fed 250 ml** at 17:11 — the feed landed on the 16:00 slot (nearest open) and a second tap became an extra. The matcher was right about the clock and wrong about the intent. Now every feed command (`nps_hand_feed`, `nps_fridge_bottle feed`, `consumable_log_dose`, `cultures_bottle fed`) takes an optional `slot` (HH:MM); the strip's card buttons carry the slot of the mark they were opened from (the hatchery card's plain Fed carries none), the row stores it, and `_match_done` files slotted feeds first, then goes greedy for the rest (an unknown or already-filled slot falls back to nearest). A matched feed is drawn **on its slot**; the card says when it really happened ("Done at 17:11 (planned 16:00)"). The button says what it will do: *Fed 250 ml — filed as the 11:00 feed*. The rotifer-bottle card gets its own Fed. Tests: `test_nps.py` 138 (1 new), `test_panel_nps.mjs` 48.

