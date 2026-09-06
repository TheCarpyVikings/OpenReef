# Spawning beta readiness — 6 September 2026

> **Update: full OpenReef temperature control has now been hardened in local version 0.7.142.** See [temperature readiness and hardware checks](spawning-temperature-readiness.md) for current results. The 0.7.141 findings and temperature exclusions below describe the earlier daylight-only preparation; the mixed OpenReef/Apex setup instructions still apply to the first beta tester.

**The focused fixes are implemented locally as version 0.7.141 and have passed software checks. The next step is a 48–72 hour bench trial with the actual equipment before starting the biological year.** This work has not been deployed to Home Assistant or tested against a live plug, fixture or Apex.

The confirmed setup is **OpenReef controlling daylight smart plugs, with Apex controlling temperature and moonlight**. Keep OpenReef seasonal temperature execution disabled. The broader spawning audit still identifies direct temperature-control faults; this is not approval for that separate control path.

## What changed

| Previous failure | Implemented behaviour |
| --- | --- |
| Plug reboot or an accepted but unfulfilled command became a false manual override | Confirm the reported state, retain an unresolved mismatch, and retry each minute. Only a direct HA action attributed to a user can create a hold. |
| Resume recreated the same hold | Clear the old assertion and mismatch along with the hold, and request reconciliation immediately. |
| Unrelated saves continually postponed the scheduler | Keep one interval across saves. Reconcile on relevant program edits and when HA starts. |
| A tick finishing after a disarm could save the old armed configuration back | Invalidate superseded work after awaits, stop before further outputs, and append activity to the latest configuration. |
| Slow plug calls could accumulate overlapping ticks | Limit each daylight/moonlight service call to ten seconds and serialize reconciliations. |
| Armed configuration displayed as successful operation | Show reported-state agreement, unresolved faults and last completed check. Publish `sensor.openreef_spawning_status`. |
| Exceptions and unfulfilled commands lacked useful alerts | Send an in-HA notification and use the configured phone notification route; repeated notifications have cooldowns. |
| The final spawn night expired early; January could lose a December window | Retain complete local nights until sunrise and search previous-year lunar candidates. |
| Two spawning roles could issue opposing commands to the same output | Reject duplicate output bindings when saving and refuse to actuate conflicting legacy configurations. |
| Apex temperature export had syntax and hysteresis discrepancies | Use the documented signed `RT+` differential, remove the unconditional OFF assignment, and use a comparable Fahrenheit band. Export local lunar dates, identify their timezone, and warn about months containing two new moons. |

The Spawning panel also explains the mixed OpenReef/Apex setup. Pulse describes the controller as armed without implying it has verified the light.

## Software verification

All runs used local fake HA/device fixtures or the pure calculation engine. No test commanded real equipment.

| Check | Result |
| --- | --- |
| Existing spawning backend tests | 58 passed |
| New spawning reliability regression tests | 22 passed |
| Spawning panel tests | 7 passed |
| Wider repository Python suites | 25 of 25 passed |
| Wider repository panel suites | 19 of 19 passed |
| GBR desired states, every minute from 6 September 2026 to 6 September 2027, Europe/London | 525,600 evaluations; 730 daylight transitions; no invalid states or simultaneous requested daylight/moonlight; includes both UK DST changes |
| All five presets and twelve seasonal offsets, sampled daily over 2027 and leap year 2028 | 43,860 evaluations; no invalid states or day lengths |
| Daylight executor, hourly over the same year with 12 simulated runtime resets | 8,760 ticks; 730 commands; zero post-tick reported-state mismatches |

Regression coverage includes both failed ON and failed OFF, delayed state reports, plug reboot/reconnection, service exceptions and timeout, overlap prevention, startup and unload callbacks, repeated saves, concurrent disarm/program edits, preservation of unrelated settings, manual hold/resume, phone routing, heartbeat expiry, local-night boundaries and duplicate bindings.

The full diagnostic audit reports **14 passing properties and 11 failing properties out of 25**, including its three annual checks. The remaining failures concern direct OpenReef temperature execution and its preset limits: sensor freshness, unconfirmed safety OFF, unreported actuator errors, disarm/rebinding handoff, heater/cooler mutual exclusion, thermal protection waiting behind a pending lighting call, and four preset/default-limit conflicts. These are grouped properties, not eleven independent bugs in the tester's daylight path. They remain visible deliberately; the diagnostic command returns exit code **1** while they are unresolved.

The annual executor checks normal operation with simulated runtime loss. Fault injection is covered by separate short regression scenarios; this was not a year of physical hardware operation or every possible combination of outages.

Reproduce the focused checks:

```bash
python3 tests/test_spawning.py
python3 tests/test_spawning_reliability.py
node tests/test_panel_spawning.mjs
python3 tests/audit_spawning_resilience.py --annual
```

## Configure the bench trial

1. Install the reviewed build through the usual OpenReef update procedure and restart HA. Check that the integration/panel reports **0.7.141**.
2. Enable spawning, choose the reef preset, seasonal offset and solar noon, and use execution mode **OpenReef — control selected plugs**. Bind the daylight plug; leave the moonlight binding empty and OpenReef seasonal temperature control disabled. Use **Put it back within a minute** (`reassert`) for this trial, then arm and save.
3. Record the actual HA version, plug integration/model/firmware, light model and Apex firmware. Check the plug's power-restoration setting and the fixture's response to restored power. Confirm that daylight power switching cannot interrupt Apex, heating or moonlight. Remove competing schedules from that same daylight output.
4. Set **Mode & spawning alert notify target** to the tester's available HA notify service, for example `mobile_app_phone` without a `notify.` prefix. Test the spawning fault route with the dashboard closed and confirm receipt on the phone.
5. Preserve any already validated Apex program. Align its local clock, DST policy and seasonal offset with HA. If using the generated temperature snippets, verify that the actual firmware accepts them, that heating/cooling behave correctly through the band, and that any required equipment-specific protection remains in place.
6. Arrange a **1 January 2027** Apex lunar-table check. Review the exported warning for the two new moons in August 2027 and establish how the actual controller represents them. OpenReef does not install a reminder or solve that firmware-specific limitation. The [source setup guide](https://packedhead.net/coral-spawning-resources/) describes the January reset; the [Neptune reference manual](https://help.neptunesystems.com/downloads/docs/Comprehensive_Reference_Manual.pdf) documents the temperature syntax.

## Hardware acceptance checks

Use a bench lamp or supervised equipment for injected faults. Record the time, expected state, actual illumination, HA-reported state and alert received for every check.

| Scenario | Required observation |
| --- | --- |
| Normal sunrise and sunset, including an overnight run | The physical daylight follows the chosen schedule; Apex temperature and moonlight remain independent. |
| Restart HA during daylight and just before each transition | The saved program resumes after startup and corrects a wrong plug state without inventing a manual hold. |
| Keep HA stopped across sunset, then restart | Document what the actual lamp does while HA is absent; verify recovery on return. An independent HA-down alert must work while HA is stopped. |
| Power-cycle the plug; disconnect and restore its network | An unavailable plug is reported. After reconnection it returns to the current desired state, whether that is ON or OFF. |
| Plug reports ON but fixture does not illuminate | A person, camera or suitable independent illumination/power check detects the failed output. The new status sensor alone cannot prove physical light. |
| Direct HA manual change under hold policy, then Resume | The hold is visible; Resume restores the intended state. Return to reassert for the trial. |
| Save unrelated settings repeatedly across a transition | The transition still occurs. |
| Disarm or change the program while switching is delayed | The new settings persist and the old tick does not command later channels. Already issued device commands may still finish. |
| Fault with dashboard closed | The tester receives the configured phone alert and can identify the affected plug. |

Normal polling is every **60 seconds**; state updates can add device/integration latency. An accepted but still unconfirmed command raises an alert after at least **120 seconds** of mismatch. Unavailable states and raised/timed-out commands alert on detection, subject to notification cooldown. Individual command attempts time out after **10 seconds**. A missing completed check for **180 seconds** is marked stalled and the active interval attempts an alert. These are software thresholds, not delivery guarantees.

**HA being down cannot be detected or corrected by HA itself during that outage.** Establish and test an independent outage notification and a deliberate daylight fallback. Disarming leaves the daylight plug in its current state; it does not mean lights OFF and cannot recall a command already sent. Use that procedure explicitly during maintenance.

## Keep evidence for the whole year

The OpenReef activity feed is capped at 200 entries; the annual simulation produced 730 daylight commands. The new status entity provides current health and timestamps, not a separate year-long journal. HA Recorder's default history retention is ten days; use reviewed retention settings or scheduled exports with independent copies before day one. Review the existing recorder filters and available disk space; adding an `include` filter can exclude other entities. [HA Recorder documentation](https://www.home-assistant.io/integrations/recorder/)

Retain dated records of planned and observed daylight, unexpected light after sunset, plug availability, completed spawning checks, HA outages, configuration/version changes, and Apex temperature/moonlight performance. Record actual spawning observations separately. Check that exports can be opened and that a backup can be restored. If using HA history, confirm the daylight entity and `sensor.openreef_spawning_status` are actually being recorded and retained for the chosen period.

The existing automatic spawn-night camera trigger produces a snapshot and a short clip, not continuous observation. Its once-per-night stamp is in memory and precedes capture success. Arrange and test recording across the intended observation window; the current trigger is not sufficient evidence that no spawning occurred.

## Remaining limits and release decision

- Do not enable direct OpenReef seasonal temperature execution for this beta. Its unresolved faults are detailed in the [original audit](spawning-reliability-review-2026-09-06.md#other-confirmed-issues-in-direct-openreef-temperature-control).
- Apex templates still need acceptance on the exact firmware and fixture. The five-step daylight/profile exporter has not been completed or validated by these fixes; the tester's HA daylight plugs do not use it.
- Regional temperature presets and spawn windows are approximations. Agreement between software outputs does not prove that the selected environment, colony maturity or husbandry will produce spawning.
- Smart-plug feedback cannot detect every welded relay, fixture failure, lost clock or electrical outage. Actual equipment recovery and the HA-down fallback remain untested here.

Start the biological year after the real-equipment checks pass, phone alerts arrive, Apex alignment is verified and durable records are working. Review faults during the trial, especially after updates, power cuts and the January lunar-table change.

## Files changed by this work

- [`custom_components/openreef/__init__.py`](../custom_components/openreef/__init__.py): scheduler, reconciliation, configuration protection, output validation, health and alerts.
- [`custom_components/openreef/spawning.py`](../custom_components/openreef/spawning.py): local-night prediction and Apex export corrections.
- [`custom_components/openreef/frontend/openreef-panel.js`](../custom_components/openreef/frontend/openreef-panel.js): truthful status, hybrid setup guidance and export warnings.
- [`custom_components/openreef/const.py`](../custom_components/openreef/const.py) and [`manifest.json`](../custom_components/openreef/manifest.json): thresholds, status entity and version 0.7.141.
- [`tests/test_spawning.py`](../tests/test_spawning.py), [`tests/test_spawning_reliability.py`](../tests/test_spawning_reliability.py), [`tests/test_panel_spawning.mjs`](../tests/test_panel_spawning.mjs) and [`tests/audit_spawning_resilience.py`](../tests/audit_spawning_resilience.py): regressions and diagnostic year/fault simulations.
- This readiness document and the [historical audit](spawning-reliability-review-2026-09-06.md).

Unrelated working-tree changes were preserved. No new production dependency was added; no live configuration, equipment, credentials or remote deployment was changed.
