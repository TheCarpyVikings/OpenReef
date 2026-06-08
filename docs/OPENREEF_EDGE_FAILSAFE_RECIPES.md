# OpenReef ESPHome Edge Failsafe Recipes

OpenReef Core can watch, alert, and coordinate Home Assistant. Edge failsafes are the extra layer for life-support gear that should still behave safely when Home Assistant, WiFi, a phone app, or OpenReef itself is unavailable.

This is not a plug-and-play wiring guide. Treat these recipes as the blessed OpenReef safety pattern for a future curated kit:

- local sensor input first
- relay default state chosen deliberately
- Home Assistant exposes a guarded switch, not the raw relay
- heater and ATO relays fail off
- return pump wiring should prefer a physical/default-on path
- every recipe is bench-tested before it touches a live tank

The example file is [openreef_edge_failsafes.example.yaml](../esphome/openreef_edge_failsafes.example.yaml).

## Recipe 1: Heater Guard

Purpose: a heater relay must turn off locally if the local temperature probe is missing or above the cutoff.

Pattern:

- Use a local DS18B20/1-Wire or equivalent water temperature probe on the ESPHome device.
- Put the physical heater relay behind an internal raw switch with `restore_mode: ALWAYS_OFF`.
- Expose a template switch called `Heater Guarded`.
- Only allow the guarded switch to turn the raw relay on when the local temperature is valid and below the configured enable threshold.
- Re-check every few seconds and force the raw relay off if the probe is missing or the cutoff is reached.

OpenReef Trust Check should only be marked as reviewed after the relay has been bench-tested with probe disconnected, probe below threshold, and probe above cutoff.

## Recipe 2: ATO Guard

Purpose: a top-off pump must not be able to run indefinitely, and local high-water/leak inputs must stop it without Home Assistant.

Pattern:

- Put the ATO pump relay behind an internal raw switch with `restore_mode: ALWAYS_OFF`.
- Expose a template switch called `ATO Guarded`.
- The guarded switch starts a local script, not the raw relay directly.
- The script turns the pump on, waits a short maximum runtime, then forces it off.
- Local high-water and leak binary sensors stop the script and force the pump off.

Start with a short runtime. If the tank needs longer top-off, prefer repeated short windows over one long unattended run.

## Recipe 3: Return Pump Guard

Purpose: return flow should not depend on a WiFi command being delivered at exactly the right time.

Pattern:

- Prefer wiring that leaves the return pump powered when the controller is absent, where the hardware allows it.
- If a relay is used, choose and bench-test the restore mode deliberately. The example uses `RESTORE_DEFAULT_ON`, but that is only safe if the board, relay module, and plumbing have been verified.
- Do not put a return pump on a relay that can boot into an unknown/off state without a physical fallback.

Return-pump edge control is hardware-sensitive. For beta, the safe OpenReef default is to document and review it rather than auto-generate a pin map.

## Trust Check Review

In OpenReef Core, go to Settings -> System Check -> Edge Failsafes and record:

- whether edge failsafes have been reviewed
- which recipes are deployed for heater, ATO, and return pump
- the review date
- a short hardware note

Trust Check will warn when heater, ATO, or return-pump equipment is armed but the matching edge-failsafe recipe has not been marked as reviewed.

## Validation Checklist

- Bench-test every relay before plugging in life support.
- Confirm relay polarity and boot state after power loss.
- Confirm heater relay turns off when the temperature probe is disconnected.
- Confirm heater relay turns off above the cutoff temperature.
- Confirm ATO relay turns off after the maximum runtime.
- Confirm high-water input stops ATO locally.
- Confirm leak input stops ATO locally.
- Confirm Home Assistant can control only the guarded/template switches.
- Confirm raw relay entities are internal or hidden from normal dashboards.
- Record the review date in OpenReef Trust Check.

## ESPHome Components Used

The example uses standard ESPHome primitives: GPIO switches with `restore_mode`, template switches, scripts, GPIO binary sensors, the 1-Wire bus, and `dallas_temp` sensors.

Official references:

- https://esphome.io/components/switch/
- https://esphome.io/components/switch/gpio
- https://esphome.io/components/switch/template/
- https://esphome.io/components/script.html
- https://esphome.io/components/binary_sensor/
- https://esphome.io/components/one_wire/
- https://esphome.io/components/sensor/dallas_temp/
