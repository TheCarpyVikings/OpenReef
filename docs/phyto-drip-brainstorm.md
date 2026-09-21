# The phyto drip — a standing live-phyto density for the carnation coral (2026-09-17)

> **STATUS: brainstorm — §8 ANSWERED 2026-09-17, decisions LOCKED. Nothing built.**
> Grows the NPS system (docs/nps-system-brainstorm.md) — this is §6 item 6 of that
> brief, "standing-density phyto mode", finally with a reason and a pump: Reece has a
> Dendronephthya on Reef Juice by hand, and a Kamoer stepper head already owned.

## 1. The idea in one line

A dosing channel whose schedule is set in **cells per millilitre of tank**, not ml a
day: the keeper says *hold ~10,000 cells/mL*, the shelf says what the bottle is worth,
the engine turns that into a 0.1 ml pulse every few minutes around the clock, and the
card tells the truth about what it cannot measure (the tint) and coaches it.

Why it matters: the library already says it — *"the only proven method is a standing
live-phyto density (5,000–50,000 cells/mL, a faint green tint), dosed continuously"*
(`nps.py` dendronephthya entry). Today the tank gets one hand dose of Reef Juice a day
at dusk. A once-a-day pulse is the wrong shape for an animal with weak nematocysts that
filters all day; it gets a tint for an hour and starves for twenty-three.

## 2. What already exists (honest map)

- **The dosing engine is enough.** `compile_schedule` continuous mode takes ml/day +
  a window and emits `doseVolume` (0.1–10 ml) + `doseInterval` (1–240 min), preferring
  10-min cadence when the volume allows. 7 ml/day over 24 h compiles to 0.1 ml every
  ~20 min; 22 ml/day to 0.1 ml every ~6.5 min. **No firmware change is needed for the
  schedule.** The kalk stepper firmware (`dosingnode-s3zero-reference.yaml`): 400
  steps/s, dose = `steps_per_ml × ml`, 60 s tick, day/night intervals.
- **Why the stepper is the right head for this** (and the brushed livefood head is
  not): 0.1 ml at ~0.27 ml/rev is ~1,200 microsteps — repeatable. A brushed KPHM100 at
  ~80 ml/min would deliver 0.1 ml in 75 ms, all spin-up, all guesswork. The stepper
  also **reverses** (TMC2209 DIR), which no other head class can do — see §5.3.
- **Honest physics:** at these rates "continuous" is a pulse train whichever way it is
  driven — a peristaltic roller passing every few minutes IS the drip. Tank mixing time
  is minutes. The card should say *0.1 ml every 8 min*, never pretend a trickle.
- **NPS side:** species library has `cadence: "continuous"`, `feedsPerDay: 12`, foods
  phyto at 1–20 µm. `compile_feed_plan` turns continuous into *"at least 8 doses,
  spread across the day"* — a suggestion in pulses, not a density. Products carry
  `refrigerated`, `stirDaily`, `shelfLifeDaysOpened` (Reefphyto 90 d), particle range —
  **no cell density field**. Reef Juice is on the shelf as a hand-dose plan
  (`doseGuide` 1 ml per 27 / 18 / 9 L a day), which is the fallback rate when the
  bottle's density is unknown.
- **Freshness clock trap:** a `livefood` channel defaults `shelfLifeDays` to 1 and
  fails closed. Phyto in a fridge with daily agitation is good for weeks. The drip
  channel's reservoir clock must **inherit the linked bottle's opened-at + shelf life**
  (LOCKSTEP with the shelf, the way a hand plan already reads it) — never the 1-day
  brine default, or the pump stops every morning. *(Refined in §5.4 once Q2 landed: a
  room-temperature jar at the node IS a 1-day clock, and the `refrigerated` flag picks
  which of the two applies.)*
- **Truce:** §5.6 already exempts micro-doses from orchestration. Right call here.
- **Camera:** `vision.py` exists (feed-watch, event capture). The tint is a colour.

## 3. Research digest (2026-09-17, one sweep)

- Dendronephthya hemprichii / sinaiensis and Scleronephthya feed near-exclusively on
  phytoplankton in the 3–20 µm range; captive losses come from *"our general inability
  to provide plankton in suitable concentrations"* — a concentration problem, not a
  food-type problem ([Saltcorner Q&A](https://www.saltcorner.com/Articles/Showarticle.php?articleID=72)).
- The keepers who succeed dose *"all day long on a timer"* — filter feeders capture
  fine particles continuously and do not wait for a target feed
  ([PodDrop, feeding filter feeders](https://www.getpoddrop.com/blogs/blog/guide-to-feeding-filter-feeders-with-live-phyto)).
- Bottle densities span three orders of magnitude: ~1 million cells/mL greenwater to
  tens of billions for concentrates
  ([PodDrop, cell density](https://www.getpoddrop.com/blogs/blog/phytoplankton-cell-density-explained)).
  Reefphyto's concentrates state ~2 billion cells/mL; Reef Juice is sold "at peak cell
  density" with no figure on the page
  ([Reefphyto, Reef Juice](https://reefphyto.co.uk/products/reef-juice-live-phytoplankton-blend),
  [Reef Flourish concentrate](https://reefphyto.co.uk/products/reef-flourish-super-concentrated-phytoplankton)).
  **Consequence:** the density is a per-bottle field the label fills in, with a
  per-litre ml/day fallback when it is blank.
- Volume rule of thumb for dense live phyto with filter feeders: 5–10 ml per 10 US gal
  (≈ 13–26 ml per 100 L) a day
  ([PodDrop dosing guide](https://www.getpoddrop.com/blogs/blog/marine-phytoplankton-dosing-guide)).
  Reefphyto's own guide is 1 ml per 27 / 18 / 9 L (≈ 4 / 6 / 11 ml per 100 L). Same
  order; the heavy bands agree.
- Already in the NPS brief §3: phyto dies in a warm line, settled phyto dies in days
  (stir daily), fridge life ~4 weeks live. Those three constraints shape §5.

## 4. The maths of a standing density

```
standing stock (cells)      = tank_L × 1000 × target_cells_per_mL
dose to hold it (ml/day)    = standing stock × turnover_per_day / bottle_cells_per_mL
```

Worked example, Reece's 52 L tank, dosed heavy:

| | |
|---|---|
| Standing stock at 10,000 cells/mL | 5.2 × 10⁸ cells — **0.26 ml** of a 2 × 10⁹ cells/mL concentrate |
| Reefphyto heavy guide (1 ml per 9 L) | **5.8 ml/day** of Reef Juice |
| Compiled | 0.1 ml every ~25 min, 24 h |
| Home-grown Nannochloropsis (hobby cultures run ~10⁷–10⁸ cells/mL, 20–200× thinner than a concentrate) | the same cells need **tens of ml a day** — set by colour, not by the guide |

The second-to-last row is why the engine is fine (one pulse every 25 minutes is nowhere near
the 1-minute floor) and the last row is why the maths cannot be the boss: Reece will grow his
own phyto within the week, with no way to count it. The density dial is therefore optional
and the **colour is the controller**. The ml/day dial stays fully hand-settable in every
mode; the cells/mL figure is shown only when a bottle has a density, and reads *unknown —
set by tint* otherwise.

So the standing stock is cheap; **the turnover is the whole game** — skimmer, UV,
filter feeders and cell death clear it many times a day, and nobody knows the number
for a given tank. The mode therefore holds *two* dials the keeper can see: the target
density (the biology, 5k–50k band) and the turnover (the tank, learned). v1 seeds
turnover from the per-litre guides (so the first day's ml/day equals what the shelf
would have said by hand) and lets the keeper nudge it against the tint; v2 (§6) learns
it from the camera.

When the bottle has no density (Reef Juice today, home-grown phyto next week): the mode
degrades honestly to the shelf's per-litre guide at the keeper's stocking band (*heavy*
for Reece — 5.8 ml/day, spread over the day), then the keeper turns the ml/day dial
against the tint. The density line reads *unknown — set by tint*.

Rates land inside the firmware envelope without work: 4–26 ml per 100 L a day at
0.1 ml a pulse is one pulse every 5–35 min for a 200 L tank. A 1,000 L tank at the
heavy rate (260 ml/day) is 0.2 ml every ~1 min — still inside `FIRMWARE_INTERVAL_MIN`.

## 5. The design

### 5.1 The channel

A normal dosing channel, driver `openreef_esphome_stepper`, chemical `food`, linked
bottle category `phyto`. New optional block:

```
schedule.standing = { enabled, targetCellsPerMl, turnoverPerDay }
product.cellsPerMl  (0 = unknown; label wins)
```

`standing.enabled` makes ml/day a *derived* number (recomputed on tank-volume change,
bottle change, dial change — via the canonical tank helpers, never a cached litre) when
the bottle has a density, and a plain hand-set number when it does not. **The window is
the keeper's** (LOCKED): 24 h continuous or any day window — the card shows the line
residence time either way (§5.3) so a short window is a visible choice, not a hidden cost.
The target density is a setting with the 5k–50k band drawn on it, default 10,000. Everything downstream — compile, guards, daily
cap, reservoir runway, integrity, tube wear — is untouched. The advisor doctrine holds:
the derived ml/day is shown beside the dials, and a keeper who turns `standing` off
keeps the last ml/day as a plain schedule.

### 5.2 The card (Feeding hub, and the dosing tab row)

*Phyto drip · holding ~10,000 cells/mL · 0.1 ml every 8 min · 18 ml/day · 11 days in
the bottle.* Below it, the coaching line the library already promises: *a faint green
tint at the glass is correct; clear by evening means the tank clears it faster than
this — raise the turnover.* Then the three clocks: bottle opened (shelf life from the
product), last stirred (§5.4), line residence (§5.3).

### 5.3 Line hygiene — residence time, not dose count

The NPS brief's clean cadence (~6 weeks at 12 doses/day) is a pulse-feed rule; a drip
at 200 pulses/day would nag every third day for no reason. The right figure for a drip
is **how long a cell spends in the warm tube**:

```
residence_h = line_ml / (ml_per_day / 24)      # 2 mm ID × 1 m ≈ 3.1 ml
```

At 5.8 ml/day through a metre of 2 mm line that is ~13 h — right at the warning line,
which is the honest answer for a low-rate drip: keep the line short and the jar close
(Reece's jar sits at the node, §5.4, so it will be). The card shows the figure and warns
past ~12 h. With a day-only window the phyto sits overnight; the stepper's reverse is the
tool: **retract the line's volume at window end** (a new firmware button/number,
stepper-only) so the tube spends the night full of tank water rather than dead algae.
Stage C, optional — a 24 h window needs none of it.
Weekly "flush the line" reminder (vinegar or NaOH per the WARF note) as a maintenance
task with a "Done" that stamps the clock — the §6.9 line-hygiene tracker, cut down.

### 5.4 The jar at the node (now) and the fridge (later)

**LOCKED (Q2/Q6):** the fridge is too far from the dosing node, so v1 is a **small jar
at the node, replaced daily** — a day's dose of phyto at room temperature. That flips
the freshness model from §2: the *jar* clock is the 1-day livefood clock after all, and
the bottle-in-the-fridge clock is a separate thing the shelf already keeps. So the
reservoir carries `refrigerated: false` → shelf life ~1 day from `mixedAt`, stamped by a
**"Loaded" button** (the hatchery's "Hatched & loaded" ceremony, reused) — and the
morning nag is *load today's phyto* rather than a silent stale-stop. A refrigerated
reservoir (the DIY mini-fridge conversion, later) flips the flag and inherits the
bottle's shelf life. Settling in the jar over a day is real: the cheapest fix is an air
line in the jar (DIY phyto drips do this), and the card says so once.

- **Stir:** `stirDaily` is already on every phyto product. Two paths: bound stirrer
  plug (magnetic stirrer in the fridge on a smart plug — the spawning plug pattern) with
  a cadence + burst schedule (the mixing station's stir schedule shape), or, with no
  plug, a daily maintenance task "Stir the phyto". Either way the card's *last stirred*
  clock is one reading; missed 48 h → warn (*settled phyto dies in days*), missed longer
  → the freshness verdict degrades, not a hard stop (advisory, because the keeper may
  have shaken it by hand).
- **Fridge sensor (optional, with the conversion):** a temp sensor entity on the
  channel; *food fridge warm* alert (§6.10). Advise, never pause the pump on it.
- **Home-grown phyto (Q3):** the jar is filled from a culture, not a shop bottle. v1
  treats it as a custom shelf product with no density and no ml to run down (bottle
  size = the jar). Later, a phyto culture can join the rack the way rotifers did, with
  its harvest split between the cone and the drip jar — a cultures-arc follow-on, not
  part of this arc.
- **Bottle-is-reservoir:** the drip decrements the linked bottle directly (the existing
  pending-flush path) so the shelf's days-left and reorder nudge come free.

### 5.5 Skimmer and UV

Continuous phyto meets a running skimmer: the skimmer strips it, that is part of the
turnover, and the keeper pays in ml/day. Alternatives to put to Reece: a nightly
skimmer-off band (a long truce window, already a lane on the strip) which cuts the
turnover for eight hours; or leave it. UV is worse — it kills the cells outright; the
Reefphyto note says UV off for an hour after a dose, which a drip cannot honour.
**LOCKED (Q4): both are keeper settings.** `standing.skimmer` = leave on / off for a
daily band (start–end, on the truce lane, restored by the max-off timer discipline);
`standing.uv` = the same shape. Reece has no UV and will leave the skimmer on; other
keepers will not. The card says once: *UV kills phyto outright — a Dendro tank does
better without it*, and warns about wet-skimming when the skimmer stays on.

### 5.6 The strip, the log and the species report

- **Strip:** a drip is a **band, not 200 marks** — one thin phyto-green bar across the
  24 h with the rate as its label, drawn like the truce band; the next-three queue skips
  it (nothing to tap). The dose card on the band shows today's ml so far vs planned
  (`expected_dosed_ml` already exists).
- **Feed log (§13.19) — Q8, recommended and LOCKED:** **one live row per day**, not
  hourly. *Phyto drip · 3.4 of 5.8 ml so far · 34 pulses · running* — updated on the
  tick, closed at midnight into the existing daily rollup. Hourly rows would be 24
  near-identical lines a day that say nothing; the one thing an hourly row could catch,
  a stall, is already caught by the dosing engine's `missed_state` on the 60 s tick,
  which raises an event row (*drip stalled 14:10 — 0.6 ml short*) in the same log. So:
  a day row for the shape, event rows for the exceptions, never a row per pulse.
- **Species coverage:** a Dendro fed by a standing channel reads *standing density held
  by Phyto drip (~10,000 cells/mL)* rather than *8 doses a day*; `compile_feed_plan`
  gains one branch. The Coral diary entry inherits the same line.
- **Nutrient budget (§5.7):** live phyto takes up NO₃/PO₄ while alive — file it as
  export-that-is-also-food beside the bacterioplankton line (§6.11), not as feed load.
- **Pulse insight:** *phyto drip holding · bottle 11 days · stirred 6 h ago.*

## 6. The intelligence bit (v2) — the tint as a sensor

The tint is the only readout the method has, and the camera is already there.
`vision.py` samples a fixed patch of open water against a stored clear-water
baseline → a **tint index** (green-channel shift, daily curve). Over a week the curve
against the drip rate gives the turnover: *tint fades from mid-afternoon — the tank
clears phyto ~14× a day; raise turnover 11 → 14?* One-tap Apply, the dosing-advisor
UX. Polyp Watch (§6.8 of the NPS brief) on the Dendro itself is the second signal.
Both advisory; nothing auto-doses off a camera. A cheap colour sensor on the glass is
the non-camera fallback — park it.

## 7. Hardware paths (pick one in §8)

| Path | What it is | Firmware work | Line length |
|---|---|---|---|
| **A. Repurpose the kalk slot** | The owned stepper IS the KPHM100-STB10 on the dosing node's TMC2209, and kalk is not running → bind a `food` channel to the existing stepper entities | none | fridge must sit by the node |
| **B. Second stepper on the dosing node** | second TMC2209 on the same UART hub (address 0x01 via MS1/MS2), 3 more GPIO (STEP/DIR/ENN) | duplicate the kalk block under a role-neutral name (`food_stepper_*`), drop the pH guard, add the retract button | same |
| **C. A phyto node at the fridge** | ESP32-S3 Zero + one TMC2209 + the stepper, on the fridge | the kalk block alone as a one-pump YAML, retract button | shortest — the fridge is the rig |

**LOCKED (Q1): path A.** The owned head is the KPHM100-STB10 that was to be the DIY
kalk stepper; kalk is dosing today on a retail Kamoer and the DIY changeover can wait —
the carnation coral takes priority. So the dosing node's existing stepper slot becomes
the phyto drip with **zero firmware work**; when the kalk changeover comes, it is path B
(a second TMC2209 on the hub) or C for whichever pump moves. The residence-time rule
(§5.3) is met by the jar sitting at the node.
The panel's auto-bind discovers entities by YAML name suffix, so B/C name the stepper
generically from day one; the kalk-specific roles (`phStop`, `phResume`, `phGuard`)
simply stay unbound.

## 8. The grill — ANSWERED 2026-09-17, decisions LOCKED

| Q | Reece | Consequence |
|---|---|---|
| 1 | The KPHM100-STB10 meant for DIY kalk, never set up; kalk runs on a retail Kamoer for now | **Path A** — the dosing node's stepper slot, no firmware work |
| 2 | Fridge too far; a DIY mini-fridge conversion later | **Jar at the node, replaced daily**; `refrigerated` flag on the reservoir decides the clock |
| 3 | Reef Juice by hand today; home-grown phyto within the week, density unmeasurable, controlled by colour | Density optional; **ml/day hand-settable, colour is the controller**; §6 tint index is the payoff |
| 4 | No UV here, some users will; skimmer policy configurable | `standing.skimmer` / `standing.uv` settings, band on the truce lane |
| 5 | Keeper picks a window or 24 h | Window free; residence time shown; retract = optional Stage C |
| 6 | Stirrer plug with the fridge build; replacing daily until then | Stirrer binding Stage B; air line tip on the card now |
| 7 | Target is a setting; 52 L, dosing heavy | Default 10,000 cells/mL with the band drawn; worked example §4 is 52 L heavy |
| 8 | "What do you recommend?" | **One live day row + event rows on stalls** (§5.6) |

The original questions, for the record:

1. **Which stepper, and is it busy?** Is the owned head the KPHM100-STB10 that is the
   kalk doser on the dosing node, and is kalk dosing live today? (Decides A vs C.)
2. **Where is the fridge** relative to the dosing node — can the line be under a metre?
3. **Which bottle** feeds the drip: Reef Juice (density unknown — worth an email to
   Reefphyto), or a concentrate with a stated ~2 × 10⁹ cells/mL?
4. **Skimmer policy** during the drip: leave it, or a nightly skimmer-off band? And is
   there a UV on the tank?
5. **24 h drip** (recommended — the residence-time argument) or day-only with the
   stepper retract?
6. **Stirring:** a stirrer on a smart plug in the fridge, or a daily task?
7. **Starting target:** 5,000 cells/mL and climb, or straight to 10,000? And the tank
   litres, so the worked example in §4 is the real one.
8. **Log granularity:** hourly rollup rows, or one row a day?

## 9. Staged build (once answers land)

- **Stage A — the drip, no hardware work** (path A, LOCKED): bind the node's stepper
  as a `food` channel; `product.cellsPerMl` (optional), `schedule.standing` (target,
  turnover, window, skimmer/UV policy), derived ml/day off the canonical tank volume
  when a density exists, hand-set otherwise; jar reservoir with the Loaded ceremony and
  the `refrigerated` clock split; card copy (density or *set by tint*, residence time,
  air-line tip); strip band; one live day row + stall events; species-report branch;
  Pulse line. Tests: dosing (derived rate, envelope,
  degrade-to-guide), nps (coverage verdict), panel (band + card).
- **Stage B — fridge & stir** (with the mini-fridge conversion): stirrer plug
  schedule + last-stirred clock, fridge sensor alert, `refrigerated: true` inherits the
  bottle's shelf life, flush reminder task.
- **Stage C — hardware** (when the kalk changeover comes, or for a day-only window):
  second stepper YAML block or a phyto node, retract button, auto-bind suffixes, bench
  gates per the dosing-node doc.
- **Stage D — the tint:** camera tint index, learned turnover, advisor suggest/apply;
  Polyp Watch on the Dendro. *The tint index shipped as the phyto CULTURE's Stage D (0.7.210,
  docs/phyto-culture-brainstorm.md §13): the bottle's density, estimated from the vessel's
  index through the keeper's count, flips this drip's line to density mode. Learned turnover
  from the tank's own tint and Polyp Watch remain open.*

## 10. Stage A as built (2026-09-17) — the drip, no firmware

Built the same day the answers landed. Nothing in the firmware changed; the kalk
stepper slot on the dosing node carries it (path A).

**Config.** `schedule.standing = {enabled, targetCellsPerMl (default 10,000),
turnoverPerDay (default 10), lineMl (default 3), skimmer/uv: {policy on|band, start,
end}}` on any food channel; `reservoir.refrigerated` (off = a jar on its own day clock,
which the normaliser defaults to 1 day when standing is on; on = the shelf's opened
clock + shelf life via `dosing.reservoir_clock`); `product.cellsPerMl` (0 = unknown,
the panel takes it in millions).

**The derived rate** lives in `_dosing_apply_standing`, a post-pass at the end of
core normalisation: tank L × target × turnover ÷ density, written over `mlPerDay`
whenever the bottle is counted, so a Profile volume edit, a bottle swap or a dial
change flows through on the next save and a stale panel save is corrected on the
next pass. An uncounted bottle leaves ml/day as the keeper set it (by tint). The
maths is `dosing.standing_ml_per_day`; the card's block is `dosing.standing_state`
(density vs tint mode, the pulse text, the line residence hours with the 12 h
warning, the coaching line, the band note, the equipment policy in words).

**What the drip does NOT do.** Its pulses never engage the feed truce (both call
sites check `is_standing`); the jar past its day is a `jar_stale` WARN and a
once-a-day push ("Load today's phyto"), never the livefood stale-stop; the bottle's
pump debits coalesce into one `drip` history row a day (`_consumable_debit(...,
coalesce_day=True)`) so the 50-row history stays weeks deep for the runway.

**The band.** `_async_nps_standing_bands_tick` (from the dosing tick, after the
truce tick) engages the profile through the truce's registry via the extracted
`_async_nps_pause_profile(..., band=True)`; the restore tick honours a `band` stamp
even when the truce is disabled, and files the pause in the same history.

**Surfaces.** Strip: the continuous band's note is the standing text
(`standing: True` on the event). Log: one live day row (`drip`, `running`, `pulses`,
`targetMl` = the realised rate) + past days from `dailyLog` + a stall row while
`missedSince` holds; the shelf's coalesced pump rows are skipped. Species report:
`standingPumps` + *"Standing density held by Phyto drip (~10,000 cells/mL)."* Card:
the standing line, the line residence, the jar/bottle clock with **Loaded ↺**
(`dosing_mark_refreshed`, event text "Jar loaded"). Pulse: one card per drip
(density, today's ml, the jar's hours; warning when stale). NPS summary
`foodChannels[].standing` carries the same block for those surfaces.

**Tests.** `test_dosing.py` +5, `test_nps.py` +5 (incl. the band through a disabled
truce on the fake HA), `test_panel_nps.mjs` +3. Unverified on Reece's HA.

**Left for later stages.** Stirrer plug + last-stirred clock, fridge sensor,
flush-reminder task (B); second stepper / phyto node, retract button (C); camera
tint index → learned turnover → advisor (D). A phyto culture on the rack feeding
the jar is a cultures-arc follow-on.

## 11. Stage B as built (2026-09-17) — the jar's care

Shipped the same day as Stage A, ahead of the mini-fridge conversion so the
settings are waiting for it. Everything here is advice: the pump never waits
on a stir, a fridge reading or a flush.

**Config.** `schedule.standing.stir = {switchEntity, everyHours (default 8,
0 = never on its own), burstMinutes (default 2)}`; `schedule.standing.fridge =
{tempEntity, maxC (default 8)}` — fields shown only once the reservoir is
refrigerated; `schedule.standing.flushEveryDays` (default 7, 0 = no chore).
Channel state (server-written): `lastStirredAt`, `stirUntil`, `lastFlushedAt`,
`fridgeWarm`.

**The stirrer plug.** `_async_dosing_standing_care_tick` runs from the dosing
tick after the band tick: the plug turns on when the cadence has run (or never
ran), `stirUntil` is stamped for the burst, and the tick past it turns the plug
off, stamps `lastStirredAt` and files "Stirred — 2 min on the plug". Both legs
are to the nearest minute (the 60 s tick). A failed switch call retries next
tick with the stamp untouched; unbinding the plug mid-burst clears the stamp.

**The verdicts** live in `dosing.standing_care` (pure; rides `standing_state`
when given the clock): stir `ok / due / warn (48 h) / late (96 h) / unknown`,
fridge `ok / warm / unknown`, flush `ok / due / overdue`. Past 96 h unstirred
the freshness verdict degrades fresh → aging with the note "unstirred for
days", applied at `_dosing_food_freshness` (the one choke point), so the card,
the summary and the guards all read the same thing — aging, never stale.

**The fridge.** `_dosing_fridge_temp_c` reads the sensor (°F converted, -5…40
°C plausible) into the channel's live snapshot; warm above `maxC` files one
channel event and one activity warning on the way up, one push a shift
(`fridge_<cid>`, 6 h), and clears on the way down.

**The flush chore.** `_dosing_sync_flush_task` runs inside the standing
post-pass: `drip_flush_<cid>` is made with the drip's cadence, kept in step,
and DISABLED (never deleted) when the cadence is 0 or the drip is off. The
pump card's Flushed tap (`dosing_mark_standing what=flushed`) stamps the line
and logs the chore's completion with source `dosing`; Stirred (`what=stirred`)
stamps the jar for keepers with no plug. A new drip's line reads "never
flushed" and the chore is due until the first tap — honest, not fabricated.

**Surfaces.** Pump card: Stir / Fridge / Line rows with Stirred ↺ and Flushed
↺, pills `stir it`, `warm`, `due`/`overdue`; the jar line carries the degrade
note. Pulse: the care warnings replace the calm detail and the card goes
warning. Settings: the three field groups under the standing block.

**Tests.** `test_dosing.py` +2, `test_nps.py` +4 (plug on/off through the fake
HA, fridge warm event + push, chore sync + both taps, the degrade),
`test_panel_nps.mjs` +2. Unverified on Reece's HA (no fridge built yet).

**Left.** Second stepper / phyto node + retract (C); camera tint index →
learned turnover → advisor (D).
