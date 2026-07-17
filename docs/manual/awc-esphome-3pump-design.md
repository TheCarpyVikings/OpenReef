<!-- Generated from OpenReef AWC micro-change design workflow, 2026-07-06. Reference design (not drop-in). Companion to docs/awc-multisource-livefood-brainstorm.md. -->

# OpenReef AWC — 3-Pump High-Frequency Micro-Change Node (reference firmware + wiring)

**Status:** reference design (adapt to your board/wiring — not drop-in). Supersedes the 2-pump [`awc-esphome-reference.yaml`](/home/reece/Workspaces/Ragnars_Reef/docs/manual/awc-esphome-reference.yaml) for Reece's 52 L rig: **3 pumps** (drain, fresh-fill, live-food-fill), **3 reservoirs** (20 L fresh, 5 L live-food, 20 L drain), tuned for **hourly tens-of-mL changes**.

> **STAGE D (2026-07-15): superseded for the build path.** The single-ESP32-S3
> consolidation is now the build authority: flash
> [`reefnode-s3-reference.yaml`](reefnode-s3-reference.yaml) and wire to the pin
> budget in [`reefnode-s3-design.md`](reefnode-s3-design.md) §1 (this doc's pin
> table predates the S3 map). The wiring theory below (MOSFET stages, master
> relay, plumbing, safety reasoning) still stands and is worth reading — and the
> HA-timed chaser sketched here is superseded by the firmware-sequenced chaser
> in the reefnode (see reefnode-s3-design.md §4).

The 2-pump stance is unchanged and non-negotiable: **hard safety lives in firmware.** Wi-Fi/HA can drop and no pump is ever stranded ON. OpenReef orchestrates, accounts litres, sequences the live-food dose + chaser, and mirrors these caps. This node is the last line that keeps working when the network doesn't. All three sources are **salt-matched to display (~35 ppt)**, so `net_salt ≈ 0` — the firmware doesn't need to know or care about salinity; it only enforces level/flood/dry-run/clog safety.

---

## 1. What changed from the 2-pump reference

| Area | 2-pump reference | This 3-pump node |
|---|---|---|
| Pump GPIO switches | drain, fill | **drain, fresh-fill, live-food-fill** (3×, same latch/guard/watchdog pattern) |
| Reservoir floats | fresh-empty, waste-full | **fresh-empty, live-food-empty, waste-full** (3×) |
| Flood backstops | leak, display-high | leak, display-high (unchanged) |
| Switching element | GPIO → relay/MOSFET | **MOSFET per channel** (24–72 starts/day → no contact wear) |
| Fail-ON mitigation | "v2 backlog" | **shipped here**: master power-cut relay in series on separate logic + hardware leak interlock |
| Watchdog sizing | 180 s (full change) | **~45 s** (sized to the *micro-dose*, not a litre fill) |
| Live-food line | n/a | **saltwater chaser flush after every dose** (shared manifold + check valves) |

---

## 2. Plumbing topology & the live-food flush

Three independent peristaltic paths. Peristaltic heads self-seal when stopped, so no open siphons — a stuck pump is bounded by *time*, not a runaway drain.

```
 ┌──────────────┐   drain pump                     ┌──────────┐
 │  DISPLAY /   │───────────────[KPHM100]──────────▶│ 20 L     │
 │   SUMP       │                                   │ WASTE    │
 │  (52 L tank) │◀──────────[Y]◀──[CV]──[KPHM100]───┤ 20 L FRESH (35 ppt)
 │              │            │                       └──────────┘
 │  display_high│            └──[CV]◀──[KPHM100]────┤ 5 L LIVE-FOOD (35 ppt,
 └──────┬───────┘         shared outlet manifold     │  phyto+pods+nauplii,
        │ leak float                                  │  aerated, refreshed daily)
   ═════╧═════ drip tray (under the whole rig)
```

**Live-food line flush (the clog defense).** Live organisms + phyto left stagnant in the delivery tube die, foul, and clog. Two supported topologies:

- **Recommended — shared outlet manifold + fresh chaser (Option A).** The fresh-fill and live-food-fill tubes join at a **Y close to the tank**, each branch fitted with a **check valve (CV)** so nothing back-flows into the wrong reservoir. **Mount the live-food pump right at the Y** so the live-food-only upstream segment is only a few mL. After every live-food dose, run a short **fresh-fill chaser** that pushes the residual live-food slug out of the shared downstream segment and leaves it full of clean saltwater. At hourly cadence with dilute, daily-refreshed cultures and a short upstream tube, this is more than enough. Because the fresh source is salt-matched, the chaser is **salinity-neutral** — it only adds to the level ledger (offset by the drain), never the salt ledger.

- **Dedicated flush (Option B, for larger/less-frequent live-food doses).** A 2-way solenoid (or a 4th micro-pump) on the live-food pump's **suction** side selects live-food reservoir *or* a saltwater flush feed, so the chaser flushes the pump head itself. More complete, more parts, more failure modes — not needed for hourly mL doses; reserve for other users.

**Who owns the sequence.** Primary owner is **OpenReef** — it turns on `livefood_pump` for the dose, then turns on `fresh_pump` for the calibrated chaser, so **both volumes land in the litre ledger**. No new firmware primitive is required (backend just drives the existing `fresh_pump` switch for N seconds). For the **local-first** case (network down mid-dose), the YAML below includes an **optional** firmware fallback `livefood_flush` script that auto-runs a bounded chaser on `livefood_pump` turn-off — disabled-by-default in spirit (it desyncs the ledger, which is acceptable only because the network is already down). Pick **one** owner in normal operation.

---

## 3. Per-channel MOSFET wiring (×3, identical)

Low-side N-channel switch, one per pump. **Buy the brushed `KPHM100-HBB10` (12 V) or `-HAB10` (24 V)** — MOSFET-drivable. Brushless (3-wire ESC) and stepper variants are *not* MOSFET loads.

```
        +Vpump (12 V HB / 24 V HA)  ── from MASTER RELAY output (§4)
             │
             ├──────────────┐
           ══╪══ 100–470 µF │           SS34 cathode → +Vpump
           electrolytic     │        ┌───►|───┐   (flyback, MANDATORY)
        (per rail, once)  ┌─┴─┐      │        │
                          │ M │  KPHM100 brushed motor
                          └─┬─┘      │        │
                        ═╪═ 100 nF   └────────┘  SS34 anode → drain
                          │ (across motor)
                          │  = MOSFET DRAIN
                        ┌─┴─┐
   GPIO ──[150 Ω]───────┤G  │  AO3400A (SMD) or IRLB8721PBF (TO-220)
              │         │  S├── GND (shared with ESP32-S3 ground)
           [10 kΩ]      └───┘
              │  gate pulldown → GND
             GND     (pump OFF while GPIO floats at boot/reset)
```

**Per-channel BOM**

| Part | Value / P-N | Why |
|---|---|---|
| MOSFET | `AO3400A` (SMD) or `IRLB8721PBF` (TO-220) | *True* logic-level, fully on at 3.3 V. **Not** `IRLZ44N` (only partly enhanced at 3.3 V). 0.5 A run / ~2 A stall → no heatsink. |
| Flyback diode | `SS34` (3 A/40 V Schottky) or `1N5819` | Across the motor, cathode→+Vpump. **#1 DIY motor-switch failure** if omitted. |
| Gate series R | 150 Ω | Tames GPIO edge / gate ring. |
| Gate pulldown | 10 kΩ → GND | **Flood safety, not polish** — guarantees pump OFF while the S3 GPIO floats during boot/reset. |
| Motor cap | 100 nF ceramic across motor | Brush noise. |
| Rail cap | 100–470 µF electrolytic on +Vpump | Inrush; one per rail, not per channel. |

**Power discipline:** feed the ESP32-S3 from its **own** buck/USB off the 12 V, share **only ground**. Pump inrush on a shared rail trips the S3 brownout (~2.4–2.7 V) mid-dose. Volume is controlled by **time at full speed** (weigh-calibrate ml/s) — never PWM.

---

## 4. Master power-cut relay + independent leak interlock (the fail-ON mitigation)

Neither a MOSFET nor a relay is fail-safe: a shorted/gate-floating MOSFET fails **ON**, a welded relay fails **ON**, and no GPIO stops a stuck actuator. So we add a **second switching element in series on separate logic**, plus a **hardware** leak kill.

**Master relay = energize-to-run (NO contacts), on its own GPIO + driver.** Firmware must *actively hold it enabled*; anything that de-asserts it (trip, reboot, crash, brownout, power loss) **opens it and cuts power to all three pump rails**. That's fail-OFF for the master — exactly the mitigation. A relay is fine *here* (unlike per-pump) because it actuates only on trips/boot, not 24–72×/day, so contact wear is a non-issue.

The **leak float is wired into the coil circuit in hardware**, independent of firmware — a wet leak physically breaks the relay-enable path no matter what the S3 is doing.

```
 GPIO7 (master_enable) ──[150 Ω]──┤G  AO3400A ┐
                          [10 kΩ]  │           │ drives relay coil low-side
                            │      └S─ GND     │
                           GND                 │
                                               ▼
   +12 V ──[ LEAK FLOAT NC ]──►(relay coil)────┘     (coil energizes only if
              (opens when wet)   flyback diode          BOTH firmware asserts
                                 across coil)           AND leak float is dry)

   Relay CONTACTS (NO):   +Vpump(raw) ──o  o──► +Vpump to all 3 MOSFET drains (§3)
                                       energized = closed = pumps powered
```

Enable requires **both** gates: (a) firmware `master_enable` HIGH **and** (b) leak-float NC closed (dry). Either failing drops the coil → contacts open → **all pump power cut**, regardless of firmware state. `trip_lock` also de-asserts `master_enable` in firmware, so a leak/overfill/overrun trip cuts the master rail too — belt *and* braces.

> Use a leak switch with a genuine **normally-closed dry contact** (float or a wet-sensor comparator board driving a small SPDT relay). The floating capacitive pads used for the *sensing* input in §5 are **not** a hardware interlock — the hardware kill needs a real contact.

---

## 5. GPIO map (ESP32-S3)

Outputs boot low; all in the safe range (GPIO4–18/21). **Avoid** GPIO0/3/45/46 (strapping), 26–32 (flash bus), 33–37 (octal), 19/20 (USB-JTAG).

| Signal | GPIO | Dir | Mode | Active |
|---|---|---|---|---|
| `drain_pump` MOSFET gate | GPIO4 | out | boots low | high = run |
| `fresh_pump` MOSFET gate | GPIO5 | out | boots low | high = run |
| `livefood_pump` MOSFET gate | GPIO6 | out | boots low | high = run |
| `master_enable` relay driver | GPIO7 | out | boots low (fail-OFF) | high = power enabled |
| `leak` (sensing) | GPIO15 | in | pulldown | high = wet |
| `display_high` cutoff | GPIO16 | in | pulldown | high = over-level |
| `fresh_empty` float | GPIO17 | in | pullup | on = empty |
| `livefood_empty` float | GPIO18 | in | pullup | on = empty |
| `waste_full` float | GPIO21 | in | pullup | on = full |

Leak also drives the **hardware** coil interlock (§4) in parallel with GPIO15's sensing.

---

## 6. The ESPHome node

```yaml
# =============================================================================
# OpenReef — Reference ESPHome config: 3-PUMP high-frequency micro-change AWC
# =============================================================================
# 3 peristaltic pumps (drain / fresh-fill / live-food-fill) + 3 reservoir floats
# + leak + display-high + a MASTER power-cut relay on separate logic. Hard safety
# lives LOCALLY: Wi-Fi/HA can drop and no pump is ever stranded ON.
#
# Safety model (mirror of OpenReef AWC, generalized to 3 pumps):
#   1. All MOSFET gates + master relay default OFF on boot/brownout (ALWAYS_OFF,
#      10k gate pulldowns). Master relay is energize-to-run => fail-OFF.
#   2. Per-pump MAX-RUNTIME watchdog, sized to the MICRO-DOSE, latched re-arm.
#   3. Leak = master kill: cut all pumps + drop master relay + latch. (Also a
#      HARDWARE leak interlock in the relay coil circuit — see the manual.)
#   4. Display high-level: cut BOTH fill pumps immediately + latch.
#   5. Floats: fresh-empty => block fresh-fill; livefood-empty => block
#      livefood-fill; waste-full => block drain. (Two-tier: pause & auto-resume.)
#   6. Debounced inputs + pull resistors so noisy/disconnected sensors can't
#      false-trigger.
#   7. Latched global lock: once tripped, stays off until a human clears it.
#
# RESIDUAL RISK: a welded relay AND a shorted MOSFET (two independent failures)
# still defeats every cutoff. Reservoir sizing is the ultimate backstop.
# =============================================================================

substitutions:
  node_name: openreef-awc3
  # Watchdogs are BACKSTOPS just above a normal MICRO-DOSE runtime — NOT a big
  # change. ~40 mL @ ~85 ml/min ≈ 28 s, so ~45 s catches a stuck pump fast.
  # Do NOT leave these at the old 180 s: at hourly cadence a 180 s stuck pump
  # dumps ~255 mL/hr into 52 L. Size to YOUR calibrated dose + margin.
  drain_max_runtime:    "45s"
  fresh_max_runtime:    "45s"
  livefood_max_runtime: "45s"
  flush_runtime:        "8s"   # optional local fallback chaser only

esp32:
  board: esp32-s3-devkitc-1

esphome:
  name: ${node_name}
  on_boot:
    # Fail-safe: master relay comes up OFF; only assert it once we confirm
    # we're not latched. Any hard trip / reboot drops it again.
    priority: -100
    then:
      - delay: 2s
      - if:
          condition:
            lambda: "return !id(awc_locked);"
          then:
            - switch.turn_on: master_enable

api:
ota:
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

logger:

globals:
  - id: awc_locked
    type: bool
    restore_value: no
    initial_value: "false"

script:
  - id: kill_all_pumps
    then:
      - switch.turn_off: drain_pump
      - switch.turn_off: fresh_pump
      - switch.turn_off: livefood_pump

  - id: trip_lock
    then:
      # Set the latch FIRST so on_turn_off flush handlers see it and skip.
      - globals.set: { id: awc_locked, value: "true" }
      - script.execute: kill_all_pumps
      - switch.turn_off: master_enable      # drop the series master rail too
      - logger.log:
          level: WARN
          format: "AWC HARD TRIP — pumps killed, master rail cut, node latched. Manual re-arm required."

  # Per-pump watchdogs. mode: restart => re-armed each turn-on, cancelled on a
  # normal turn-off, so they only fire on OVERRUN.
  - id: drain_watchdog
    mode: restart
    then:
      - delay: ${drain_max_runtime}
      - logger.log: "Drain pump exceeded max-runtime — tripping."
      - script.execute: trip_lock
  - id: fresh_watchdog
    mode: restart
    then:
      - delay: ${fresh_max_runtime}
      - logger.log: "Fresh-fill pump exceeded max-runtime — tripping."
      - script.execute: trip_lock
  - id: livefood_watchdog
    mode: restart
    then:
      - delay: ${livefood_max_runtime}
      - logger.log: "Live-food pump exceeded max-runtime — tripping."
      - script.execute: trip_lock

  # OPTIONAL local-first fallback: chase every live-food dose with a short fresh
  # flush so organisms don't sit stagnant in the shared line when the network is
  # down. In NORMAL operation OpenReef sequences this chaser instead (so the mL
  # land in the ledger). Guarded so it never runs during a trip or dry.
  - id: livefood_flush
    then:
      - if:
          condition:
            and:
              - lambda: "return !id(awc_locked);"
              - binary_sensor.is_off: fresh_empty
              - binary_sensor.is_off: display_high
          then:
            - switch.turn_on: fresh_pump
            - delay: ${flush_runtime}
            - switch.turn_off: fresh_pump

switch:
  # --- Master power-cut relay (energize-to-run, fail-OFF) -------------------
  - platform: gpio
    id: master_enable
    name: "AWC Master Power Enable"
    pin: GPIO7
    restore_mode: ALWAYS_OFF     # boot with pump rail DEAD until firmware arms

  # --- Pump 1: DRAIN --------------------------------------------------------
  - platform: gpio
    id: drain_pump
    name: "AWC Drain Pump"
    pin: GPIO4
    restore_mode: ALWAYS_OFF
    on_turn_on:
      - if:
          condition:
            or:
              - lambda: "return id(awc_locked);"
              - switch.is_off: master_enable
              - binary_sensor.is_on: waste_full
          then:
            - switch.turn_off: drain_pump
            - logger.log: "Drain blocked (latched, master off, or waste full)."
          else:
            - script.execute: drain_watchdog
    on_turn_off:
      - script.stop: drain_watchdog

  # --- Pump 2: FRESH-FILL ---------------------------------------------------
  - platform: gpio
    id: fresh_pump
    name: "AWC Fresh-Fill Pump"
    pin: GPIO5
    restore_mode: ALWAYS_OFF
    on_turn_on:
      - if:
          condition:
            or:
              - lambda: "return id(awc_locked);"
              - switch.is_off: master_enable
              - binary_sensor.is_on: fresh_empty
              - binary_sensor.is_on: display_high
          then:
            - switch.turn_off: fresh_pump
            - logger.log: "Fresh-fill blocked (latched, master off, fresh empty, or display high)."
          else:
            - script.execute: fresh_watchdog
    on_turn_off:
      - script.stop: fresh_watchdog

  # --- Pump 3: LIVE-FOOD-FILL ----------------------------------------------
  - platform: gpio
    id: livefood_pump
    name: "AWC Live-Food Pump"
    pin: GPIO6
    restore_mode: ALWAYS_OFF
    on_turn_on:
      - if:
          condition:
            or:
              - lambda: "return id(awc_locked);"
              - switch.is_off: master_enable
              - binary_sensor.is_on: livefood_empty
              - binary_sensor.is_on: display_high   # it's still a FILL — respect overfill
          then:
            - switch.turn_off: livefood_pump
            - logger.log: "Live-food blocked (latched, master off, livefood empty, or display high)."
          else:
            - script.execute: livefood_watchdog
    on_turn_off:
      - script.stop: livefood_watchdog
      # OPTIONAL local fallback flush — comment out if OpenReef owns the chaser.
      - script.execute: livefood_flush

  # --- Clear-latch template switch (OpenReef -> HA switch entity) -----------
  - platform: template
    name: "AWC Clear Lock"
    optimistic: true
    turn_on_action:
      - globals.set: { id: awc_locked, value: "false" }
      - switch.turn_on: master_enable        # re-arm the master rail
      - logger.log: "AWC lock cleared, master rail re-armed."

binary_sensor:
  - platform: gpio
    id: leak
    name: "AWC Leak"
    device_class: moisture
    pin: { number: GPIO15, mode: { input: true, pulldown: true } }
    filters: [ delayed_on: 200ms, delayed_off: 500ms ]
    on_press:
      - logger.log: "LEAK detected — master kill."
      - script.execute: trip_lock          # firmware kill; HARDWARE coil interlock backs this

  - platform: gpio
    id: display_high
    name: "AWC Display High-Level Cutoff"
    device_class: problem
    pin: { number: GPIO16, mode: { input: true, pulldown: true } }
    filters: [ delayed_on: 200ms, delayed_off: 500ms ]
    on_press:
      - logger.log: "Display high-level cutoff — fills killed."
      - switch.turn_off: fresh_pump
      - switch.turn_off: livefood_pump      # BOTH fill pumps, not just one
      - script.execute: trip_lock

  - platform: gpio
    id: fresh_empty
    name: "AWC Fresh Reservoir Empty"
    device_class: problem
    pin: { number: GPIO17, mode: { input: true, pullup: true } }
    filters: [ delayed_on: 300ms, delayed_off: 300ms ]
    on_press:
      - switch.turn_off: fresh_pump         # never dry-run the fresh pump

  - platform: gpio
    id: livefood_empty
    name: "AWC Live-Food Reservoir Empty"
    device_class: problem
    pin: { number: GPIO18, mode: { input: true, pullup: true } }
    filters: [ delayed_on: 300ms, delayed_off: 300ms ]
    on_press:
      - switch.turn_off: livefood_pump      # never dry-run the live-food pump

  - platform: gpio
    id: waste_full
    name: "AWC Waste Reservoir Full"
    device_class: problem
    pin: { number: GPIO21, mode: { input: true, pullup: true } }
    filters: [ delayed_on: 300ms, delayed_off: 300ms ]
    on_press:
      - switch.turn_off: drain_pump         # never overflow the waste reservoir
```

---

## 7. Micro-change tuning notes

- **24–72 starts/day → MOSFETs per pump.** Solid-state switching has no contacts to arc/weld across tens of thousands of hourly cycles/year. Reserve the relay for the **master cutoff** only, which actuates on trips/boot (rare) — so its contact life is a non-issue there while its fail-OFF behaviour is exactly what the master job needs.
- **Watchdogs sized to the DOSE, not a change.** ~40 mL @ ~85 ml/min ≈ **28 s**, so ~45 s catches a stuck pump within seconds. **Do not inherit the old 180 s** — at hourly cadence a 180 s stuck pump pushes ~255 mL/hr into 52 L. Re-derive from *your* calibrated ml/s after each recalibration (brushed heads drift and last ~800 h — a consumable on a nano that cycles this often).
- **Apply the `interceptMl` priming offset.** At 40 mL a few-mL startup slug is a **5–8 % systematic error**. On the firmware side keep the watchdog margin above `interceptMl + dose` time; on the OpenReef side, `runtime_for_volume_s` must add the intercept, not just `mlPerS` (flagged in the brainstorm as load-bearing at this scale).
- **Flush the live-food line after every dose.** Sequence: `livefood_pump` dose → brief dwell → **fresh chaser** through the shared Y so the residual live-food slug is pushed into the tank and the shared segment ends full of clean saltwater. Keep the live-food-only upstream tube **short** (pump mounted at the Y) so residual volume is a few mL. Owner = OpenReef in normal operation (chaser mL land in the ledger); the firmware `livefood_flush` script is the network-down fallback only. Salt-matched fresh ⇒ the chaser is salinity-neutral (level ledger only). Use the **widest bore** the head accepts and **dilute cultures only**.
- **Rethink ATO coordination at hourly frequency.** The shipped design suspends the ATO + 15-min hold-off *per change* — 24×/day that's a near-permanent ATO suspension. At mL scale a per-dose ATO suspension is likely unnecessary; that's an OpenReef-side change, not firmware, but the firmware imposes no such lock so it won't fight you.

---

## 8. OpenReef entity mapping

Map in **OpenReef → Water Change → Setup & calibration**. The live-food pump is configured as a **decoupled mL-dose channel** (`mode: dose`), *not* an AWC fill leg.

| OpenReef role | HA entity | Node object |
|---|---|---|
| Drain pump | `switch.awc_drain_pump` | `drain_pump` |
| Fresh-fill pump | `switch.awc_fresh_fill_pump` | `fresh_pump` |
| Live-food pump (mL-dose) | `switch.awc_live_food_pump` | `livefood_pump` |
| Master power enable | `switch.awc_master_power_enable` | `master_enable` |
| Clear-lock (re-arm) | `switch.awc_clear_lock` | template switch |
| Leak sensor | `binary_sensor.awc_leak` | `leak` |
| Display high-level cutoff | `binary_sensor.awc_display_high_level_cutoff` | `display_high` |
| Fresh-empty float | `binary_sensor.awc_fresh_reservoir_empty` | `fresh_empty` |
| Live-food-empty float | `binary_sensor.awc_live_food_reservoir_empty` | `livefood_empty` |
| Waste-full float | `binary_sensor.awc_waste_reservoir_full` | `waste_full` |

**Reservoir descriptors** (per the §E.1 data model — all opt-in beyond the base 2×2):

| Reservoir id | direction | capacity | level entity | extra fields |
|---|---|---|---|---|
| `fresh` | source | 20 L | `fresh_empty` | `salinityPpt: 35` |
| `livefood` | source | 5 L | `livefood_empty` | `salinityPpt: 35`, **`mixedAt`**, **`shelfLifeDays: 1`** |
| `waste` | sink | 20 L | `waste_full` | — |

`freshSourcePolicy` for his rig: cadence hourly, micro-dose; live-food is a **separate mL-dose schedule** riding the same hardware, not an alternating fill source. **Freshness/age tile + stale lockout** driven by `mixedAt`/`shelfLifeDays` (refreshed daily) — if the timestamp goes stale, OpenReef must **not** command `livefood_pump` (dead biomass = ammonia into 52 L of low-buffer water). The firmware can't see freshness; that lockout is OpenReef's job.

---

## 9. Honest residual-risk notes (3 pumps + live food)

1. **Two independent welds still win.** The master relay + per-pump MOSFETs are defense-in-depth, but a **welded master relay AND a shorted pump MOSFET** simultaneously defeats every cutoff — no GPIO stops a stuck actuator. Probability is low (two independent failures on separate logic), never zero. **Reservoir sizing is the ultimate backstop.**
2. **Reservoir sizing is a safety parameter.** A 20 L fresh reservoir fully dumped into 52 L is a **~38 % swing** — tank-crashing. OpenReef should warn/refuse any config where one reservoir's full contents exceed the safe single-swing cap. Peristaltic self-sealing bounds a stuck pump by *time*, so tight watchdogs + small per-dose volumes keep the realistic worst case to tens of mL — but the *reservoir* is what caps the catastrophe.
3. **Live-food clog (not crushing) is the mechanical failure mode.** Phyto/pods/nauplii survive the low-shear head; **adult brine shrimp clog and get chopped — excluded.** A partial clog makes the pump *run but move less* (or nothing) → the firmware watchdog trips on time overrun, but the dose was short and OpenReef dead-reckons full volume. Mitigate: widest bore, dilute cultures, **flush after every dose**, and bench-test survival (count live arrivals under magnification at 2 speeds) before trusting the feature.
4. **Stale live-food = ammonia dosing.** A room-temp 5 L reservoir fouls in 1–4 days (dead biomass → ammonia into a low-buffer 52 L). The daily refresh + `mixedAt` timestamp + **stale lockout** are load-bearing, and gentle aeration + a **mid-column pickup** are mandatory (a static reservoir stratifies to sludge or clear water — neither representative). This risk lives entirely in OpenReef/husbandry; firmware cannot detect it.
5. **Fill-side "runs but moves no water" is invisible mid-run.** Air-lock or a detached tube on either fill pump isn't detected — progress is dead-reckoned from calibrated rate. The display high-level cutoff still guards *overfill*, and sequential dosing avoids over-drain. Optional v3: a sump-low float for over-drain protection.
6. **Sensor fail-open at the HA layer.** A configured leak/high-level sensor going `unavailable` reads as "no hazard" in HA (`_awc_binary_on`). The **local-first ESPHome trip logic here is the real guard** — the firmware never depends on HA being up — but the OpenReef HA layer should still soft-block start/pause when a safety sensor is unavailable rather than fail open.

Don't run unattended changes larger than you'd be comfortable losing to a stuck pump. At hourly tens-of-mL that appetite is small by design — which is the whole point of the micro-change cadence.

---

Reference files read: `/home/reece/Workspaces/Ragnars_Reef/docs/manual/awc-esphome-reference.yaml`, `/home/reece/Workspaces/Ragnars_Reef/docs/manual/awc-hardware-and-safety.md`, `/home/reece/Workspaces/Ragnars_Reef/docs/awc-multisource-livefood-brainstorm.md`. (The path given in the task, `docs/awc-esphome-reference.yaml`, does not exist — the reference lives under `docs/manual/`.)
