# Reefnode — the single-ESP32-S3 consolidation (Stage D)

**Build authority for the single-node path.** The flashable reference is
[`reefnode-s3-reference.yaml`](reefnode-s3-reference.yaml); this doc records the
final pin budget, the frozen live-food auto-bind contract, the resolved hardware
call, and the bring-up flow. The classic two-node path
(`awc-esphome-reference.yaml` + `kalk-doser-esphome-design.md` §5, classic-ESP32
pins) remains valid for older builds — nothing there changed.

## 1. Final S3 pin budget

S3 rules honoured: strapping 0/3/45/46, USB-JTAG 19/20, flash 26–32 and
octal-PSRAM 33–37 avoided; UART0 43/44 left for the console.

| GPIO | Signal | Dir | Notes |
|---|---|---|---|
| 4 | `drain_pump` MOSFET | out | |
| 5 | `fresh_pump` MOSFET | out | fill — source 1 |
| 6 | `fresh2_pump` MOSFET | out | fill — source 2 (optional) |
| 7 | `master_enable` relay | out | energize-to-run (fail-OFF); hardware leak-float in the coil |
| 8 | `livefood_pump` MOSFET | out | |
| 9 | `livefood_reservoir_low` | in, pull-up | |
| 10 | `kalk_reservoir_low` | in, pull-up | classic build used GPIO4 |
| 11 | TMC2209 UART TX | out | 500 kBd (classic: 22) |
| 12 | TMC2209 UART RX | in | (classic: 21) |
| 13 | TMC2209 ENN | out | low = enabled (classic: 23) |
| 14 | TMC2209 INDEX | in | (classic: 13) |
| 15 | `leak` | in, pull-down | plus the HARDWARE float in the relay coil |
| 16 | `display_high` | in, pull-down | |
| 17 | `fresh_empty` | in, pull-up | |
| 18 | `fresh2_empty` | in, pull-up | |
| 21 | `waste_full` | in, pull-up | |
| 1, 2, 38–42, 47, 48 | spares | — | |

## 2. Recorded hardware call (was the open bench question)

**The kalk stepper's motor rail runs through the master power-cut relay — yes.**
The TMC2209's *logic* supply stays on the always-on 3.3 V rail so it keeps
answering UART while de-energised (HA still sees the channel; there is simply no
motion). Consequence in firmware: the relay is energised for *normal operation*
(`on_boot`, and re-energised by `Reefnode Clear Lock`) and dropped by any hard
trip — plus, independently, by the hardware leak float in its coil circuit.

## 3. Live-food auto-bind contract — FROZEN (Stage D)

The panel auto-binds a **brushed live-food channel** by these entity-id
suffixes, exactly as the kalk table in `kalk-doser-esphome-design.md` §6 does
for the stepper (contract rev 2 rules apply: `friendly_name` supplies the `<p>`
prefix; ESPHome `text_sensor` entities register under `sensor.`). Machine-checked
by `tests/test_entity_contract.py` against `DOSING_BRUSHED_BINDING_ROLES` and the
panel's brushed suffix map. **Never rename these entities.**

| Binding role | HA entity id |
|---|---|
| `doseVolumeNumber` | `number.<p>_live_food_dose_volume_ml` |
| `doseIntervalNumber` | `number.<p>_live_food_dose_interval_min` |
| `nightIntervalNumber` | `number.<p>_live_food_night_interval_min` |
| `maxDailyNumber` | `number.<p>_live_food_max_daily_ml` |
| `windowStartNumber` | `number.<p>_live_food_window_start_min` |
| `windowEndNumber` | `number.<p>_live_food_window_end_min` |
| `nightStartNumber` | `number.<p>_live_food_night_start_min` |
| `nightEndNumber` | `number.<p>_live_food_night_end_min` |
| `manualDoseMlNumber` | `number.<p>_live_food_manual_dose_ml` |
| `flowMlPerSNumber` | `number.<p>_live_food_flow_ml_s` |
| `spinUpMlNumber` | `number.<p>_live_food_spin_up_ml` |
| `chaserSecondsNumber` | `number.<p>_live_food_chaser_s` |
| `enabledSwitch` | `switch.<p>_live_food_dosing_enabled` |
| `haSuspendSwitch` | `switch.<p>_live_food_ha_suspend` |
| `primeButton` | `button.<p>_live_food_prime_test_run_5s` |
| `doseNowButton` | `button.<p>_live_food_dose_now_one_dose` |
| `manualDoseButton` | `button.<p>_live_food_manual_dose` |
| `calibrateButton` | `button.<p>_live_food_calibrate_30s` |
| `dosedTodaySensor` | `sensor.<p>_live_food_dosed_today_ml` |
| `reservoirLowSensor` | `binary_sensor.<p>_live_food_reservoir_low` |
| `lastSkipSensor` | `sensor.<p>_live_food_last_skip_reason` |
| `chaserSkippedSensor` | `binary_sensor.<p>_live_food_chaser_skipped` |

Frozen skip-reason vocabulary (shared with kalk, minus `ph_guard` — brushed
heads carry no probe): `disabled · ha_suspend · reservoir_low · not_calibrated ·
out_of_window · daily_cap · ok HH:MM`.

**AWC pumps and safety sensors stay explicit-bind** (picked manually in the
panel) — keep the reference names anyway; the YAML's footer lists them.

## 4. Firmware design notes (what differs from the kalk channel)

- **Time-based motion.** A brushed head has no step counts: dose runtime =
  `(dose_ml − spin_up_ml) / flow_ml_s`, executed as pump-ON → delay → pump-OFF,
  with a 60 s max-runtime watchdog as the backstop. `flow_ml_s` boots **0 = not
  calibrated** and every dose path refuses while ≤ 0.
- **Guard chain** is the kalk chain minus the pH step, same order, same skip
  vocabulary.
- **Freshness lives in HA, posture lives here.** The firmware cannot know when a
  culture was mixed; OpenReef turns `Live Food Dosing Enabled` OFF the moment
  the food goes stale and re-asserts every sync (the pH-mirror philosophy). The
  4 h `ha_suspend` dead-man is unchanged and separate.
- **Fresh chaser.** After a successful dose, if `Live Food Chaser (s)` > 0 the
  node runs the **AWC fresh pump** for that many seconds to flush the food line —
  unless the fresh pump is already running (an AWC change owns it), in which
  case it publishes `Live Food Chaser Skipped = on` and does nothing. OpenReef
  reads that flag when it debits the rinse from the fresh reservoir. This
  firmware-sequenced chaser **supersedes the HA-timed chaser sketched in
  `awc-esphome-3pump-design.md`** (conflict resolved at Stage D).
- **Calibration** is a fixed 30 s burst (`Live Food Calibrate 30s`) into a
  measuring jug; the panel derives ml/s — rhyming with kalk's exact
  100 revolutions.

## 5. Bring-up flow (merged node)

1. **Bench, dry, motors disconnected**: flash, join Wi-Fi, confirm every entity
   appears in HA with the `openreef_` prefix. Check `Reefnode Master Enable`
   goes ON a few seconds after boot and OFF on a simulated leak (short GPIO15
   high) — and that the latch requires `Reefnode Clear Lock`.
2. **Floats and sensors**: trip each float and watch the matching entity;
   confirm debounce (no chatter).
3. **Pumps into jugs, water, still unplumbed**: AWC panel explicit-bind (drain,
   fill, fill2 if fitted) → per-pump timed calibration runs from the panel
   ceremony. Kalk: auto-bind (expect **24 of 24**) → prime → `Calibrate
   100 rev` → measure → verify 10 ml ± 5 %. Live food: auto-bind (expect
   **22 of 22**) → prime → `Calibrate 30s` → measure → verify a 5 ml dose.
4. **Guard proofs** (per `OPENREEF_DOSING_SMOKE_TEST.md` §7–10): every guard
   demonstrably blocks with the skip sensor agreeing; watchdogs trip on a
   deliberately-stalled run; the hardware leak float drops the relay with the
   firmware untouched.
5. **Only then plumb to the tank.**

## 6. Residual risks (unchanged, be honest)

A welded relay **plus** a shorted MOSFET on the same channel defeats every
cutoff — the hardware coil float makes that a two-fault condition. A shorted
TMC2209 is stopped only by the relay on its motor rail (the Stage D addition).
Reservoir sizing bounds the worst case; never plumb more water than the tank
can absorb.
