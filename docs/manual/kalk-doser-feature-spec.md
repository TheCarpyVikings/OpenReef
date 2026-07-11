# OpenReef Feature Brief: Kalkwasser Doser Subsystem

> **Audience:** AI coding agent working inside the OpenReef repository.
> **Requested deliverable:** an implementation plan first — not code. Explore the codebase, then propose the plan and surface open questions before implementing anything.
>
> **Status note (2026-07-11):** the plan this brief requested has been produced and approved — see the Dosing Pumps feature plan. The scope grew from this single-channel kalk brief to a multi-channel Dosing page; this document is preserved as the original firmware/product contract for the kalk channel. Firmware amendments to Appendix A are specified in `kalk-doser-esphome-design.md`.

---

## 1. How to use this document

1. Read this brief in full.
2. Explore the repository to locate the existing **Automatic Water Change (AWC)** feature: its settings panel, state storage, entity-binding pattern, calibration workflow, and any ESPHome configs stored in the repo.
3. Produce an **implementation plan** that maps every requirement in Sections 4–8 onto the existing architecture, reusing AWC patterns and components wherever they exist.
4. List assumptions and open questions (Section 10 is a starting set) at the end of the plan.
5. Do not begin implementation until the plan is reviewed by the user.

The AWC feature is the design precedent for everything here. When this document says "match the AWC pattern," that pattern is authoritative over any generic suggestion in this brief.

---

## 2. Context

OpenReef is the user's custom reef-aquarium controller built on Home Assistant with ESP32 devices running ESPHome. An existing AWC subsystem provides the reference implementation: a settings panel with entity pickers, inline pump calibration ("Calibrate drain/fill" buttons with ran-seconds/measured-ml inputs and a "Not calibrated yet" state), safety sensors and thresholds, ATO coordination toggles, quiet hours, and a scheduler.

This feature adds a second dosing subsystem: **continuous kalkwasser (limewater) micro-dosing** via a stepper-motor peristaltic pump (Kamoer KPHM100-STB10) driven by a TMC2209 stepper driver over UART, controlled by the **same ESP32 device** that runs the AWC.

Default operating point: **300 ml/day delivered as ~2.08 ml doses every 10 minutes** (144 doses/day). All values are user-tunable at runtime.

---

## 3. Division of responsibility

| Layer | Owns | Notes |
|---|---|---|
| ESPHome firmware (Appendix A) | Dose execution, per-dose safety guard evaluation, daily-total accounting, midnight reset, calibration motion (fixed 100-revolution run), persistence across reboot | Guard enforcement is firmware-side by design — dosing must fail safe if HA is offline |
| Home Assistant / OpenReef | Settings panel (configure the firmware's entities), diagnostics display, AWC-coordination automation, tube-runtime tracking, calibration math UX | Panel writes to the firmware's `number`/`switch` entities; it does not implement its own dosing loop |

If the plan finds a better split given the existing architecture, propose it — but firmware-side guard enforcement is non-negotiable.

---

## 4. Firmware entity contract

The ESPHome config (Appendix A) exposes these entities. Exact HA `entity_id` values depend on the device name after flashing — **the panel must use entity pickers (AWC pattern), never hardcoded entity IDs.**

### Configuration entities (read/write)

| Entity (ESPHome name) | Type | Range / unit | Default | Semantics |
|---|---|---|---|---|
| Kalk Dose Volume (ml) | number | 0.1–10 ml, step 0.01 | 2.08 | Volume per dose |
| Kalk Dose Interval (min) | number | 1–240 min, step 1 | 10 | Minutes between dose attempts |
| Kalk Max Daily (ml) | number | 0–1000 ml, step 5 | 300 | Hard daily cap enforced in firmware |
| Kalk Dose Speed (steps/s) | number | 50–2000 | 400 | Stepper speed during a dose |
| Kalk Run Current (A) | number | 0.1–1.0 A, step 0.05 | 0.6 | TMC2209 run current, written over UART |
| Kalk pH High Stop | number | 7.5–9.0, step 0.05 | 8.40 | Doses skipped while tank pH ≥ this value |
| Kalk Dosing Enabled | switch | on/off | off | Master enable |

### Action entities (buttons)

| Entity | Action |
|---|---|
| Kalk Prime / Test (run 5s) | Runs the pump ~5 s for priming/direction checks |
| Kalk Dose Now (one dose) | Executes one guarded dose immediately |
| Kalk Calibrate 100 rev | Runs exactly 320,000 microsteps (100 revolutions) for volumetric calibration |

### State entities (read-only)

| Entity | Type | Semantics |
|---|---|---|
| Kalk Dosed Today (ml) | sensor | Accumulated total, resets at midnight |
| Kalk Reservoir Low | binary_sensor | Optional float switch; doses skipped while on |

### Firmware-internal values needing a panel pathway

| Value | Current form | Requirement |
|---|---|---|
| `steps_per_ml` | ESPHome global, placeholder 11851.0 | Must become runtime-settable from the panel's calibration workflow. Preferred: add a template `number` bound to the global in the firmware YAML (plan should specify this change). Reflash-to-set is not acceptable as the end state. |
| Tank pH source | Hardcoded `sensor.openreef_ph` in firmware | Panel should expose a pH-entity picker; plan must propose how the selection reaches firmware (e.g., regenerate/parameterise the YAML, or an HA-side mirror sensor) consistent with how AWC handles entity selection today |

---

## 5. Settings panel requirements

Create a **Kalkwasser Doser** panel section following the AWC panel's structure, styling, and interaction patterns exactly (cards with section headers, toggles with one-line descriptions, entity dropdowns defaulting to "— none —", numeric fields with helper text, calibrate buttons with status line).

### 5.1 Core setup
- Master enable toggle ("Master switch for kalk dosing and safety guards")
- Entity pickers: dosing device/switch, pH sensor, reservoir-low sensor (all optional except the doser itself)
- Daily volume target (ml/day)

### 5.2 Dosing schedule
- Interval (minutes) field
- **Derived, read-only per-dose volume**: `daily ÷ (1440 ÷ interval)` displayed live (e.g., "300 ml/day @ 10 min = 2.08 ml/dose") and written to the firmware's dose-volume entity on save
- Optional (flag as Phase 2 in the plan): day/night weighting to bias dosing toward lights-off hours

### 5.3 Calibration (mirror AWC's calibrate workflow)
- "Run calibration (100 revolutions)" button — triggers the firmware button
- "Measured (ml)" input
- Derived `steps_per_ml = 320000 / measured_ml`, displayed, then written to firmware
- Persistent "Not calibrated yet" state that **blocks scheduled dosing** until first calibration is stored (match AWC's uncalibrated behaviour)
- Store calibration history (at minimum last value + timestamp) for drift comparison

### 5.4 Safety and guards
- pH high-stop threshold field (default 8.40)
- Max daily volume field (default 300)
- Reservoir-low sensor picker
- **"Suspend during water changes"** toggle: kalk dosing pauses while an AWC run is active (reuse the mechanism behind AWC's "Suspend ATO during active water changes" — locate it in the codebase)
- Optional: quiet-hours window (AWC has this pattern; include for consistency, note pump is near-silent)

### 5.5 Diagnostics
- Dosed today (ml) with progress against the daily cap
- Last dose timestamp and last skip reason if surfaced (skips are logged firmware-side)
- **Tube runtime tracking**: accumulate pump run-hours HA-side (derivable from dose count × dose duration, or a history stat); warn when approaching **1000 h** (manufacturer tube life) — surface as "Replace pump tube" warning with a reset-after-replacement action

---

## 6. Behavioural requirements (firmware-enforced, panel-visible)

Every dose attempt evaluates, in order: master enable → reservoir not low → pH < stop → (dosed_today + dose_volume) ≤ daily cap. Any failure skips the dose and logs the reason. Additional required behaviours:

- Daily total resets at local midnight; total and all settings survive reboot
- Pump idles freewheeling between doses (silent, no holding current)
- If the pH sensor is unavailable/unknown, the pH guard **fails safe (no dosing)**
- AWC-suspend guard (Section 5.4) must prevent doses during an active water change

---

## 7. Constraints

- **Everything user-facing is runtime-configurable.** No dosing parameter may require a firmware reflash after initial setup (the `steps_per_ml` pathway in §4 closes the last gap).
- Reuse existing OpenReef components, state patterns, and styling — introduce no new UI framework or state mechanism without justification in the plan.
- The ESP32 is shared with the AWC. Firmware pin assignments are fixed and must not be changed: UART TX GPIO17, RX GPIO16, driver enable GPIO14, index GPIO13, reservoir float GPIO4. GPIO25/26/27/32/33 belong to the AWC. *(Superseded: the repo's AWC reference YAML already uses GPIO16/17/14 — see the pin audit in `kalk-doser-esphome-design.md`.)*
- The Appendix A YAML merges into the existing AWC device config (single `esphome:`/`wifi:`/`api:` block). If the repo stores that config, the plan should include the merge.
- Units metric, ml and minutes, matching AWC conventions.

---

## 8. Acceptance criteria

1. Panel renders in the OpenReef UI, visually consistent with the AWC panel.
2. With entities picked and calibration stored, changing daily volume or interval updates the firmware entities and doses change size/frequency accordingly — no reflash.
3. Uncalibrated state blocks scheduled dosing and is clearly indicated.
4. Calibration workflow: run button → measured input → derived steps_per_ml stored to firmware → verified by a subsequent dose.
5. Each guard (enable off, pH ≥ stop, cap reached, reservoir low, AWC active) demonstrably prevents dosing, and the panel reflects the blocking state.
6. Dosed-today, cap progress, and tube-runtime warning display correctly; tube counter is resettable.
7. All settings persist across HA restarts and ESP32 reboots.

---

## 9. Out of scope

- Hardware assembly, wiring, and bench calibration procedure (covered by a separate human build guide)
- Multi-pump/multi-channel dosing abstractions (single kalk channel only, but note in the plan if a generic "doser" abstraction falls out naturally) *(Superseded: the approved plan builds the multi-channel abstraction from day one.)*
- Alkalinity/Ca dosing math or tank-chemistry modelling

---

## 10. Open questions for the implementation plan

1. Where does the AWC panel live and what component/state patterns does it use? Enumerate the reusable pieces.
2. How does the AWC persist settings (HA helpers, custom storage, ESPHome numbers)? Follow the same route.
3. How is "an AWC run is active" represented today, for the suspend guard to consume?
4. What is the cleanest pathway for panel-selected entities (pH sensor) to reach firmware guards, given how OpenReef manages its ESPHome configs?
5. Is there an existing runtime/hours-counter pattern (e.g., for AWC pumps) to reuse for tube-life tracking?
6. Does the repo store the ESPHome device YAML? If yes, include the Appendix A merge in the plan; if no, state that firmware is flashed out-of-band and the plan covers HA-side only.

*(All six are answered in the approved Dosing Pumps plan.)*

---

## Appendix A — ESPHome firmware config (reference)

Merge into the existing AWC ESP32 device YAML. Placeholders: `steps_per_ml` initial value is uncalibrated; `sensor.openreef_ph` must become the user's real pH entity (see §4). **Superseded by the amended YAML in `kalk-doser-esphome-design.md`; preserved here as the original contract.**

```yaml
external_components:
  - source: github://slimcdk/esphome-custom-components
    components: [ tmc2209_hub, tmc2209, stepper ]

uart:
  id: tmc_uart
  tx_pin: GPIO17
  rx_pin: GPIO16
  baud_rate: 500000

globals:
  - id: steps_per_ml
    type: float
    restore_value: true
    initial_value: '11851.0'   # placeholder until calibrated
  - id: dosed_today_ml
    type: float
    restore_value: true
    initial_value: '0'

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

switch:
  - platform: template
    name: "Kalk Dosing Enabled"
    id: kalk_enabled
    optimistic: true
    restore_value: true

sensor:
  - platform: homeassistant
    id: tank_ph
    entity_id: sensor.openreef_ph      # replace with the user's pH entity
  - platform: template
    name: "Kalk Dosed Today (ml)"
    id: kalk_dosed_today
    unit_of_measurement: "ml"
    accuracy_decimals: 2
    lambda: 'return id(dosed_today_ml);'
    update_interval: 30s

binary_sensor:
  - platform: gpio
    name: "Kalk Reservoir Low"
    id: kalk_reservoir_low
    pin:
      number: GPIO4
      mode:
        input: true
        pullup: true
    filters:
      - delayed_on: 2s
      - delayed_off: 2s

stepper:
  - platform: tmc2209
    id: kalk_driver
    max_speed: 400 steps/s
    acceleration: 1000 steps/s^2
    deceleration: 1000 steps/s^2
    rsense: 110 mOhm
    vsense: False
    address: 0x00
    enn_pin: GPIO14
    index_pin: GPIO13
    on_boot:
      - tmc2209.configure:
          microsteps: 16
          interpolation: true
      - tmc2209.currents:
          standstill_mode: freewheeling
          run_current: 0.6A
          ihold: 0
          iholddelay: 0
          tpowerdown: 0

script:
  - id: do_one_dose
    mode: single
    then:
      - if:
          condition:
            and:
              - switch.is_on: kalk_enabled
              - binary_sensor.is_off: kalk_reservoir_low
              - lambda: 'return id(tank_ph).state < id(kalk_ph_stop).state;'
              - lambda: |-
                  return (id(dosed_today_ml) + id(kalk_dose_ml).state)
                         <= id(kalk_max_daily_ml).state;
          then:
            - stepper.set_speed:
                id: kalk_driver
                speed: !lambda 'return id(kalk_speed).state;'
            - stepper.report_position:
                id: kalk_driver
                position: 0
            - stepper.set_target:
                id: kalk_driver
                target: !lambda |-
                  return (int)(id(kalk_dose_ml).state * id(steps_per_ml));
            - globals.set:
                id: dosed_today_ml
                value: !lambda 'return id(dosed_today_ml) + id(kalk_dose_ml).state;'
          else:
            - logger.log: "Kalk dose skipped (disabled / pH / cap / empty)"
  - id: reset_daily_total
    then:
      - globals.set:
          id: dosed_today_ml
          value: '0'

button:
  - platform: template
    name: "Kalk Prime / Test (run 5s)"
    on_press:
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
    on_press:
      - script.execute: do_one_dose
  - platform: template
    name: "Kalk Calibrate 100 rev"
    on_press:
      - stepper.set_speed:
          id: kalk_driver
          speed: !lambda 'return id(kalk_speed).state;'
      - stepper.report_position:
          id: kalk_driver
          position: 0
      - stepper.set_target:
          id: kalk_driver
          target: 320000     # 200 steps x 16 microsteps x 100 revolutions

time:
  - platform: homeassistant
    id: ha_time
    on_time:
      - seconds: 0
        minutes: 0
        hours: 0
        then:
          - script.execute: reset_daily_total

interval:
  - interval: 60s
    then:
      - if:
          condition:
            lambda: |-
              static int elapsed = 0;
              elapsed++;
              if (elapsed >= (int)id(kalk_interval_min).state) {
                elapsed = 0;
                return true;
              }
              return false;
          then:
            - script.execute: do_one_dose
```

## Appendix B — Hardware summary (for context only)

| Item | Detail |
|---|---|
| Pump | Kamoer KPHM100-STB10, bipolar stepper peristaltic, ~0.27 ml/rev nominal (calibration is authoritative) |
| Driver | BigTreeTech TMC2209 V1.3, UART mode, address 0x00, R_SENSE 0.11 Ω, StealthChop + interpolation |
| Power | Existing 12 V PSU (fused 1 A) for motor; ESP32 3.3 V for driver logic |
| Chemistry | Saturated kalkwasser (Ca(OH)2); dosed above waterline with siphon break; pH guard is the primary chemical safety |
