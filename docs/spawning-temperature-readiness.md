# Full OpenReef temperature readiness — 6 September 2026

**Version 0.7.142 implements the temperature reliability fixes. Software verification passes; live hardware and tank operation have not been tested or deployed.** Reece will use full OpenReef with a tank temperature sensor and independent heat/cool thermostat. The first tester will use OpenReef daylight with Apex temperature/moonlight. The implementation uses standard HA temperature sensors and switch entities; it contains no Inkbird-specific code or fixed wiring scheme.

## Temperature behaviour

| Situation | Behaviour in 0.7.142 |
| --- | --- |
| A valid probe repeatedly reports the same value | Use `last_reported`, with older timestamp fields as a fallback. Unchanged values no longer falsely time out merely because `last_updated` is old. |
| Missing, stale, restored, non-finite, non-numeric or implausible readings | Request both thermal outputs OFF, verify the reported states and alert. Explicit Celsius or Fahrenheit units are required. |
| Failed or unfulfilled ON/OFF | Record the unresolved output, notify and retry on subsequent checks. Each service call has a ten-second timeout. An accepted service call is not reported as a confirmed switch. |
| Heating and cooling disagree | Stop unwanted outputs before starting the opposite one. A start requires every opposing or previous output to report OFF. If both report ON inside the hold band, request both OFF. |
| Slow daylight switching | Run thermal reconciliation first. A slow OFF on one thermal output does not prevent the other OFF request; those requests run concurrently. |
| Disarm, disable temperature, change bindings, or switch to Apex | Retain the previous outputs in a separate saved recovery record until OFF is confirmed. Unavailable old outputs keep retrying even with the feature disabled. |
| A program edit arrives during an ON command | Recheck the saved program after the await and request OFF if that start was superseded. Do not restore old settings. |
| Probe changes during switching | Re-read before and after a start; a new unsafe reading stops the output. |
| Integration unload/reload | Stop new starts, wait for the bounded in-flight check, then attempt verified thermal OFF. Unconfirmed releases remain saved for recovery on the next load. |
| A serious OFF failure follows an earlier drift warning | Use a separate alert cooldown so the earlier warning does not suppress the shutdown fault. |
| Month or year changes | Interpolate between the monthly table's 15th-day anchors. Offset handling avoids February day-clamping jumps. All preset/offset combinations change by less than 0.08°C per day in the tested 2027–2028 period. |
| A preset exceeds configured limits | Reject arming through the save API and stop thermal execution of incompatible legacy settings with a visible fault. Include the full ±0.2°C band. The code does not raise limits or silently clip the seasonal curve. |

The health sensor/panel includes pending thermal shutdowns, live sensor/output faults and cooling restart delay. A saved disarm is not displayed as successful release while old temperature outputs remain unconfirmed.

HA defines `last_reported` as the state-machine write timestamp, whereas `last_updated` only changes when the state or attributes change. Neither proves a physical probe is accurate or that an integration's cached reading is fresh at the device. [HA state-object documentation](https://www.home-assistant.io/docs/configuration/state_object/)

## Settings to review for each installation

- **Sensor report timeout:** default 15 minutes, configurable from 1 to 120. Choose it against the actual integration's report cadence, including unchanged readings. Verify missing-probe and communication-loss behaviour physically.
- **Minimum cooling OFF time:** default 180 seconds, configurable from 0 to 1,800. Use the equipment manufacturer's requirement; a fan may allow zero. After HA restart, the controller starts a fresh delay when it first observes cooling OFF. A safety OFF request is never delayed. This is an OFF/restart delay, not a minimum running-time guarantee.
- **Temperature limits:** defaults remain 22.0–27.5°C. Four regional presets extend outside these defaults. Review the chosen biological profile and independent protection settings before deliberately changing limits. The numerical values used by test fixtures are not husbandry recommendations.
- **Independent protection:** follow the actual controller and equipment instructions for both heating and cooling. The software does not prescribe a brand, socket arrangement or universal thermostat setpoint. The direct output bindings accept HA `switch.*` entities, not thermostat/climate setpoint APIs.
- **Initial enable/profile changes:** the daily seasonal curve is smoother, but selecting another preset/offset still immediately selects that profile's current target. There is no automatic acclimation ramp. Establish an appropriate acclimation plan before enabling across a large temperature difference.

## Verification

All verification used fake HA/device fixtures and the real OpenReef functions. No test contacted hardware.

- **25 temperature regression tests passed**, including bad/fresh/unchanged probes, C/F conversion, both-on recovery, failed ON/OFF, timeout, an unavailable opposing output, cooling delay, status between ticks, concurrent disarm/rebind, saved release recovery after restart, and unload.
- Existing spawning backend **58/58**, daylight/calendar reliability **22/22**, and spawning panel **9/9** passed.
- Wider repository run: **26/26 Python suites and 19/19 panel suites passed**. Additional focused tests were rerun after final refinements.
- Original short diagnostic audit: **22/22 properties passed**. The four incompatible default/preset properties now test explicit rejection, rather than requiring protective limits to expand to accommodate every curve.
- Annual schedule: **525,600 minute evaluations**, including both UK DST changes, with **730 daylight transitions**, no invalid states or simultaneous requested daylight/moonlight.
- All five presets × twelve offsets over 2027 and leap year 2028: **43,860 daily schedule evaluations passed**. A separate temperature interpolation test verifies every daily step and monthly anchor over the same matrix.
- Annual daylight executor: **8,760 hourly ticks**, **12 simulated runtime resets**, **730 light commands**, zero post-tick mismatches.
- Annual thermal executor with scripted C/F readings: **8,760 hourly ticks**, **12 resets**, **2,919 thermal commands**, zero wrong outputs or simultaneous heating/cooling.
- Combined full OpenReef executor (daylight, moonlight, heater and cooler together): **8,760 hourly ticks**, **12 resets**, **4,138 output commands**, zero thermal errors, simultaneous heat/cool or lighting mismatches.
- Compilation, panel syntax and whitespace checks passed.

The annual thermal traces alternate readings 0.4°C below/above the current target and use a zero cooling delay for a simulated fan. These are functional controller simulations, not physical tank heating/cooling models or proof of spawning. Nonzero cooling delay and fault injection are covered separately by regressions. The annual audit run passed **26/26 properties**; the combined four-output simulation was additionally run after extending the harness.

Reproduce:

```bash
python3 tests/test_spawning.py
python3 tests/test_spawning_reliability.py
python3 tests/test_spawning_temperature.py
node tests/test_panel_spawning.mjs
python3 tests/audit_spawning_resilience.py --annual
```

## Before connecting the tank

Run a supervised bench test with the real sensor integration, output plugs and heat/cool controller. Verify sensor report timing, correct C/F readings, actual output operation, loss/recovery of the probe and network, stuck/unavailable plugs, both outputs ON, cooling restart delay, disarm/rebind, HA restart and an outage across a temperature-control transition. Confirm the phone receives a failed-OFF alert with the panel closed. Verify independent cutoffs against the controller manufacturer's procedure.

Use one automation/controller for each smart-plug output. Check for competing HA automations and other OpenReef device modes. Changes to the output role should follow a confirmed thermal shutdown, with the physical equipment checked before reassignment.

**An independent thermostat cannot supply heat or cooling through a plug that is OFF.** HA cannot issue commands during its own outage. Reported OFF cannot prove an unwelded relay, and a late command already sent to hardware may still execute. Test the real plug's restoration/command-order behaviour and an independent outage/fallback arrangement. The saved recovery record uses normal HA configuration-entry persistence; abrupt power loss before HA flushes a write is not simulated here.

The software still uses a one-minute polling cycle, rather than an independent hardware safety controller. Record tank temperatures, actual output states, outages, configuration revisions and spawning observations throughout the year. See the [hybrid beta checklist](spawning-beta-readiness.md#keep-evidence-for-the-whole-year) for retention and recording gaps; no new year-long storage service has been deployed.

## Files changed for temperature

- [`__init__.py`](../custom_components/openreef/__init__.py): thermal reconciliation, report validation, retained output ownership, cleanup/recovery, live health, configuration checks and alerts.
- [`spawning.py`](../custom_components/openreef/spawning.py): daily interpolation and full-profile limit validation.
- [`openreef-panel.js`](../custom_components/openreef/frontend/openreef-panel.js): model-independent setup text, timeout/restart-delay fields and pending shutdown visibility.
- [`const.py`](../custom_components/openreef/const.py), [`manifest.json`](../custom_components/openreef/manifest.json): defaults, recovery-record key and version 0.7.142.
- [`test_spawning_temperature.py`](../tests/test_spawning_temperature.py), [`test_spawning.py`](../tests/test_spawning.py), [`test_panel_spawning.mjs`](../tests/test_panel_spawning.mjs), [`audit_spawning_resilience.py`](../tests/audit_spawning_resilience.py): regressions and annual simulations.
- This report and update notices on the historical audit/daylight-readiness reports.

No production dependency was added. Existing unrelated working-tree changes were preserved. No live settings, credentials, equipment or deployment were changed.
