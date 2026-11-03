# Heater health monitoring

OpenReef can learn a heater's normal electrical and temperature behaviour and
notify the keeper when a check or an identification is needed. It observes the
existing controller; it never operates a switch or changes a thermostat setting.

## Setup

1. Map the tank and room temperature sensors in Settings.
2. In Settings → Equipment, map the device's **Power** sensor.
3. Under **Heater health monitoring**, select what the power monitor measures:
   heater only (including an external thermostat), thermostat + heater + fan, or
   thermostat + heater + chiller. Save settings.
4. Open Energy → Heater health. Learning proceeds during normal use.

Arming the equipment is not required. A shared supply must contain only the
controller and its heating/cooling equipment. Monitor each physical supply once.
Multiple heaters on one supply are assessed as a group, not individually.

If Home Assistant exposes the controller as a climate entity with `hvac_action`,
the optional climate mapping can identify active loads automatically. Otherwise,
shared supplies prompt the user to identify recurring wattage patterns as heater,
cooling equipment or standby. Do not guess an unfamiliar pattern. Unassigned
periods remain excluded from the heater reference. Wattage alone cannot prove a
load's purpose; variable-speed or overlapping loads may remain ambiguous.

Prompts appear in Home Assistant and on the Energy screen. A configured existing
**mode notification target** also receives phone notifications. Warnings are
deduplicated; acknowledging an issue keeps its reference and warning visible.
Critical temperature excursions take precedence over learning/health status.

## Learning and interpretation

- Establishes a reference from at least 12 complete heating cycles spanning seven
  days. These are initial engineering defaults, not a validated failure forecast.
- Tracks active power and completed temperature-response cycles. Compares warming
  rates at similar tank-to-room temperature gaps, starting temperatures and times
  of day. Colder-room runtime alone does not reduce a health indicator.
- Retains the original reference for familiar conditions; healthy power/control
  behaviour can add coverage for new room conditions without replacing old data.
- Reports **active power versus reference**, rather than an efficiency or lifespan
  percentage. A heater that has not run recently has no current power comparison.
- Learns heating independently of cooling season. Cooling labels and estimated
  energy are supported; cooling performance/failure prediction is not scored.
- Requires three completed cycles for persistent power, cut-off temperature or
  warming-rate change warnings. Continuous heating above the learned stopping
  temperature is checked separately. Explicit controller heat demand without an
  active load prompts a check after 15 observed minutes.
- Reference learning excludes known maintenance/feed modes, automatic water-change
  operation and its holdoff, discontinuous data, abrupt temperature changes and
  out-of-range temperature cycles. Temperature warnings remain active.
- Missing/stale readings are unknown, never zero. Readings need valid W/kW and
  Celsius/Fahrenheit units and a report within 20 minutes. Flat values can remain
  valid when the entity continues reporting (`last_reported`).

The heater-only and controller-telemetry paths treat input at or below 5 W as
standby. Very small heaters, overlapping fan/standby readings and controllers with
unusual standby power need separate metering or clearer telemetry. Short/noisy
power events are not reference cycles. Slow reporting can miss switching events;
use a meter that reports load changes promptly.

Energy figures are explicitly **estimates from observed power intervals**, not an
allocation of the smart plug's cumulative Wh counter. Controller standby is
subtracted when identified. The card reports observed hours, unassigned energy
and heating time within observed time; gaps are excluded. Existing measured
per-device energy remains available beside the monitoring cards.

## Changes and storage

Use **Heater replaced** or **Thermostat / probe changed** on the card after a real
change. A confirmation explains what will be relearned. The previous reference
is retained. Heater replacement preserves identified cooling/standby patterns;
a settings change preserves all identified power patterns.

The monitor uses a versioned Home Assistant Store at
`.storage/openreef.heater_health.<entry_id>`. Data is bounded to 160 reference
cycles, 12 recent cycles, eight power patterns and 24 hourly energy buckets per
equipment item, plus one previous reference. Ordinary sensor updates are flushed
at most about once a minute; responses and new notifications persist immediately.
Restarts discard partial cycles and never estimate heating during downtime.
Changing sensor bindings starts a new reference; disabling monitoring preserves
history for later use. No runtime learning state is written into panel settings.

## Verification and limits

Run `python3 tests/test_heater_health.py` and
`node tests/test_panel_heater_health.mjs` from the repository root. They use
simulated cycles, fake Home Assistant entities/services and the real panel class.
They never connect to aquarium hardware.

Before broad release, observe actual histories from heater-only and shared Inkbird
installations across room conditions, and measure false alarms. The initial 15%
power and 35% warming-rate change thresholds require field validation. Circulation,
evaporation, other heat sources, sensor drift and voltage changes can affect the
signals; alerts request investigation rather than automatically recommending a
replacement. Sudden failures may have no measurable precursor. Independent
temperature alarms and the existing thermostat remain necessary.
