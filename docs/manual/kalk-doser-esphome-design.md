<!-- Generated from OpenReef Dosing Pumps plan, Stage 0, 2026-07-11. Reference design (not drop-in). Companion to docs/manual/kalk-doser-feature-spec.md (original brief) and docs/manual/awc-esphome-reference.yaml (merge target). -->

# OpenReef Kalk Doser — Kalkwasser Stepper Channel on the Shared AWC ESP32 (reference firmware + pin audit)

**Status:** reference design (adapt to your board/wiring — not drop-in, per AWC convention). Merges a kalkwasser stepper channel — Kamoer KPHM100-STB10 peristaltic + BigTreeTech TMC2209 V1.3 over UART — into the existing 2-pump AWC node ([`awc-esphome-reference.yaml`](/home/reece/Workspaces/Ragnars_Reef/docs/manual/awc-esphome-reference.yaml)). Supersedes Appendix A of [`kalk-doser-feature-spec.md`](/home/reece/Workspaces/Ragnars_Reef/docs/manual/kalk-doser-feature-spec.md).

Two things in this doc are **not** adapt-to-taste:

- **The entity names are a frozen contract.** The OpenReef panel's auto-bind feature discovers this channel by scanning `hass.states` for the entity-id **suffixes** in §6 (e.g. `button.*_calibrate_100_rev`). Rename the node, the device, the Wi-Fi — never the entity names.
- **The pins are FINAL for a fresh build** (audit resolved 2026-07-11: neither the AWC pumps nor the doser are built yet, so no device YAML exists to drift from — this document is the wiring authority). Build to the map in §2/§3. Choosing different pins on your fresh build is fine — just update the GPIO table here so doc and copper never disagree, and never touch the entity names.

---

## 1. What changed from the brief's Appendix A

The AWC stance carries over unchanged: **guards live in firmware.** HA edits the schedule; it never runs it. Wi-Fi/HA can drop and the channel keeps dosing (or keeps refusing to dose) on its own judgment. The nine amendments below are the approved plan's firmware-contract changes:

| # | Brief's Appendix A | This design |
|---|---|---|
| 1 | `steps_per_ml` global, placeholder `11851.0` | Global defaults **0 = not calibrated**; new number **Kalk Steps per mL** writes it at runtime; every dose path refuses while ≤ 0. No reflash-to-calibrate. |
| 2 | No AWC coordination primitive | New **Kalk HA Suspend** switch: HA asserts it while an AWC run is active; firmware **auto-expires it after 4 h** so a dead HA can never permanently silence dosing. Boots OFF, never restored. |
| 3 | pH guard hardcoded to `sensor.openreef_ph`, plain threshold | Subscribes to the **fixed mirror** `sensor.openreef_kalk_ph_mirror` (HA republishes the user-picked probe there — repickable at runtime, no reflash). New **Kalk pH Guard Enabled** switch (HA sets it iff a pH entity is bound) + **Kalk pH Resume Below** hysteresis pair + freshness/connectivity fail-closed. Guard OFF ⇒ channel is fully HA-independent. |
| 4 | `homeassistant` time; single interval | **SNTP** time (timezone substitution); dosing **window** numbers (start==end ⇒ 24 h) and **night window + night interval** numbers — day/night weighting executes on-device and survives HA outages. Midnight reset keys off SNTP local midnight. |
| 5 | Only Prime (unguarded) and Dose Now (scheduled size) | New bounded **Kalk Manual Dose (ml)** number + **Kalk Manual Dose** button: runs the **same guard chain** and counts into dosed-today. Prime stays guard-free but hard-bounded (~5 s per press). |
| 6 | Mixed persistence | Every config number/switch restores across reboot — **except Kalk HA Suspend, which must boot OFF**. |
| 7 | Skips only visible in the device log | New text sensor **Kalk Last Skip Reason**: every skip publishes a short reason; successful doses publish `ok HH:MM`. |
| 8 | UART TX GPIO17 / RX GPIO16 / EN GPIO14 | All three collide with the AWC reference — remapped per §2 (**final**: TX→22, RX→21, EN→23). |
| 9 | Guard order implicit | Guard chain order documented (header comment + here): **enabled → !ha_suspend → reservoir not low → calibrated → in window → pH ok (if guard on) → daily cap**. |

Also unchanged from the brief and deliberate: the pH guard can only *stop* dosing when pH is high. There is no "dose when pH < X" pathway anywhere in this firmware, and none can be configured into existence (locked decision 8).

---

## 2. Pin audit — **RESOLVED: this map is final**

> **Audit outcome (2026-07-11):** there is no flashed device to audit — the AWC pumps and the doser are both unbuilt, so the repo's reference YAML is the single source of truth and the remap below is **final for a fresh build**. The table is kept because it documents *why* these pins were chosen over the brief's claims. If you wire differently, update this table and §3 in the same change.

The brief (§7) asserted "firmware pin assignments are fixed and must not be changed: UART TX GPIO17, RX GPIO16, driver enable GPIO14, index GPIO13, reservoir float GPIO4; GPIO25/26/27/32/33 belong to the AWC." Three of those five kalk pins are already spoken for in the repo's AWC reference, and two of the "belongs to AWC" pins are actually free:

| GPIO | 2-pump AWC reference claims | Brief claimed for kalk | Verdict |
|---|---|---|---|
| 16 | `drain_pump` output (`awc-esphome-reference.yaml:95`) | UART RX | **COLLISION** — RX moves to **GPIO21** |
| 17 | `fill_pump` output (`:114`) | UART TX | **COLLISION** — TX moves to **GPIO22** |
| 14 | `waste_full` float input (`:177`) | TMC2209 driver enable | **COLLISION** — EN moves to **GPIO23** |
| 13 | — (free) | TMC2209 INDEX | no conflict — **stays GPIO13** |
| 4 | — (free) | reservoir float | no conflict — **stays GPIO4** |
| 25 / 26 / 27 | `leak` / `display_high` / `fresh_empty` inputs | "belong to the AWC" | consistent — untouched |
| 32 / 33 | **unused** | "belong to the AWC" (wrong) | actually free — **fallback candidates** |

**Why 32/33 are the fallback, not the first choice:** GPIO21/22 are the ESP32's default I2C pins (SDA/SCL). If your fresh build adds an I2C peripheral (display, ADS1115, RTC…), take UART TX/RX to **GPIO32/33** instead, put EN wherever remains free, and update this table. GPIO23 is likewise the default VSPI MOSI — same drill if SPI is in play. GPIO34–39 are input-only and unusable for TX/EN; GPIO0/2/12/15 are strapping pins — avoid.

**If your AWC is the 3-pump ESP32-S3 node** ([`awc-esphome-3pump-design.md`](/home/reece/Workspaces/Ragnars_Reef/docs/manual/awc-esphome-3pump-design.md)) rather than the 2-pump classic ESP32: this audit does **not** apply. That board uses GPIO4–7/15–18/21 (GPIO4 is the *drain MOSFET*, GPIO21 the *waste float*) and has different safe/forbidden pin ranges (26–32 flash, 33–37 octal). Re-run the audit from scratch against that map.

---

## 3. GPIO map (proposed, post-merge)

Merged view of the shared node after adding the kalk channel. Kalk rows are the new claims; AWC rows are unchanged from the 2-pump reference.

| Signal | GPIO | Dir | Mode | Active |
|---|---|---|---|---|
| `drain_pump` (AWC, existing) | GPIO16 | out | ALWAYS_OFF | high = run |
| `fill_pump` (AWC, existing) | GPIO17 | out | ALWAYS_OFF | high = run |
| `leak` (AWC, existing) | GPIO25 | in | pulldown | high = wet |
| `display_high` (AWC, existing) | GPIO26 | in | pulldown | high = over-level |
| `fresh_empty` (AWC, existing) | GPIO27 | in | pullup | on = empty |
| `waste_full` (AWC, existing) | GPIO14 | in | pullup | on = full |
| TMC2209 UART TX (kalk, **new**) | GPIO22 | out | UART 500 kBd | — |
| TMC2209 UART RX (kalk, **new**) | GPIO21 | in | UART 500 kBd | — |
| TMC2209 ENN (kalk, **new**) | GPIO23 | out | driver-managed | low = driver enabled |
| TMC2209 INDEX (kalk, **new**) | GPIO13 | in | driver-managed | pulse per step |
| `kalk_reservoir_low` float (kalk, **new**) | GPIO4 | in | pullup, 2 s debounce | on = empty |

Free after the merge: GPIO32/33 (full I/O — the §2 fallbacks), GPIO34/35/36/39 (input-only).

---

## 4. How OpenReef drives this channel

- **Schedule sync is write-then-verify.** HA compiles `mlPerDay + window + night%` into per-dose volume + day/night intervals, writes the numbers below via `number.set_value`, then reads them back at +8 s. The device keeps executing its **last-synced schedule** through any HA outage — that is the point of on-device execution.
- **pH pathway is a mirror, not a picker.** The firmware subscribes to the fixed id `sensor.openreef_kalk_ph_mirror`; OpenReef republishes the user-picked pH entity there (60 s heartbeat) and publishes `unavailable` when the source drops, which arrives here as NaN ⇒ fail closed. Re-picking the probe in the panel never touches firmware. HA turns **Kalk pH Guard Enabled** ON iff a pH entity is bound — this is how the firmware distinguishes "user never configured pH" (guard off, dose freely) from "pH was configured and is now lost" (guard on, refuse).
- **AWC coordination is one switch.** OpenReef turns **Kalk HA Suspend** ON when an AWC run enters a running state and OFF on finalize/abort. The firmware's 4 h auto-expiry is the dead-man's mitigation: live HA re-asserts on its 60 s tick for as long as suspension is genuinely wanted; a crashed HA loses the argument after 4 h and dosing resumes under the ordinary caps. Suspend-induced shortfall flows through the missed-dose path HA-side (kalk defaults to *skip*, never a compensation spiral).
- **Manual actions are bounded.** Panel "Dose __ ml" writes `Kalk Manual Dose (ml)` then presses `Kalk Manual Dose` — full guard chain, counted into dosed-today. Prime is the only unguarded motion and is hard-bounded to ~5 s per press.

---

## 5. The ESPHome node

Merge notes: this is a **fragment** — the `esphome:`, `esp32:`, `api:`, `ota:`, `wifi:`, `logger:` blocks come from the existing AWC node; do not duplicate them. All list blocks below (`globals`, `script`, `switch`, `binary_sensor`, `sensor`, `number`, `button`) **append** to the AWC node's existing lists (`awc_locked`, `trip_lock`, the pump switches, …). `uart:`, `time:`, `stepper:`, `text_sensor:`, `external_components:` and `interval:` are new top-level blocks on the 2-pump node.

```yaml
# =============================================================================
# OpenReef — Reference ESPHome fragment: KALKWASSER STEPPER DOSER channel
# (merges into the existing AWC node — shares esphome:/api:/wifi: blocks)
# =============================================================================
# Kamoer KPHM100-STB10 stepper peristaltic + BigTreeTech TMC2209 V1.3, UART
# mode, address 0x00. This is a REFERENCE you adapt to your wiring — but the
# ENTITY NAMES ARE A FROZEN CONTRACT: the OpenReef panel auto-binds this
# channel by entity-id suffix. Rename the node, never the entities.
#
# Guard chain — evaluated IN THIS ORDER on every dose attempt (scheduled,
# Dose Now, and Manual Dose alike); the first failure skips the dose and
# publishes Kalk Last Skip Reason:
#   1. kalk_enabled          master enable ON
#   2. !kalk_ha_suspend      not suspended by HA (AWC run); auto-expires 4 h
#   3. !kalk_reservoir_low   optional float not reporting empty
#   4. steps_per_ml > 0      calibrated — the default 0 blocks ALL dosing
#   5. in dosing window      window start==end => 24 h; wrap-aware
#   6. pH ok                 ONLY while kalk_ph_guard is ON: HA link up,
#                            mirror value sane and < 30 min old, hysteresis
#                            latch clear. Guard OFF => fully HA-independent.
#   7. dosed_today + dose <= kalk_max_daily_ml
#
# Fail-safe stances:
#   - steps_per_ml boots 0: an uncalibrated head can never dose.
#   - pH guard ON + HA down/stale/NaN => NO dosing (fail closed).
#   - kalk_ha_suspend boots OFF and auto-expires after 4 h, so a dead HA can
#     never permanently silence dosing.
#   - Motor freewheels between doses: silent, no holding current.
#   - Scheduled dosing waits for first SNTP sync (no clock => no schedule);
#     after first sync the clock survives network loss.
#
# RESIDUAL RISK: a shorted TMC2209 cannot be stopped by any GPIO. Per-dose
# step targets and the daily cap bound firmware/HA failures, NOT silicon
# failure — reservoir sizing is the ultimate backstop. v2 mitigation is the
# master power-cut relay from the 3-pump design. See the risk notes.
#
# PINS FINAL for a fresh build (audit resolved: nothing is wired yet, this doc
# is the authority): GPIO22/21/23 replace the brief's 17/16/14, which collide
# with the AWC reference's fill/drain/waste-full pins. GPIO21/22 are the
# default I2C pins and GPIO23 the default VSPI MOSI — if YOUR build adds those
# buses, take TX/RX to GPIO32/33 instead and update the §2 table to match.
# =============================================================================

substitutions:
  node_name: openreef-awc     # MUST match the existing AWC node
  friendly_name: OpenReef     # MUST match the AWC node's friendly_name — the HA
                              # entity prefix (the auto-bind contract's <p>)
                              # derives from it (contract rev 2)
  timezone: Europe/London     # SNTP local time: dosing windows + midnight reset

external_components:
  - source: github://slimcdk/esphome-custom-components
    components: [ tmc2209_hub, tmc2209, stepper ]

uart:
  id: tmc_uart
  tx_pin: GPIO22     # FINAL — remapped from brief's GPIO17 (AWC fill pump)
  rx_pin: GPIO21     # FINAL — remapped from brief's GPIO16 (AWC drain pump)
  baud_rate: 500000

time:
  - platform: sntp
    id: kalk_time
    timezone: ${timezone}
    on_time:
      # SNTP local midnight — reset the daily total.
      - seconds: 0
        minutes: 0
        hours: 0
        then:
          - script.execute: reset_daily_total

globals:
  # (Appends to the AWC node's existing globals list, e.g. awc_locked.)
  - id: steps_per_ml
    type: float
    restore_value: true
    initial_value: '0'          # 0 = NOT CALIBRATED — blocks all dosing.
                                # (Was a live 11851.0 placeholder in the brief.)
  - id: dosed_today_ml
    type: float
    restore_value: true
    initial_value: '0'
  - id: ph_latched_high
    type: bool
    restore_value: false
    initial_value: 'false'      # hysteresis latch: set at >= stop, cleared < resume
  - id: ph_last_update
    type: uint32_t
    restore_value: false
    initial_value: '0'          # millis() of last FINITE mirror value; 0 = never
  - id: guard_pass
    type: bool
    restore_value: false
    initial_value: 'false'      # result slot for check_guards
  - id: interval_elapsed_min
    type: int
    restore_value: false
    initial_value: '0'          # scheduled-dose cadence counter

number:
  - platform: template
    name: "Kalk Dose Volume (ml)"
    id: kalk_dose_ml
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "ml"
    min_value: 0.1
    max_value: 10
    step: 0.01
    initial_value: 2.08
    mode: box
  - platform: template
    name: "Kalk Dose Interval (min)"
    id: kalk_interval_min
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "min"
    min_value: 1
    max_value: 240
    step: 1
    initial_value: 10
    mode: box
  - platform: template
    name: "Kalk Night Interval (min)"
    id: kalk_night_interval_min
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "min"
    min_value: 1
    max_value: 240
    step: 1
    initial_value: 10
    mode: box
  - platform: template
    name: "Kalk Max Daily (ml)"
    id: kalk_max_daily_ml
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "ml"
    min_value: 0
    max_value: 1000
    step: 5
    initial_value: 300
    mode: box
  - platform: template
    name: "Kalk Dose Speed (steps/s)"
    id: kalk_speed
    entity_category: config
    optimistic: true
    restore_value: true
    min_value: 50
    max_value: 2000
    step: 10
    initial_value: 400
    mode: box
  - platform: template
    name: "Kalk Run Current (A)"
    id: kalk_run_current
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "A"
    min_value: 0.1
    max_value: 1.0
    step: 0.05
    initial_value: 0.6
    set_action:
      # Kept verbatim from the brief — verify against the slimcdk component
      # API at compile time (see tuning notes).
      - lambda: |-
          id(kalk_driver).write_run_current(x);
  - platform: template
    name: "Kalk pH High Stop"
    id: kalk_ph_stop
    entity_category: config
    optimistic: true
    restore_value: true
    min_value: 7.5
    max_value: 9.0
    step: 0.05
    initial_value: 8.40
    mode: box
  - platform: template
    name: "Kalk pH Resume Below"
    id: kalk_ph_resume
    entity_category: config
    optimistic: true
    restore_value: true
    min_value: 7.0
    max_value: 9.0
    step: 0.05
    initial_value: 8.30
    mode: box
    # The OpenReef normalizer enforces resume <= stop - 0.05. If misconfigured
    # (resume >= stop) the latch degrades to a plain threshold at stop — it can
    # never invert into "dose when pH is high".
  - platform: template
    name: "Kalk Steps per mL"
    id: kalk_steps_per_ml
    entity_category: config
    optimistic: true
    restore_value: true
    min_value: 0
    max_value: 200000
    step: 0.1
    initial_value: 0
    mode: box
    set_action:
      # Calibration lands here from the panel: steps_per_ml = 320000 / measured_ml.
      - lambda: |-
          id(steps_per_ml) = x;
  - platform: template
    name: "Kalk Window Start (min)"
    id: kalk_window_start_min
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "min"
    min_value: 0
    max_value: 1439
    step: 1
    initial_value: 0          # start == end => dose 24 h (the default)
    mode: box
  - platform: template
    name: "Kalk Window End (min)"
    id: kalk_window_end_min
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "min"
    min_value: 0
    max_value: 1439
    step: 1
    initial_value: 0
    mode: box
  - platform: template
    name: "Kalk Night Start (min)"
    id: kalk_night_start_min
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "min"
    min_value: 0
    max_value: 1439
    step: 1
    initial_value: 1320       # 22:00
    mode: box
  - platform: template
    name: "Kalk Night End (min)"
    id: kalk_night_end_min
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "min"
    min_value: 0
    max_value: 1439
    step: 1
    initial_value: 480        # 08:00 (wraps midnight — handled wrap-aware)
    mode: box
  - platform: template
    name: "Kalk Manual Dose (ml)"
    id: kalk_manual_dose_ml
    entity_category: config
    optimistic: true
    restore_value: true
    unit_of_measurement: "ml"
    min_value: 0.1
    max_value: 10
    step: 0.1
    initial_value: 2
    mode: box

switch:
  # (Appends to the AWC node's existing switch list.)
  - platform: template
    name: "Kalk Dosing Enabled"
    id: kalk_enabled
    optimistic: true
    restore_mode: RESTORE_DEFAULT_OFF   # master enable survives reboot
  - platform: template
    name: "Kalk HA Suspend"
    id: kalk_ha_suspend
    optimistic: true
    restore_mode: ALWAYS_OFF            # MUST boot OFF — a suspend never
                                        # survives a reboot, and never restores
    on_turn_on:
      - script.execute: ha_suspend_expiry
    on_turn_off:
      - script.stop: ha_suspend_expiry
  - platform: template
    name: "Kalk pH Guard Enabled"
    id: kalk_ph_guard
    optimistic: true
    restore_mode: RESTORE_DEFAULT_OFF   # HA turns this ON iff a pH entity is
                                        # bound in the panel. OFF => the pH
                                        # guard is not consulted at all and the
                                        # channel is fully HA-independent.

sensor:
  # (Appends to the AWC node's existing sensor list, if any.)
  - platform: homeassistant
    id: tank_ph
    entity_id: sensor.openreef_kalk_ph_mirror   # FIXED id — do not point at a
    # raw probe. OpenReef republishes the user-picked pH entity here (60 s
    # heartbeat) and publishes `unavailable` when the source drops, which
    # arrives as NaN => fail closed while the guard is on.
    on_value:
      - lambda: |-
          if (!std::isnan(x)) {
            id(ph_last_update) = millis();
            // Hysteresis latch: engage at/above stop, release below resume.
            if (x >= id(kalk_ph_stop).state) {
              id(ph_latched_high) = true;
            } else if (x < id(kalk_ph_resume).state) {
              id(ph_latched_high) = false;
            }
          }
  - platform: template
    name: "Kalk Dosed Today (ml)"
    id: kalk_dosed_today
    unit_of_measurement: "ml"
    accuracy_decimals: 2
    lambda: 'return id(dosed_today_ml);'
    update_interval: 30s

binary_sensor:
  # (Appends to the AWC node's existing binary_sensor list.)
  - platform: gpio
    name: "Kalk Reservoir Low"
    id: kalk_reservoir_low
    pin:
      number: GPIO4            # no conflict — unchanged from the brief
      mode:
        input: true
        pullup: true
    filters:
      - delayed_on: 2s
      - delayed_off: 2s

text_sensor:
  # NB: ESPHome `text_sensor` entities register in HA under the `sensor.`
  # domain — the auto-bind row is `sensor.<p>_kalk_last_skip_reason` (rev 2).
  - platform: template
    name: "Kalk Last Skip Reason"
    id: kalk_last_skip
    update_interval: never     # push-only: written by check_guards / run_dose

stepper:
  # TMC2209 block kept verbatim from the brief (slimcdk external component) —
  # only the enn_pin is remapped. Verify field names against the component
  # version you pin (see tuning notes).
  - platform: tmc2209
    id: kalk_driver
    max_speed: 400 steps/s
    acceleration: 1000 steps/s^2
    deceleration: 1000 steps/s^2
    rsense: 110 mOhm
    vsense: False
    address: 0x00
    enn_pin: GPIO23    # FINAL — remapped from brief's GPIO14 (AWC waste float)
    index_pin: GPIO13  # no conflict — unchanged from the brief
    on_boot:
      - tmc2209.configure:
          microsteps: 16
          interpolation: true
      - tmc2209.currents:
          standstill_mode: freewheeling   # silent between doses, no holding current
          run_current: 0.6A
          ihold: 0
          iholddelay: 0
          tpowerdown: 0

script:
  # (Appends to the AWC node's existing script list — trip_lock etc. untouched.)

  # --- THE guard chain (one place, both dose paths) --------------------------
  # Synchronous (single lambda, no delays): callers may read guard_pass
  # immediately after script.execute returns. The script.wait in the callers is
  # kept so the chain stays correct if a check ever gains an async step.
  - id: check_guards
    mode: restart
    parameters:
      dose_ml: float
    then:
      - lambda: |-
          std::string reason;   // empty = pass
          if (!id(kalk_enabled).state) {
            reason = "disabled";
          } else if (id(kalk_ha_suspend).state) {
            reason = "ha_suspend";
          } else if (id(kalk_reservoir_low).state) {
            reason = "reservoir_low";
          } else if (id(steps_per_ml) <= 0.0f) {
            reason = "not_calibrated";
          } else {
            // Dosing window: start == end => 24 h. Wrap-aware. If a window is
            // configured but SNTP never synced, fail closed as out_of_window.
            const int ws = (int) id(kalk_window_start_min).state;
            const int we = (int) id(kalk_window_end_min).state;
            bool in_window = (ws == we);
            if (!in_window) {
              auto now = id(kalk_time).now();
              if (now.is_valid()) {
                const int mod = now.hour * 60 + now.minute;
                in_window = (ws < we) ? (mod >= ws && mod < we)
                                      : (mod >= ws || mod < we);
              }
            }
            if (!in_window) {
              reason = "out_of_window";
            } else {
              // pH guard — consulted ONLY while the guard switch is on.
              bool ph_ok = true;
              if (id(kalk_ph_guard).state) {
                if (api::global_api_server == nullptr ||
                    !api::global_api_server->is_connected()) {
                  ph_ok = false;                                  // HA link down
                } else if (std::isnan(id(tank_ph).state)) {
                  ph_ok = false;                                  // mirror unavailable
                } else if ((millis() - id(ph_last_update)) > 1800000UL) {
                  ph_ok = false;                                  // stale > 30 min
                } else if (id(ph_latched_high)) {
                  ph_ok = false;                                  // latched high
                }
              }
              if (!ph_ok) {
                reason = "ph_guard";
              } else if ((id(dosed_today_ml) + dose_ml) >
                         id(kalk_max_daily_ml).state) {
                reason = "daily_cap";
              }
            }
          }
          id(guard_pass) = reason.empty();
          if (!reason.empty()) {
            id(kalk_last_skip).publish_state(reason);
            ESP_LOGW("kalk", "Dose skipped: %s", reason.c_str());
          }

  # --- Motion + accounting (callers MUST guard first) ------------------------
  - id: run_dose
    mode: single
    parameters:
      dose_ml: float
    then:
      - stepper.set_speed:
          id: kalk_driver
          speed: !lambda 'return id(kalk_speed).state;'
      - stepper.report_position:
          id: kalk_driver
          position: 0
      - stepper.set_target:
          id: kalk_driver
          target: !lambda 'return (int)(dose_ml * id(steps_per_ml));'
      - globals.set:
          id: dosed_today_ml
          value: !lambda 'return id(dosed_today_ml) + dose_ml;'
      - lambda: |-
          auto now = id(kalk_time).now();
          char buf[16];
          if (now.is_valid()) {
            snprintf(buf, sizeof(buf), "ok %02d:%02d", now.hour, now.minute);
          } else {
            snprintf(buf, sizeof(buf), "ok");
          }
          id(kalk_last_skip).publish_state(buf);

  # --- Scheduled / Dose Now path (uses the configured dose volume) -----------
  - id: do_one_dose
    mode: single
    then:
      - script.execute:
          id: check_guards
          dose_ml: !lambda 'return id(kalk_dose_ml).state;'
      - script.wait: check_guards
      - if:
          condition:
            lambda: 'return id(guard_pass);'
          then:
            - script.execute:
                id: run_dose
                dose_ml: !lambda 'return id(kalk_dose_ml).state;'

  # --- Bounded manual path (same guards, manual volume, counted) -------------
  - id: do_manual_dose
    mode: single
    then:
      - script.execute:
          id: check_guards
          dose_ml: !lambda 'return id(kalk_manual_dose_ml).state;'
      - script.wait: check_guards
      - if:
          condition:
            lambda: 'return id(guard_pass);'
          then:
            - script.execute:
                id: run_dose
                dose_ml: !lambda 'return id(kalk_manual_dose_ml).state;'

  # --- HA-suspend dead-man auto-expiry ----------------------------------------
  # mode: restart => the 4 h clock re-arms on every ON edge. Live HA re-asserts
  # the switch while an AWC run genuinely needs suspension; a dead HA loses the
  # argument after 4 h and dosing resumes under the ordinary caps.
  - id: ha_suspend_expiry
    mode: restart
    then:
      - delay: 4h
      - switch.turn_off: kalk_ha_suspend
      - logger.log:
          level: WARN
          format: "Kalk HA-suspend auto-expired after 4 h (HA never cleared it)."

  - id: reset_daily_total
    then:
      - globals.set:
          id: dosed_today_ml
          value: '0'

button:
  # (Appends to the AWC node's existing button list, if any.)
  - platform: template
    name: "Kalk Prime / Test (run 5s)"
    id: kalk_prime_button
    on_press:
      # Deliberately guard-free (first-run priming, direction checks) but
      # hard-bounded: ~5 s of steps at the configured speed per press. Not
      # counted into dosed_today — prime output normally isn't plumbed to the
      # tank yet. This is the ONLY unguarded motion path.
      - stepper.set_speed:
          id: kalk_driver
          speed: !lambda 'return id(kalk_speed).state;'
      - stepper.report_position:
          id: kalk_driver
          position: 0
      - stepper.set_target:
          id: kalk_driver
          target: !lambda 'return (int)(id(kalk_speed).state * 5);'
  - platform: template
    name: "Kalk Dose Now (one dose)"
    id: kalk_dose_now_button
    on_press:
      - script.execute: do_one_dose
  - platform: template
    name: "Kalk Manual Dose"
    id: kalk_manual_dose_button
    on_press:
      - script.execute: do_manual_dose
  - platform: template
    name: "Kalk Calibrate 100 rev"
    id: kalk_calibrate_button
    on_press:
      # Fixed 320000 microsteps = 200 steps x 16 microsteps x 100 revolutions.
      # Panel computes steps_per_ml = 320000 / measured_ml and writes the
      # Kalk Steps per mL number. Guard-free by design: calibration must work
      # on an uncalibrated (steps_per_ml == 0) channel.
      - stepper.set_speed:
          id: kalk_driver
          speed: !lambda 'return id(kalk_speed).state;'
      - stepper.report_position:
          id: kalk_driver
          position: 0
      - stepper.set_target:
          id: kalk_driver
          target: 320000

interval:
  # --- Scheduled-dose executor -------------------------------------------------
  - interval: 60s
    then:
      - lambda: |-
          // Re-seed the calibration global from the restored number every tick
          // (covers NVS restore-ordering between the global and the number;
          // set_action covers live edits).
          id(steps_per_ml) = id(kalk_steps_per_ml).state;

          // No clock, no schedule: before the first SNTP sync scheduled dosing
          // does not run (fail closed on time). After first sync the clock
          // keeps ticking through network loss.
          auto now = id(kalk_time).now();
          if (!now.is_valid()) return;
          const int mod = now.hour * 60 + now.minute;

          // Dosing window (start == end => 24 h; wrap-aware).
          const int ws = (int) id(kalk_window_start_min).state;
          const int we = (int) id(kalk_window_end_min).state;
          const bool in_window = (ws == we) ||
                                 ((ws < we) ? (mod >= ws && mod < we)
                                            : (mod >= ws || mod < we));

          // Cadence: night interval inside the night window, else day interval.
          // Night window is wrap-aware (default 22:00 -> 08:00); start == end
          // disables the night rate entirely.
          const int ns = (int) id(kalk_night_start_min).state;
          const int ne = (int) id(kalk_night_end_min).state;
          const bool night = (ns != ne) &&
                             ((ns < ne) ? (mod >= ns && mod < ne)
                                        : (mod >= ns || mod < ne));
          int cadence = (int) (night ? id(kalk_night_interval_min).state
                                     : id(kalk_interval_min).state);
          if (cadence < 1) cadence = 1;

          // The counter keeps counting outside the window so the first
          // in-window minute doses immediately at window-open.
          id(interval_elapsed_min) += 1;
          if (in_window && id(interval_elapsed_min) >= cadence) {
            id(interval_elapsed_min) = 0;
            id(do_one_dose).execute();
          }
```

---

## 6. OpenReef entity mapping — the frozen auto-bind contract

**This table is the contract.** The panel's auto-bind scans `hass.states` for these entity-id **suffixes** (the slug ESPHome derives from each entity's name) and fills the channel's explicit per-role bindings. `<p>` is the device prefix HA prepends from the node's **`friendly_name`** (`openreef` with the reference YAML's `friendly_name: OpenReef`) — the prefix may vary per install, **the suffix may not**. A node with no `friendly_name` yields prefix-less ids; auto-bind accepts those as exact bare ids (`number.kalk_dose_volume_ml`). Changing any entity name in the YAML silently breaks auto-bind for every user; treat renames as breaking API changes.

> **Contract revision 2 (2026-07-11).** Two corrections to rev 1, both permissible because no rev-1 install could ever have bound the affected rows: (a) `lastSkipSensor` was listed under a `text_sensor.` HA domain that does not exist — ESPHome text sensors register in HA as `sensor.`; the row now reads `sensor.<p>_kalk_last_skip_reason`. (b) The reference AWC node previously set no `friendly_name`, so a verbatim build produced prefix-less ids and the suffix scan matched nothing; `friendly_name` is now set in the reference YAML and declared part of this contract, and the panel additionally accepts exact bare ids for prefix-less nodes.

| OpenReef role | HA entity (frozen suffix) | Node object |
|---|---|---|
| `doseVolumeNumber` | `number.<p>_kalk_dose_volume_ml` | `kalk_dose_ml` |
| `doseIntervalNumber` | `number.<p>_kalk_dose_interval_min` | `kalk_interval_min` |
| `nightIntervalNumber` | `number.<p>_kalk_night_interval_min` | `kalk_night_interval_min` |
| `maxDailyNumber` | `number.<p>_kalk_max_daily_ml` | `kalk_max_daily_ml` |
| `doseSpeedNumber` | `number.<p>_kalk_dose_speed_steps_s` | `kalk_speed` |
| `runCurrentNumber` | `number.<p>_kalk_run_current_a` | `kalk_run_current` |
| `phStopNumber` | `number.<p>_kalk_ph_high_stop` | `kalk_ph_stop` |
| `phResumeNumber` | `number.<p>_kalk_ph_resume_below` | `kalk_ph_resume` |
| `stepsPerMlNumber` | `number.<p>_kalk_steps_per_ml` | `kalk_steps_per_ml` |
| `windowStartNumber` | `number.<p>_kalk_window_start_min` | `kalk_window_start_min` |
| `windowEndNumber` | `number.<p>_kalk_window_end_min` | `kalk_window_end_min` |
| `nightStartNumber` | `number.<p>_kalk_night_start_min` | `kalk_night_start_min` |
| `nightEndNumber` | `number.<p>_kalk_night_end_min` | `kalk_night_end_min` |
| `manualDoseMlNumber` | `number.<p>_kalk_manual_dose_ml` | `kalk_manual_dose_ml` |
| `enabledSwitch` | `switch.<p>_kalk_dosing_enabled` | `kalk_enabled` |
| `haSuspendSwitch` | `switch.<p>_kalk_ha_suspend` | `kalk_ha_suspend` |
| `phGuardSwitch` | `switch.<p>_kalk_ph_guard_enabled` | `kalk_ph_guard` |
| `primeButton` | `button.<p>_kalk_prime_test_run_5s` | `kalk_prime_button` |
| `doseNowButton` | `button.<p>_kalk_dose_now_one_dose` | `kalk_dose_now_button` |
| `manualDoseButton` | `button.<p>_kalk_manual_dose` | `kalk_manual_dose_button` |
| `calibrateButton` | `button.<p>_kalk_calibrate_100_rev` | `kalk_calibrate_button` |
| `dosedTodaySensor` | `sensor.<p>_kalk_dosed_today_ml` | `kalk_dosed_today` |
| `reservoirLowSensor` | `binary_sensor.<p>_kalk_reservoir_low` | `kalk_reservoir_low` |
| `lastSkipSensor` | `sensor.<p>_kalk_last_skip_reason` | `kalk_last_skip` |

Not in the binding table but equally frozen: the firmware subscribes to the fixed id **`sensor.openreef_kalk_ph_mirror`** (`DOSING_PH_MIRROR_ENTITY`). That is an HA-side state OpenReef publishes, not an ESPHome entity — the panel's pH picker selects the *source* that gets mirrored there.

`Kalk Last Skip Reason` values (also frozen — reserved for panel banner copy; today they surface via the sensor itself and the smoke test): `disabled` · `ha_suspend` · `reservoir_low` · `not_calibrated` · `out_of_window` · `ph_guard` · `daily_cap` · `ok HH:MM` on success.

---

## 7. Tuning notes

- **Run current: start from the motor label, not this file.** The 0.6 A default is deliberately conservative for the KPHM100-STB10's stepper. Set run current to ~60–80 % of the motor's rated phase current (check your unit's label — Kamoer has shipped different windings); a peristaltic head needs modest torque, and every extra 100 mA is heat in the driver and motor. Raise it only if the head audibly skips steps under load; the bare TMC2209 V1.3 runs ~1 A RMS comfortably without a fan, more only with airflow.
- **Dose speed is a chemistry knob, not a throughput knob.** At 400 steps/s and 16 microsteps the head turns 0.125 rev/s ≈ 7.5 rev/min ≈ **2.0 ml/min** at the nominal 0.27 ml/rev — a 2.08 ml dose takes ~62 s. That slowness is a *feature*: kalkwasser is pH ~12.5, and slow delivery above the waterline lets each dose disperse before the next drop lands. Doubling the speed halves the dose time and sharpens the local pH spike. If you raise `kalk_speed` past `max_speed` in the stepper block, raise both.
- **Draw from the clear zone, never the slurry.** Keep the intake a few cm off the reservoir bottom, dose only clear saturated solution, and never dose after stirring — undissolved Ca(OH)₂ particles overdose locally and clog/abrade the head. Top up with RO and fresh powder, stir, then let it settle fully before the next dose window.
- **Vinegar flush on a schedule.** Kalk precipitates CaCO₃ crust in the tube and head. Monthly: run dilute white vinegar through the line (Prime button), follow with an RO rinse, then **recalibrate** — any tube service changes ml/rev. The 60-day calibration-age nag in the panel exists for exactly this drift.
- **Night weighting worked example** (what HA computes and writes — the firmware just executes two intervals): target 300 ml/day, 65 % at night, night window 22:00–08:00 (600 min night, 840 min day), dose volume 2.0 ml. Night: 195 ml ÷ 2.0 ml = 97.5 doses over 600 min → **6 min night interval**. Day: 105 ml ÷ 2.0 ml = 52.5 doses over 840 min → **16 min day interval**. HA writes `kalk_dose_ml = 2.0`, `kalk_interval_min = 16`, `kalk_night_interval_min = 6`; delivered ≈ 200 + 104 ml and the 300 ml daily cap trims the rounding overshoot. The cap is therefore part of the schedule, not just a safety — keep it at (not above) the daily target.
- **ESPHome syntax to verify at first compile** (kept as the brief wrote them where the external component's API is uncertain): (1) the whole `stepper: platform: tmc2209` block and `tmc2209.configure` / `tmc2209.currents` / `write_run_current(x)` come verbatim from the brief — pin the slimcdk component to a known-good ref and check its docs for renames; (2) `api::global_api_server->is_connected()` in the guard lambda — some ESPHome versions expose it unqualified as `global_api_server`; adjust to whatever compiles; (3) script `parameters:` need ESPHome ≥ 2023.x; (4) template **switches** persist via `restore_mode` (the brief's `restore_value: true` on a switch is not a valid option — numbers use `restore_value`, switches use `restore_mode`); (5) `update_interval: never` on the template text sensor.

---

## 8. Honest residual-risk notes

1. **A shorted TMC2209 cannot be stopped by any GPIO.** Per-dose step targets, the guard chain, and the daily cap bound *firmware and HA* failures — not silicon failure. A driver that fails conducting runs the head until power is cut. Realistic bounds: dose volume per event (position-target motion), then reservoir size. **Size the kalk reservoir so a total dump is survivable** (2–3 days' volume, not 50 L of saturated limewater over a 52 L tank). The v2 mitigation is the master power-cut relay + hardware interlock from the 3-pump design (§4 there); this 2-pump-node merge ships without it.
2. **HA outage with pH guard ON pauses kalk — by design.** The mirror goes stale in ≤ 30 min (or the API-connected check trips immediately) and the channel refuses to dose until HA returns. That is the fail-closed stance the guard promises. If you want kalk to survive HA outages, run the guard OFF — and accept risk 3.
3. **HA outage with pH guard OFF keeps dosing on schedule.** The channel is then fully autonomous: windows, night rates, and the daily cap still bind, but nothing chemical does. A stuck-high pH excursion during an HA outage will not stop the schedule. Choose your poison per tank; the panel makes the choice loud, never silent.
4. **The float switch is optional, so "reservoir empty" is often advisory.** Without a float, the HA-side ledger is dead reckoning — a leak, a mis-entered refill, or doses during an HA outage desync it, and the head will happily pump air. Pumping air is mechanically harmless for a peristaltic but the tank silently receives nothing while dosed-today keeps counting. Fit the float; it's one GPIO.
5. **SNTP is a dependency for the schedule.** A node that boots during an internet outage never syncs and never schedule-doses until it does (manual/Dose Now still work when the window is 24 h). After first sync the clock free-runs through outages but drifts (seconds/day — irrelevant at 10-min cadence); midnight reset and DST follow the `timezone` substitution, so a wrong timezone shifts the daily-cap day.
6. **Kalk crust can jam the head between doses — and the firmware can't see it.** Dosing is open-loop: the TMC2209 steps whether or not the rotor turns, `dosed_today` counts *commanded* ml, and there is no delivered-volume feedback. A crusted or stalled head under-doses silently until alkalinity drifts. Mitigations: the vinegar-flush routine, the panel's dose-integrity/calibration-age status, and periodic verify-doses into a measuring cup. StallGuard via the TMC2209 diag output is a plausible v2 detector; it is not wired here.
7. **`restore_value` writes flash.** Every config edit and each of ~144 daily `dosed_today_ml` updates lands in NVS. ESPHome mitigates (writes are rate-limited/deferred via the preferences `flash_write_interval`, and ESP32 NVS wear-levels), so at this write rate the flash outlives the pump tube by orders of magnitude — noted for honesty, not for worry. Do not "improve" the design by persisting per-second state.

---

Reference files read: `/home/reece/.claude/plans/i-now-want-to-vivid-gray.md` (approved Dosing Pumps plan), `/home/reece/Workspaces/Ragnars_Reef/docs/manual/kalk-doser-feature-spec.md` (original brief incl. Appendix A), `/home/reece/Workspaces/Ragnars_Reef/docs/manual/awc-esphome-3pump-design.md` (house style + master-relay v2 mitigation), `/home/reece/Workspaces/Ragnars_Reef/docs/manual/awc-esphome-reference.yaml` (2-pump merge target; pin claims at lines 95/114/177).
