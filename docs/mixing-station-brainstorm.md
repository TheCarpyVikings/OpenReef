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
  (no guess).
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
