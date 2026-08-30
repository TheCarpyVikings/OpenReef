# Saltwater Mixing Station — design brief & staged plan

Decisions locked with Reece 2026-08-28. This doc is the reference; commits cite its §-numbers.

## §1 What it is

A new **Mixing Station** tab (Water group, next to AWC): a guided batch workflow with a live
SVG diagram of the user's actual station. OpenReef drives the switchable hardware (RODI
booster plug, mixing pump plugs, heater plug), times the stages, and publishes an honest
"ready batch" state the rest of OpenReef can trust.

Neither Apex Fusion nor raw HA models the *batch* — they switch outlets. The Trust Moat
move here is that AWC can refuse to run against water that was never tested (§9).

## §2 Locked decisions

- **Layout is configurable: dual-vessel** (RODI store + mix vessel, gravity transfer via
  manual ball valve) **or single-vessel** (fill RODI, salt in place). Reece: dual, 2×50 L.
- **Flow:** Fill RODI → Transfer *(dual only, manual/confirmed)* → **Heat *(optional,
  BEFORE salt — brands require water at temp first)*** → Add Salt & Mix → Test → Ready →
  Storing.
- **Per-run batch type:** `salt` or `rodi` (single-vessel users also make plain top-off
  batches; `rodi` batches skip Heat/Salt/Test and are never AWC-eligible).
- **V1 data honesty:** no level sensors yet → estimate from runtimes + configured volumes
  with manual corrections; settings expose optional level-sensor and salinity-probe
  entities from day one (sensor-first design, estimation fallback).
- **Salinity:** manual refractometer entry v1, target 35 ppt (configurable); optional live
  probe entity later.
- **Salt brand configurable** from a popular-brands list (NYOS for Reece); brand sets the
  default mix-duration timer and the salt-dose guide (§6).
- **Storage:** periodic circulation — OpenReef kicks the mixing pumps on intermittently on
  a configurable cadence, never continuously; retest reminder when a batch ages.
- **Hardware roles (Reece):** RODI booster on smart plug **+ mechanical float valve as the
  hard stop** (software max-runtime cap is the backup); two mixing pumps on **two separate
  plugs**; heater on a plug with dry-run protection; transfer is gravity + manual valve
  (nothing to switch — the workflow prompts and the user confirms).
- **Integrations (all yes, staged):** AWC ready-batch guard (§9), ATO depletes the RODI
  level (dual only), maintenance reminders (batch retest, RODI filter throughput).

## §3 Architecture (house split)

- `custom_components/openreef/mixing.py` — **new pure engine** (stdlib only, no HA):
  batch state evaluation, stage clocks, salt-dose maths, guard-reason builders,
  `summary(cfg, now)`.
- Orchestration in `__init__.py`: new banner section modeled on AWC — `_mixing_cfg`,
  `_mixing_lock` (top-level entry points only hold it), `_async_mixing_set_switch`
  (copy of `_async_awc_set_pump`: sim short-circuit, `blocking=True`, user context),
  best-effort stop path, orphan recovery on restart, HA-timed caps/circulation.
- State is **stamped timestamps evaluated on read** (hatchery pattern) — timers exist only
  where hardware must be switched off (fill cap, circulation window, heater hold).
- Config lives at `config["mixingStation"]` in `DEFAULT_CORE_CONFIG`; bump
  `CORE_SCHEMA_VERSION`; clamps in `const.py` (`MIXING_*`); normaliser
  `_normalise_mixing_config` called from `_normalise_core_config`.
- WS namespace `openreef/mixing_*`, registered in the flat block; replies via `_awc_send`.
- Panel: `_mixingTab()` behind `_mixingEnabled()` gate; Water nav group; `_hubTab` card;
  settings section `or-section-mixing` with pickers via the shared `_awcEntitySelect`
  (keeps the R20 missing-entity rule); `data-scope` branches `mixing` / `mixing-switch` /
  `mixing-vessel`; every mutation calls `_setDirty(true)`.

## §4 Config block (shape)

```jsonc
"mixingStation": {
  "enabled": false,
  "layout": "dual",                    // "dual" | "single"
  "vessels": {
    "rodi": { "volumeLitres": 50, "levelSensorEntity": "" },   // dual only
    "mix":  { "volumeLitres": 50, "levelSensorEntity": "" }
  },
  "switches": {
    "rodiBooster": { "switchEntity": "" },
    "mixPumpA":    { "switchEntity": "" },
    "mixPumpB":    { "switchEntity": "" },
    "heater":      { "switchEntity": "" }
  },
  "rodi":  { "rateLph": 0, "fillCapMin": 240 },   // rateLph 0 = unknown → no ETA shown
  "salt":  { "brand": "nyos", "targetPpt": 35.0, "mixHours": 0 },  // 0 = brand default
  "heat":  { "enabled": true, "targetC": 25.0, "tempSensorEntity": "" },
  "salinitySensorEntity": "",
  "storage": { "circulateEveryH": 6, "circulateForMin": 10, "retestAfterDays": 7 },
  "batch": {                            // stamped by the state machine, never hand-edited
    "state": "idle", "type": "salt",
    "startedAt": null, "stageAt": null,
    "litres": 0, "loggedPpt": null, "testedAt": null, "usedLitres": 0
  },
  "integrations": { "awcGuard": "warn", "atoFromRodi": false }  // "off"|"warn"|"block"
}
```

Estimated levels are derived on read (engine), not stored: RODI level = confirmed fills −
transfers − ATO draw (§10); mix level = batch litres − `usedLitres`. Manual correction WS
command overwrites the ledger's anchor. **No third tank-volume field** — "how much do I
need" for AWC comparisons reuses `_awc_effective_tank_l`.

## §5 State machine

```
MIXING_STATUSES = ("idle", "filling", "transferring", "heating",
                   "salting", "ready", "storing", "fault")
```

- `idle → filling` — `mixing_start_batch {type, litres}`. Guard reasons (engine
  `start_guard_reasons`): another batch active, litres > vessel volume, booster entity
  missing when litres > 0, heater configured but heat target insane, etc.
  Booster plug ON; software cap = `fillCapMin` (HA-timed); float valve is the hard stop.
  User confirms "container full / fill done" → booster OFF.
- `filling → transferring` *(dual + type=salt)* — prompt: open the ball valve; user
  confirms done + litres moved (default: batch litres). Single-vessel or `rodi` batches
  skip this state.
- `→ heating` *(skipped when heat.enabled false or type=rodi)* — heater plug ON.
  **Dry-run protection:** heater is only ever switchable in states after a confirmed
  fill/transfer, and OFF is forced on abort/fault/restart-orphan. With a temp sensor:
  auto-advance prompt at target; without: user confirms "at temp".
- `→ salting` — mixing pumps ON (both plugs), salt-dose guide shown (§6), brand mix timer
  runs (stamped, evaluated on read). Heater may stay ON to hold temp. When the timer
  elapses the Test prompt unlocks: user logs ppt (`mixing_log_salinity`). Within
  tolerance (±0.5 ppt of target) → `ready`; outside → stay in `salting` with add-salt /
  dilute guidance (real maths: grams or RODI litres to correct, from measured vs target).
- `ready → storing` — automatic after a grace period; pumps OFF. Storing runs the
  periodic circulation schedule (pumps ON `circulateForMin` every `circulateEveryH`,
  HA-timed, orphan-recovered) and ages the batch: past `retestAfterDays` the batch
  downgrades to `retest` flag — still visible, not AWC-eligible until re-logged.
- `mixing_mark_used {litres}` — decrements the batch from any ready/storing state;
  at 0 → `idle`. `mixing_abort` from anywhere: best-effort all switches OFF, state
  cleared, reason recorded.
- `fault` only for actuation failures on a safety-relevant OFF (same philosophy as AWC:
  flaky sensors pause, they don't latch).

Backend-authoritative throughout (0.7.79 lesson): stage advances, salinity logging, and
reminder syncs happen in single WS commands that fetch fresh config — never panel-side
config writes.

## §6 Salt brand table (engine data)

`mixing.py` carries a small table: `{brand: {label, gPerL35, mixHoursDefault, useWithinH}}`
for Red Sea Coral Pro, Red Sea Salt, Instant Ocean, Reef Crystals, Tropic Marin Classic,
Tropic Marin Pro Reef, NYOS Pure, Fritz RPM, Aquaforest Reef Salt, Brightwell NeoMarine,
plus `custom` (user enters g/L + hours). Dose guide = `gPerL35 × litres × targetPpt/35`,
always labelled *guide* — brand-published figures, not a promise. Honest-numbers rule: no
figure for `custom` until the user supplies one.

## §7 Diagram

`_mixingDiagramSvg()` on the AWC-diagram pattern: static viewBox scene, CSS keyframes in
an inline `<style>`, state-conditional classes. Dual layout draws two vessels + gravity
line; single draws one. Fill heights from estimated/sensor percentages; animated dashes on
the active flow (fill, transfer, circulation); pump impeller spin while plugs are ON;
heater glow during heating; salt "snow" during salting (CSS only — no rAF loop in v1);
ppt/temp badges when known, absent when not (never a fake reading). Vessel groups are
deep-link buttons (`data-action="tab" data-id="settings" data-section="mixing"`).
Honour the diagram's unavailable-entity styling conventions; `prefers-reduced-motion`
disables the keyframe classes.

## §8 Guided workflow UI

Hatchery-shaped, not a wizard: the backend state is the truth, the tab renders the current
stage card with the *one next action* (button or confirm), progress rail of the stage
sequence (layout-aware — Transfer/Heat cards absent when skipped), and the diagram
animating the same state. Virgin state gets a 3-step "getting started" card. Personality
rules apply: cheeky copy on calm/empty states only, never on safety text.

## §9 AWC "ready batch" guard (Trust Moat)

`awc.start_guard_reasons` gains one optional check: when `mixingStation.enabled` and
`integrations.awcGuard != "off"`, compare the planned change litres against the mixing
station's ready, in-date (`testedAt` fresh, not retest-flagged), salt-type batch volume.
`"warn"` (default) surfaces the reason but allows an acknowledged start; `"block"` refuses.
AWC completion calls `mixing_mark_used` with the fill litres so the ledger stays honest.

## §10 ATO depletion & reminders

- **ATO from RODI** (dual only, opt-in): decrement the RODI ledger from the ATO litres
  OpenReef already tracks where available; if no usage source exists, show nothing
  (no guess). **Stage D finding (2026-08-28): OpenReef tracks no ATO volume anywhere**
  — duty-cycle interlocks time the ATO, nothing measures its litres — so this ships
  with the sensor track (a level entity on the RODI store makes it trivial and honest),
  not as a dead toggle. Stage C's manual level correction covers it meanwhile. The
  `integrations.atoFromRodi` config field stays reserved.
- **Maintenance:** seed/sync reminders the hatchery way (`_mixing_sync_reminders`):
  batch retest when `retestAfterDays` elapses; RODI filter throughput reminder fed by
  cumulative litres filled (interval task on litres is v2 if the task model fights it —
  start with a plain day-interval task).

## §11 Safety summary

1. Float valve = hard stop on fill; software `fillCapMin` cap behind it (HA-timed, orphan-recovered).
2. Heater: stage-gated (never in idle/filling), forced OFF on abort/fault/restart, optional temp-sensor ceiling.
3. Best-effort stop paths: one dead plug never abandons a transition half-done.
4. Orphan recovery in `async_setup_entry`, fail-safe per role: booster and heater force OFF after a restart (unattended, their direction is the hazard); the mixing pumps re-assert ON during `salting` — circulation is the safe direction and the vessel provably holds water by that stage. The stamped clocks keep running regardless.
5. Configured level sensors are fail-closed (`_awc_binary_unknown` pattern): unavailable blocks a start, pauses circulation, never latches a fault.
6. Guards return reason lists (engine) — orchestrator/panel decide presentation.

## §12 Stages & releases

| Stage | Version | Ships |
|---|---|---|
| **A — foundation** | 0.7.84 | `mixing.py` engine (state eval, brand table, dose maths, guards, summary) + config schema/normaliser/clamps + settings section (layout, volumes, pickers, salt, storage) + tab shell + static diagram (all states renderable) + `mixing_summary` WS. Tests: `test_mixing.py` engine + `test_panel_mixing.mjs` (statuses read from `const.py` — anti-drift). |
| **B — the workflow runs** | 0.7.85 | Start/advance/abort WS commands, booster + pumps + heater actuation, fill cap, salinity logging with correction maths, ready state, orphan recovery, sim mode. Safety tests via FakeHass/FakeScheduler (AWC-safety technique). |
| **C — storing & reminders** | 0.7.86 | Periodic circulation scheduler, batch aging/retest flag, manual level corrections, maintenance reminder sync (lockstep rule respected), `mixing_mark_used`. |
| **D — integrations** | 0.7.87 | AWC ready-batch guard (warn/block) + AWC completion decrement; ATO-from-RODI ledger (dual, opt-in); hub card polish + deep links. |

Each stage: one commit, house message style (`Mixing: … (0.7.8x)`), `INTEGRATION_VERSION`
+ `manifest.json` bumped together, `CORE_SCHEMA_VERSION` bump in Stage A. Expect the
demo-drift issue on panel changes. Optional-later (not in this arc): Pulse wall batch
tile, live salinity probe stage auto-advance, TDS/filter-exhaustion tracking.

## §13 Out of scope (v1)

Full "make me a batch" one-button automation (needs level sensors + electric transfer
valve), salinity-probe-driven auto-dosing of salt, multi-batch history/analytics, Pulse
wall tile.

## §15 The pipeline dissolves — independent processes (0.7.94)

Real keepers rarely run a start-to-finish batch. They fill the store and leave it for
days; they transfer and mix only when the tank asks. The forced pipeline
(fill → transfer → … as ONE state machine) is gone; supersedes §5's shape.

- **The vessel is the source of truth.** `vessels.mix` gains its own ledger:
  `estimatedLitres` + `contents` (`empty | rodi | salt`). Every process reads and
  moves that ledger; `remainingLitres` for the run/AWC guard IS the vessel's litres.
- **Independent processes:** *Fill* (RODI runs, §14 — now with destination `mix` and
  an open-ended shape: litres 0 = run to the float valve, fill-cap backstop; no rate
  needed; keeper-confirmed = vessel-full — announced, one Set-level from corrected;
  cap-expired without a rate credits nothing). *Transfer* (`mixing_transfer` — one-shot
  ledger move, gravity did the work). *Mix run* (`mixing_start_mix` — the only state
  machine left: heating? → salting → ready → storing, on whatever RODI the vessel
  holds; `MIXING_STATUSES` shrinks accordingly; salt enters ON the salting edge, so
  the contents flip there).
- **Smart guards across processes:** no transfer or vessel-fill onto standing
  saltwater — EXCEPT while `salting`, where adding RODI is exactly how a too-salty
  batch is diluted (correction maths now uses the live vessel litres); no mixing an
  empty or salty vessel; one booster — draw, calibration and each other exclude.
- **Discard is contents-aware:** stopping a HEATING run keeps the vessel's plain RODI
  (nothing ruined, only warmed); from salting onward discard drains the ledger.
- **Legacy migration (schema 57):** a batch still carrying `type`/`usedLitres` seeds
  the vessel ledger once (litres−used, contents from stage/type); `filling`/
  `transferring` and rodi-type stored "batches" fold to idle — the water stays,
  as vessel contents. RODI-only batches are gone: plain RODI in a vessel IS the
  top-off supply.

## §16 Near-full alerts (0.7.95)

Configurable heads-up (`rodi.alertPct`, default 80, 0 = off) fired ONCE per RODI run
when a container is projected past the threshold — HA persistent notification + the
configured phone push (`_async_send_mode_notification`). Rate-projected, so it exists
only when a rate makes it honest; the T-off gets its own `rodi.externalVolumeL`
(assumes it starts empty — said in settings). Runs that END at/above the threshold
without crossing mid-run get the boundary message at the finish. The alert leg rides
the stamps contract: `draw.alertedAt` + save re-arm ⇒ restart-proof, never twice.

## §17 Filters v2 — every stage its own life (0.7.96)

The single processed-litres counter (§14) grew up: `rodi.filters[]` holds one entry
per PHYSICAL stage in flow order — a 5-stage keeper runs sediment + carbon + carbon +
membrane + DI, each `{id, label, type, ratedLitres, litresProcessed, changedAt}`.
Every litre through the unit counts against EVERY stage (all water passes all
stages — litres are the honest proxy we have; DI keepers can rate by experience).
`mixing_filters_changed` now takes `filter_id` and resets ONE stage;
`rodi.litresProcessed` stays as the unit's lifetime odometer and never resets.
Panel: the filter train — one canister per stage on the tab, fill = percent life
REMAINING (backend-computed; untracked stages draw hollow and dashed, never a guess),
green/amber/red by margin, a Changed button per stage, and the due notice names the
spent stage. Settings: per-stage editor (label, type, rated litres, remove) + Add.
Legacy `filterRatedL` counters migrate into one tracked stage exactly once; the old
keys are read for migration and never emitted again.

## §18 The page in flow order — hero cards (0.7.97)

The tab grew feature-by-feature and read back to front (RODI — the thing you run
FIRST — sat under the mix vessel). Panel-only rework, no config or WS change:

- **Hero cards** (house `summary-grid` / `_missionSummaryCard`): one glance-card
  per station element, left→right in the order the water travels — RODI unit →
  RODI store (dual only) → Mix vessel → Filters. Values come straight from the
  summary; each card scrolls to its section (`or-mixing-*` anchors).
- **Sections in the same order**: Live view (diagram; the level-correction
  inputs fold into a `<details>` — utility, not headline) → *Make water* (RODI
  unit runs/calibration) → *Move water* (transfer, dual only) → *Salt & mix*
  (the mix run: rail, controls, circulation) → *RODI unit health* (the filter
  train on its own card) → Salt dose guide. Notices (refusals, retest-due) pin
  to the top of the page.
- **Transfer as its own card** — and when the vessel is spoken for it says WHY
  transfers are paused (standing saltwater / heating / salting → dilution lives
  on the mix card) instead of hiding. The guard, visible.

## §19 The odometer tells the truth (0.7.98)

Two honesty gaps in §17's lifetime odometer, both raised by Reece: no way to
reset it when the WHOLE unit is replaced, and most keepers install OpenReef
long after their RODI unit — so "unit lifetime" was quietly wrong for them.

- **`rodi.meteredSince`** — stamped by the FIRST litre counted from zero
  (`_mixing_add_processed`), never by an install that arrives already carrying
  litres: OpenReef cannot know when that counting began, and no date beats a
  false one. The panel says "N L metered since <date>" when stamped, and
  "the count began when OpenReef arrived, not when the unit was new" when not.
- **`mixing_unit_replaced` WS** — the odometer's ONLY reset: a new unit comes
  with new cartridges, so it zeroes the odometer AND every stage clock, stamps
  a fresh meteredSince, and writes the activity line. Refused while the booster
  runs (`rodi_busy_reason` — a run's litres belong to one unit). Panel: the
  "New RODI unit" button on the filter card, behind a confirm.
- **Stage-clock caveat, shown only when it applies**: stages that have never
  been swapped under OpenReef carry a hint that their clock starts true at the
  next real swap — the pre-OpenReef wear is invisible to us and we say so.

## §20 The stir schedule shows its face (0.7.99)

Reece, with a fresh ready batch: "struggling to work out how to activate the
store button… is it possible to turn auto mixing on and off?" Store was never
a button — the first scheduled burst IS the ready→storing edge — but every
other rail chip had one, and between bursts the schedule was invisible. Two
real bugs fell out of tracing his question:

- **`nextCirculateAt` joins the batch summary** (ready/storing only; empty
  mid-burst — `circulating` tells that half). The vessel card now says
  "Next stir at 21:40" — day-marked (`Sun 21:40`) when the stir crosses into
  another day, since the cadence can be a week. On ready it adds the chip
  lesson: "that first stir flips the batch to Store by itself. Nothing to
  press." Settings names the switch: "Circulate every (h, 0 = off)".
- **Bug: cadence→0 mid-burst abandoned the pumps ON.** The schedule pass
  cleared the timer, then bailed on `every_h <= 0` before re-arming the stop
  leg — no save while `every_h == 0` could ever stop the burst. The in-flight
  branch now arms the stop leg unconditionally (state alone gates it); the
  stop leg's own cadence read stamps no next burst when it lands on 0.
- **Bug: turning circulation ON could never stir a batch that went ready
  while it was off.** The ready edge stamps no `nextCirculateAt` when the
  cadence is 0, and the pass arms only from stamps — permanent void. The
  normaliser self-heals it: ready/storing + cadence on + no stamps ⇒ anchor
  `now + every_h` on any save (mid-burst untouched; `circulateUntil` owns
  that moment). Stamps stay the schedule; the void just can't survive a save.

## §21 The rate earns its decimals (0.7.100)

Reece calibrated for real and the browser threw both inputs back at him.

- **Rate to 2 dp everywhere**: `calibration_rate` (engine), the calibrate-WS
  round, the normaliser clamp and `rodi_status` all round to 2 decimals. At
  trickle rates a whole-decimal round moves a long fill's ETA by many
  minutes (4.93 vs 4.9 L/h is ~20 min across a 50 L fill).
- **Input grids fixed**: the rate box was `step=0.5` — it refused the real
  4.9; now `step=0.01`. The fill cap was `min=1 step=5`, a grid anchored at
  1 that made 120 invalid ("nearest are 116 and 121"); now by the minute.

## §22 The flush isn't water (0.7.101)

Reece: many RODI units auto-flush to drain for a set time before producing —
that time corrupts a timed calibration (and every rate × time read). New
setting `rodi.flushSeconds` (0–900, default 0, "Auto-flush (s, 0 = none)"),
threaded through EVERY rate × time consumer so they can't drift:

- **`calibration_rate(litres, elapsed, flush)`** — production seconds =
  elapsed − flush; the 60 s floor applies to PRODUCTION (a run the flush
  swallows is refused, and the refusal names the flush).
- **Timed draws budget it**: run length = flush + litres/rate, or every run
  comes up one flush short of its target.
- **Crediting discounts it**: finish/stop legs and the live `litresDone`
  meter production time only — inside the flush window a draw honestly
  reads 0 L; a run stopped inside the flush credits nothing.
- **The near-full projection starts after it** (`draw_alert`).
- Panel: settings field + hint; the calibrating card says "the first N s is
  your unit's auto-flush — discounted automatically, don't subtract it
  yourself" so keepers don't double-correct. `rodi_status` exposes
  `flushSeconds` for that copy. Idle card now prints the raw 2 dp rate
  (`Number(rate)`, was `_format(rate,1)` — a 0.7.100 straggler).

## §23 Calibration becomes a ceremony (0.7.102)

Reece: "as soon as you click calibrate, it starts — not very obvious… this
section deserves more work; users will find this very cool." The old flow
also had a physics bug: litres were read while water still ran, and elapsed
was computed at finish-click — the number drifted while the keeper typed.
Now a guided three-step:

1. **Prep** (panel state `_mixingCalPrep`, NO backend call): "Calibrate
   flow" opens the ceremony card — jug placement, the 60 s floor, the flush
   note — with "Start the water" as the only way any water moves.
2. **Run**: live m:ss clock ticking every second — `_mixingCalArmTicker`
   patches text nodes directly (`[data-mixing-cal-clock/phase/expect]`),
   never `_render()`, so typing survives; self-clears when the element
   leaves the DOM; `unref()`d under Node. Phase line: "Flushing — N s until
   the water counts" → "Collecting — N of production". When an old rate
   exists: "the old 4.93 L/h says ~0.35 L by now — the jug is the judge."
3. **Stop, then read**: new WS action `calibrate stop` — booster off,
   `stoppedAt` stamped, run stays active (still owns the booster; second
   stop refused). Finish computes from the FROZEN window
   (`stoppedAt − startedAt`), so reading the jug takes as long as it takes.
   Litres input step 0.01 (jugs read to 10 ml). The cap leg re-anchors from
   the stop stamp — a 40-min run still leaves the full 30 min to measure;
   an abandoned measure is still tidied (message: "litres never arrived").

Engine: `rodi_status.calibration` gains `stopped` / `elapsedSeconds` /
`productionSeconds` (flush out — panel shows, never computes); `elapsedMin`
freezes at stop. Hero: "Read the jug" state; hero rate now raw 2 dp.
One-click finish-while-running still works at the WS level (back-compat).

## §24 The run warns on its own finish line (0.7.103)

Reece: "am I right that I never get an alert on the T-off without a
container size? …if I select 10 L to T-off, I'd also like an alert when
the 10 L is 80% complete." He was right — `draw_alert` only measured
containers, so a timed external draw with no `externalVolumeL` ran silent.

`draw_alert` now weighs TWO candidate stories and fires the EARLIEST
(still once per run, one `alertedAt` stamp):

- **Container** (unchanged): store/mix volume, or the T-off container when
  its volume is set — the overflow story; still suppressed when a timed
  draw ends before reaching it (finish-boundary check covers that edge).
- **Run** (new, timed draws only): the run passing `alertPct` of its OWN
  target — "The 10 L RODI run to the T-off is passing 80% (8 of 10 L) —
  about 3 min to go." By construction it lands before endsAt, needs no
  suppression, starts after the flush like everything else.

Earliest-wins keeps it one notification per run: a brimming store's
container story beats the run story; an empty store flips it. Ties go to
the container (listed first — the safety flavour). `draw_finish_alert` is
untouched: a "nearly done" that arrives after done is noise. Settings hint
now names the nearly-done heads-up. No new config — alertPct governs both.

## §25 The dose guide tells two stories (0.7.104)

Reece: "the estimated salt stopped updating — I changed vessel size" and
"tell the user how much salt to fill back to full from the current level.
Make the wording obvious." The frozen number was the litres pick order:
the one dose figure preferred vessel CONTENTS over configured volume, so
his standing 15 L pinned it at 585 g while the copy claimed "full batch" —
resizing could never move it.

`summary()` gains `doseGuide` (legacy `dose` kept for old readers; the
panel falls back to it when a stale summary lacks the guide):

- **`full`** — ALWAYS the configured `volumeLitres`: "Fresh full batch:
  50 L from empty needs roughly 1950 g (39.0 g/L)." Resizes move it
  instantly (the save→refetch chain from 0.7.90 already delivers it).
- One **context story** beside it, mutually exclusive:
  - `run` (heating/salting): "This run: the 40 L mixing now took ~1560 g."
  - `topUp` (standing salt, short of full): "Top back up to full: the
    vessel holds 15 L of saltwater — adding 35 L of fresh RODI needs
    roughly **1365 g more** salt. The water already standing keeps its
    own." Caveat appended: assumes the standing water tested at target.
  - `standingRodi` (contents rodi): "Salting what's on hand: the 20 L of
    RODI standing in the vessel needs roughly 780 g."

Maths note: top-up grams = g/L × ADDED litres only — water at target
needs nothing; salt rides in with the new RODI. (The contents guard still
blocks fresh RODI onto standing salt outside a salting run — the top-up
figure is the plan for the next mix, not a button.)

## §26 Your own top-up — the what-if row (0.7.105)

Reece: "if the user decides to add a further 10 L of RODI to the mixed
saltwater — it should calculate how much extra salt to add roughly."

Panel-only (the engine already hands `doseGuide.full.gPerL`): when the
vessel holds saltwater and no mix is running, the dose card grows a live
row — "**Your own top-up:** adding [10] L of fresh RODI needs roughly
**390 g** more salt." Typing updates the grams instantly: a
`data-mixing-dose-whatif` branch in `handleFieldInput` (fires on input AND
change) patches `[data-mixing-dose-whatif-g]` textContent directly — the
cal-ticker pattern, never `_render()`, so typing never fights a repaint.
The litres persist in `_mixingDoseWhatIfL`, so a summary refetch re-renders
with the keeper's figure, not the default. Litres beyond the vessel's free
space get named: "more than the vessel has room for — about 35 L free."
No what-if on RODI contents (RODI into RODI needs no salt) or mid-run
(dilution has its own maths on the mix card). Caveat now plural: the
top-up figures assume the standing water tested at target.

## §27 Fresh refilled is the transfer (0.7.106)

Reece: fold the vessel estimates into the AWC — "Fresh refilled" should
compute what the container took and debit it from the mix vessel. Status
check first: the AWC DOES dead-reckon its fresh container (capacityLitres /
remainingMl / dispensedSinceFullMl, every fill debits it through the single
choke point, drift-graded at the empty-float bookend). What was wrong was
WHERE the mixing vessel paid: Stage D debited it per RUN — the direct-draw
model — while a keeper with a separate AWC container moves water at the
REFILL moment.

New integrations flag **`freshFromVessel`** (default ON — the container
model; the capacity default of 25 L meant "reservoir tracked" could never
be the discriminator):

- **ON**: `websocket_awc_reset_reservoir(fresh)` measures the refill BEFORE
  zeroing (`capacity − remaining`), then `_mixing_debit_batch(refill_l,
  "the AWC fresh refill")` — all the old guards still apply (station
  enabled, awcGuard ≠ off, live tested batch; exhaustion closes the batch).
  Completed changes no longer touch the vessel (`_mixing_run_debit` no-ops)
  — the same litres must never be counted twice. fresh2 never folds back:
  the multi-source line (live-food water) is not the mixing station's.
- **OFF** (direct-draw plumbing): exactly the Stage D behaviour — each
  completed change debits the vessel; refills are a ledger reset only.

Settings: checkbox under the AWC guard picker, both models spelled out.
Level estimates and the dose guide's top-up story follow automatically
(save → summary refetch, held litres drop, top-up grams grow).

## §14 RODI utility (0.7.88 — post-arc)

The RODI unit becomes usable OUTSIDE a batch, because keepers run it for more than
batches — above all the single-vessel crowd filling an ATO reservoir from a T-off.

- **RODI draw** (`mixing_rodi_draw` / `mixing_rodi_stop`): a litre-targeted booster run
  to a chosen destination — `store` (dual only; the anchor is credited) or `external`
  (the T-off; nothing in our vessels moves, the litres still count for the filters).
  Litres are metered by **rate × time**, so a draw REFUSES without a known flow rate —
  never runs blind. Stop leg = persisted `draw.endsAt` stamp, armed by the save pass
  (the circulation chain's contract, so it is restart-proof); an early stop credits
  only what ran; a late fire (restart delay) credits the overrun and says so. Single
  layout refuses `store` — filling the vessel IS a RODI-only batch.
- **Flow calibration** (`mixing_calibrate` start/finish/cancel): timed run into a
  keeper-measured container; finish sets `rodi.rateLph` + `calibratedAt` from
  litres/elapsed. Runs under `MIXING_CAL_MIN_SECONDS` (60 s) refuse — that maths is
  noise. A forgotten run is cancelled by the `MIXING_CAL_CAP_MIN` (30 min) cap leg.
- **Filter ledger**: `rodi.litresProcessed` counts every litre through the membrane
  (batch fills, draws, calibration runs); `filterRatedL` (settings, 0 = untracked)
  turns it into a service warning on the tab; `mixing_filters_changed` resets it.
  This is the "RODI filter litres processed" reminder from §10, delivered as an
  honest counter rather than a day-cadence chore.
- **Mutual exclusion**: draw, calibration and the batch fill share one plug — each
  guards against the others (engine `rodi_busy_reason`); one runtime key
  (`MIXING_RODI_UNSUB`) since only one leg can live at a time.
- Same release: the visual pass — every mixing action button carries a panel class
  (a bare `<button>` rendered as an unreadable white rectangle), level corrections
  get proper compact Set buttons, idle pump glyphs dim, and the diagram animates
  draws (store = feed line, external/calibration = a labelled T-off branch).
