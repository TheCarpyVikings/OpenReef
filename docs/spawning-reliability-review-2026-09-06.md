# Spawning reliability review — 6 September 2026

> **Historical baseline review (0.7.139).** Daylight fixes followed in 0.7.141, and temperature fixes in local 0.7.142. See [temperature readiness and current results](spawning-temperature-readiness.md) and the [hybrid beta checklist](spawning-beta-readiness.md). The findings and results below preserve the original audit; they are not the current test results.

**Recommendation: fix the daylight recovery and scheduling issues before starting the year-long beta.** The normal calendar/reconciliation path works in simulation, but several realistic faults can leave the lighting wrong without a useful warning. A simulated year verifies software behaviour; it cannot establish that the corals will spawn.

The beta configuration confirmed by Reece is **OpenReef controlling daylight smart plugs; Apex controlling temperature and moonlight**. The direct OpenReef temperature findings below are therefore outside this tester's active control path.

Scope: the native Home Assistant integration, spawning engine, settings persistence, scheduler, notifications, capture hook, native panel and Apex exporter. Baseline: commit `3f6ffb5`, manifest version `0.7.139`. Other work changed cultures/maintenance/NPS files during the review, including unrelated parts of `__init__.py`; those changes were preserved. No production code, live HA configuration or equipment was changed by this audit. File line numbers below refer to the working tree at review time.

## Findings affecting this beta

### 1. High — plug failures can become a false manual override

Source: [`_async_spawning_tick`](../custom_components/openreef/__init__.py#L20245), particularly the assertion/override logic at lines 20286–20315.

The default `hold` policy assumes any mismatch after an earlier correct state was caused by a person. It does not distinguish a plug reboot, a competing automation or an unsuccessful command from deliberate manual control. It also records a command as asserted as soon as the service returns, without checking that the state changed.

**Reproduced:** an accepted-but-unfulfilled ON command was sent once; the next tick invented an override and the light stayed OFF. Separately, a working plug became unavailable and rebooted OFF; on recovery it stayed OFF until the next natural transition. Issues were empty after the invented override. The opposite direction can leave daylight on overnight.

**Fix:** distinguish requested state from confirmed state, verify changes with bounded retries, treat reconnects as recovery, and require explicit evidence/intent for a manual hold. For the tester, `overridePolicy: reassert` avoids this particular false-hold path. It does not fix the other findings or verify physical light output.

### 2. High — an older tick can undo a newer disarm/configuration change

Source: [`_async_spawning_tick`](../custom_components/openreef/__init__.py#L20215) and [`_async_save_config`](../custom_components/openreef/__init__.py#L6263).

The tick reads the full configuration, awaits device commands, appends activity to that old copy, then saves the whole copy. A user can save newer settings while the device call is pending.

**Reproduced:** pause a light service call, save `armed: false`, then allow the original call to finish. The old tick saves `armed: true` back into the entry. Preset or binding edits can be overwritten by the same pattern.

**Fix:** keep activity persistence from overwriting control configuration, check configuration revisions after awaits, and prevent overlapping reconciliations from issuing stale commands. Cancelling an interval registration does not cancel an already running tick.

### 3. High — unrelated saves can prevent lighting ticks from firing

Source: [`_async_save_config`](../custom_components/openreef/__init__.py#L6263), [`_async_schedule_spawning_tick`](../custom_components/openreef/__init__.py#L19987).

Every configuration save cancels and recreates the 60-second interval, even if spawning settings are unchanged. There is no immediate reconciliation.

**Reproduced:** saves every 30 seconds for five simulated minutes produced zero spawning ticks and left an OFF light OFF during its intended photoperiod. Background features also use the shared save path, so this is broader than pressing Save on the spawning page.

**Fix:** retain the interval across unrelated saves, reconcile on relevant setting changes, and perform a startup reconciliation when devices are ready. Add a scheduler test with actual repeated-save callbacks.

### 4. Medium — “Resume now” immediately recreates the hold

Source: [`websocket_spawning_execution_resume`](../custom_components/openreef/__init__.py#L20418).

The handler clears `overrides` but retains `asserted`. The next tick sees the same mismatch against the retained assertion and creates another hold.

**Reproduced:** Resume returned success, but the light remained OFF and the override reappeared on the following tick.

**Fix:** explicitly request a reconciliation that bypasses that old assertion/hold decision, and test the resulting plug state rather than just the empty override dictionary.

### 5. High operational gap — “running” does not prove the light is running

Source: [`websocket_spawning_execution_status`](../custom_components/openreef/__init__.py#L20364), [`_async_run_watchdog`](../custom_components/openreef/__init__.py#L5150), actuator call at line 20307.

The status flag is derived from configured mode, armed state and bindings. There is no spawning tick completion timestamp, sustained-mismatch alarm, or physical-output check. A light service exception creates a panel issue and log entry, but does not use the phone-notification path used for an unavailable plug. An accepted command with an unchanged state can fall into finding 1 without an issue.

The shared watchdog records its own heartbeat, not successful spawning ticks. OpenReef cannot change a plug or send a new alert while HA is stopped. A welded relay or a failed lamp can also disagree with HA's reported switch state.

**Fix:** expose last completed reconcile, desired/observed state and time out of agreement; send a tested phone alert for sustained failures. Record actual illumination or suitable power telemetry where available. Choose and physically test an independent outage fallback for daylight and an external HA-down notification.

Blocking actuator calls have no OpenReef timeout or overlap guard. HA's implementation awaits blocking services and schedules interval callbacks independently, so a slow/hung integration is not automatically contained by the one-minute timer. This is supported by the [HA service implementation](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/core.py#L2638) and [interval implementation](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/helpers/event.py#L1483). Add bounded service timeouts and stale-command checks.

### 6. Medium — spawn windows can lose their last night and disappear at New Year

Source: [`predict_spawn_window`](../custom_components/openreef/spawning.py#L340).

The selection expires at the *full-moon instant* plus the final offset, even though the UI describes inclusive calendar nights. It also searches only the current and following year, excluding a previous December moon whose window falls in January.

**Reproduced:** GBR 2026 predicts 6–9 December, but at 23:00 on 9 December the selected window has jumped to November 2027. With a one-month seasonal offset, the predicted 5–8 January 2027 window is already absent at 01:00 on 5 January.

These errors affect the countdown, spawn-night light warning and capture hook; they do **not** stop the ordinary daylight schedule. UTC date extraction also needs an explicit local-night policy.

**Fix:** model complete local nights, include previous-year candidates, and test the final evening, post-midnight hours and year rollover.

### 7. Apex export needs validation before this tester copies it

Source: [`_code_snippets`](../custom_components/openreef/spawning.py#L397), [`generate_program`](../custom_components/openreef/spawning.py#L517), [`_walkthrough`](../custom_components/openreef/spawning.py#L503).

- Generated negative temperature offsets use `RT-0.2`; Neptune documents the `RT+` prefix with a signed differential, e.g. `RT+-0.2`. This is a documented syntax discrepancy; rejection on the tester's exact Apex firmware has **not** been tested. The exporter should not claim verified copy-paste readiness until that is checked. [Neptune reference manual](https://help.neptunesystems.com/downloads/docs/Comprehensive_Reference_Manual.pdf)
- The exported heater/chiller snippets add `Set OFF`. Under the documented default-state semantics, this removes the hold-in-band behaviour of OpenReef's direct controller; it is not the claimed identical hysteresis implementation. The temperature tolerance is also the numeric value 0.2 in both °C and °F, which represents different physical bands. Check the intended band and anti-cycling protection on Apex.
- The referenced setup guide explicitly calls for checking/resetting custom new-moon dates in January. OpenReef's walkthrough already warns about this, which is good; the export contains one year's dates and does not schedule a reminder or arrange the handoff. The generated 2027 list contains two August new moons, on 2 and 31 August; there is no double-new-moon workflow in the exporter. Confirm how the tester's controller handles both issues. [Rich Ross's setup guide](https://packedhead.net/coral-spawning-resources/)
- The five-step daylight snippet also differs from the cited recipe and only four profile templates are supplied. This is outside the confirmed smart-plug daylight path, but the general “exact workflow” claim is too strong.

If Apex already has independently validated temperature/moonlight programs, preserve those and check their seasonal alignment with OpenReef. Export discrepancies are conditional on using OpenReef's generated Apex code.

## Other confirmed issues in direct OpenReef temperature control

These do not affect an independently controlled Apex heater, provided OpenReef temperature execution stays disabled.

| Issue | Evidence and consequence | Suggested correction |
|---|---|---|
| Healthy, unchanged readings treated as stale | A 20-minute-old `last_updated` with a fresh `last_reported` caused the heater to be turned OFF. | Use the sensor's actual report/availability contract; `last_updated` is not a heartbeat. [HA timestamp definitions](https://www.home-assistant.io/docs/configuration/state_object/) |
| Failed safety command reported as success | Injecting failure into heater OFF left it ON, while the notification said heater and cooling were switched OFF. The return value is ignored. | Track unconfirmed OFF, retry and escalate; make the message accurately describe the result. |
| Normal heater command failure only logged | Failed ON at 24.4°C against 24.7°C produced no runtime issue or notification. | Persist a per-actuator fault until confirmed recovery. |
| Disarm/rebinding can abandon an energised heater | Disarm left the heater ON even after the sensor was set to 30°C. Rebinding left both old and new heaters ON. | Define and execute a verified handoff for thermal actuators; do not reuse daylight's leave-as-is policy. |
| A blocked daylight call delays thermal protection | With an unavailable temperature sensor, a paused daylight command prevented reaching the heater-OFF logic. | Isolate thermal reconciliation from other channels and bound device calls. |
| Heater and cooler can both remain ON | Both ON at target remained ON through the hysteresis hold band. Duplicate output roles are also accepted. | Reject conflicting bindings and enforce actuator mutual exclusion. |
| Default clamps contradict four of five full preset curves | GBR peaks at 29.0°C but heat is prohibited from 27.5°C; Singapore's whole curve exceeds 27.5°C; Red Sea drops below the 22°C cooling floor; Caribbean peaks at 30.1°C. | Validate the chosen biological profile against the configured limits and hardware. Do not silently raise safeguards to fit a preset. |
| Direct seasonal target jumps monthly | `targetTempC` directly indexes the monthly array: largest steps are 1.6°C for GBR and 1.9°C for Caribbean. | Interpolate an agreed seasonal curve and define acclimation after initial enable or a profile change. |

Source: [`_async_spawning_temp_reconcile`](../custom_components/openreef/__init__.py#L20105), configuration normalization around line 3474, and [`execution_desired_state`](../custom_components/openreef/spawning.py#L688).

An inline thermostat can cut excessive heating while powered. It cannot supply power through an OpenReef plug that is OFF; the current “guard thermostat holds the tank” failure message overstates that protection.

## Recording and interpreting a year of testing

- The shared activity feed retains only 200 entries. The simulated executor produced 730 light commands and retained 200 activity entries. Save durable daily summaries of planned/observed light duration, unexpected light after sunset, HA downtime, plug outages, configuration revisions, and Apex temperature/moonlight performance. Establish export/retention before day one.
- The automatic spawn-night capture is a snapshot and short clip at the first eligible evening tick: 12 seconds by default, 60 seconds maximum. It is not a night's recording. Its once-per-night stamp is in memory, is lost on restart, and is set before capture success. Arrange recording across the intended observation period and verify it can see the corals without unwanted illumination.
- Presets are regional approximations, not species-specific guarantees. The GBR prediction covers one spawning month even though its cited hobbyist source describes two. Validate the selected species, population, mature colonies and observation period with the tester; record biological outcomes separately from control-system uptime. The foundational study combined environmental control with husbandry and observed complete gametogenic cycles over more than a year. [Craggs et al., 2017](https://pubmed.ncbi.nlm.nih.gov/29299282/)

## Smallest useful preparation for this beta

1. Fix findings 1–4, add confirmed-state failure alerts and a tick heartbeat, and validate any Apex snippets the tester intends to use. Keep changes focused on this control path.
2. Configure `mode: openreef`, the daylight binding, `moonEntity: null`, and `temp.enabled: false`. Use `reassert` for the trial, with a clear deliberate maintenance/disarm procedure. The global `apex` mode would stop OpenReef daylight control too.
3. Confirm the daylight smart plug does not cut power to the Apex-controlled moonlight or the Apex itself. Confirm the light's own internal program/clock/power-restoration behaviour allows it to illuminate whenever the plug is ON. Ensure no other automation controls the same output.
4. Align reef preset, seasonal offset, local clock and DST handling across HA and Apex. Agree a January lunar-table check and the 2027 double-new-moon handling before the trial crosses those dates.
5. Run a 48–72 hour bench trial with the real plug/light: HA restart before sunrise and sunset, HA stopped across sunset, plug reboot, network loss/recovery, failed or slow switching, manual override/resume, and saving/disarming during a pending command. Observe the actual lamp and confirm the phone alerts arrive with the dashboard closed.
6. Start the biological year only after those checks pass and durable logging/recording is in place. Review exceptions promptly, rather than waiting until the expected spawn to discover a broken photoperiod.

## Verification and reproduction

The audit harness uses the real spawning functions and executor with the existing fake HA/device framework. It never contacts a live controller. Restart checks reconstruct in-memory HA runtime while retaining the config entry and device states; they do not reproduce HA's full boot lifecycle or electrical behaviour.

```bash
python3 tests/test_spawning.py
node tests/test_panel_spawning.mjs
python3 tests/audit_spawning_resilience.py
python3 tests/audit_spawning_resilience.py --annual
```

The audit intentionally exits **1** while unresolved reliability properties fail. It is separate from the `test_*.py` CI discovery; its failures are evidence for remediation, not assertions that bugs are acceptable.

Results:

- Existing spawning backend: **58/58 passed**. Existing spawning panel: **4/4 passed**.
- Annual daylight executor: **8,760 hourly ticks, 12 simulated runtime resets, 730 light commands, zero post-tick state mismatches**.
- Minute-by-minute GBR calendar, 6 September 2026 to 6 September 2027 in Europe/London: **525,600 evaluations passed**, including both UK DST changes; **730 daylight transitions**, no invalid states or simultaneous requested daylight/moonlight. This verifies the schedule computation, not actual light output during outages.
- All five presets × all twelve seasonal offsets, sampled daily throughout 2027 and leap year 2028: **43,860 evaluations passed** without invalid states or invalid day lengths.
- Fault/calendar/default-limit audit: **19 failed properties out of 22**, grouped above; these are not 19 independent release-blocking bugs.
- Wider test snapshot: **23/24 Python suites passed; 19/19 panel suites passed**. The cultures suite failed `test_summary_carries_the_rig_and_the_vessel_fields` during concurrent cultures work. That failure is outside spawning; the wider run is not a clean release sign-off.
- Python compilation of the spawning engine, integration and audit harness passed; native panel JavaScript syntax check passed.

Files added by this review: this report and [`tests/audit_spawning_resilience.py`](../tests/audit_spawning_resilience.py). No production fixes have been applied. Next step: implement the focused daylight reliability fixes, then run the real-equipment bench trial.
