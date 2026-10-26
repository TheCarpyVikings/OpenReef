# AWC and NPS safety audit — 25 October 2026

This review covers OpenReef's automatic water change orchestration, food
dosing, matched feed-water drainage, settings saves and the Node 1 ESP32-S3
firmware. Reece's build uses the stepper for phyto and brushed pumps for
AWC drain, saltwater fill and live food.

**This is software verification, not approval for unattended tank operation.**
No pump, real Home Assistant instance or physical ESP32 was operated during
the audit. The software tests use simulated devices; the firmware build uses
dummy network settings and must not be flashed as the user's configuration.

## Defects addressed

| Failure case | Required behaviour |
|---|---|
| HA restarts during a water change | Stop both pumps, latch a fault and retain only saved progress. Never infer drainage during downtime or automatically add replacement water. |
| A pump ignores ON/OFF, becomes unavailable or its watchdog stops it | Verify reported actuator state; stop and fault. A failed drain stop must never advance to filling or release the ATO. |
| Saving state fails after starting/changing a leg | Stop outputs and retain a fault rather than leave an untracked pump or replay a previous leg. |
| A requested AWC leg exceeds the reference node's watchdog | Refuse before draining. Backend legs are limited to 170 s; the firmware backstop is 180 s. Reduce each change and increase cadence. |
| A fitted flow curve cannot represent a tiny remaining volume | Refuse rather than run an arbitrary minimum or count water that did not move. |
| Device dosing settings are missing, offline or rejected | Disable first, write settings, verify every required value, then enable. Manual doses also require verified manual volume. |
| OpenReef stops communicating, the device reboots or a run trips | Food enable leases expire; boot does not restore an old enable. Trip and interrupted-run locks persist until checked and cleared. |
| Clock misses midnight or moves backwards | Daily caps remain conservative. A backwards date must not reset the dose allowance. |
| A food dose is interrupted | Reserve its allowance before motion, but never report the full target as completed. Completed-dose telemetry is separate from daily reservations. |
| HA restarts after seeing a food-dose counter increase | Persist the counter baseline, bottle debit and matched-drain debt together; never bank the same dose twice. |
| Midnight passes without a complete sensor reading | Do not invent delivery from the planned schedule and drain against that guess. |
| A matched drain is interrupted or its stop is uncertain | Stop and fault, disable the exchange and forfeit uncertain pending debt rather than replay it. Reconcile levels manually. |
| A generic HA-timed food pump is selected for matched drainage | Refuse automatic matched drainage: a completed firmware dose counter is required. A timed switch alone cannot establish delivered volume. |
| A stale tab saves settings or a pump is rebound mid-run | Preserve runtime counters/stop records and refuse changes to active actuator bindings/calibration. Enabled channels must be disabled and confirmed off before removal. |
| A page refresh, notification or unrelated feature saves an older snapshot | Preserve the current controller state and reservoir balances. Notification results commit only their own bookkeeping; timers re-read current state. |
| A delayed background task tries to resume or dose after a newer pause | Re-read current AWC and dosing controls under their locks before issuing hardware commands. |
| A background watcher finishes after a newer dose was recorded | Merge only its advisory changes; retain current delivery counters, bottle stock and stop records. |
| ATO duty cycling waits on a device | Run it separately from pump-state saves and serialize its ON decision with AWC, so it cannot delay arming the stop timer or bypass a new hold. |
| OpenReef is intentionally disabled or reloaded | Revoke dosing, attempt each owned output's stop, and keep recovery timers if shutdown cannot be confirmed. A rejected stop must not allow reload to proceed. |
| Two controllers share a writable output | Reject duplicate or wrong-domain bindings and block actuation. Read-only sensors may be shared. |
| An old settings backup is imported | Require old controllers to be stopped; import AWC, dosing and feed exchange disabled, with no pending physical runs. |
| Food expires | Stop scheduled food dosing, including the standing phyto drip, until a fresh load is recorded. |
| Food rinse and AWC both use the fill pump | Automatic rinse is disabled in UI, integration and firmware. No guessed rinse water is added to accounting. |
| The TMC driver starts during setup or UART stop hangs | A local wrapper keeps ENN disabled during setup and cuts it before UART stop; driver failure must refuse motion. |

## Evidence and checks

Dedicated failure tests are in:

- `tests/test_awc_audit.py`: power loss, rejected actuation, failed stops,
  persistence failure, lost actuator state and bounded run behaviour.
- `tests/test_nps_safety_audit.py`: sync/readback refusal, manual-volume proof,
  disabled channels, atomic accounting, midnight and food freshness.
- `tests/test_dosingnode_safety.py`: executes firmware guard, clock and lease
  lambdas and the local driver wrapper on a host; checks motor/persistence order.
- `tests/test_automation_settings_safety.py`: duplicate bindings, active-edit
  refusal, stale saves, notification races and import disarming.
- `tests/test_automation_shutdown.py`: intentional unload, failed stops,
  concurrent shutdown and simulation isolation.

Verification on 25 October 2026:

| Check | Result |
|---|---|
| Five added audit suites | 94/94 tests passed: AWC 27, NPS 33, settings/concurrency 16, firmware 7, shutdown 11. |
| Existing AWC, dosing, NPS, mixing, binding and NPS-panel suites | Passed. |
| Python compilation, panel JavaScript syntax, diff whitespace | Passed. |
| Full ESPHome 2026.10.0 build | Passed; configuration hash `0xcdf0771e`, RAM 32.4%, flash 47.4%. The compiled YAML/local C++ match the reviewed source apart from temporary dummy network/path substitutions. |

The repository-wide run passed **62 of 65 suites**. Three suites retain
pre-existing failures reproduced separately from the last released commit
(`fcc230e0`, v0.7.226): two daylight assertions in `test_cultures.py`, the
due-report scheduling assertion in `test_report.py`, and the hand-logged trend
modal assertion in `test_panel_live.mjs`. Those failures remain unresolved;
this audit does not claim a fully green repository.

Release verification on 26 October 2026 repeated all 65 suites from an isolated
copy of the staged v0.7.227 files: **61/65 suites passed**, including all 94
focused audit tests. After midnight, `test_cultures_audit.py` additionally failed
its lamp-tick assertion; the identical failure was reproduced on v0.7.226.
All four failing suites are recorded in the release notes.

These checks use simulated Home Assistant devices and host-compiled firmware
decisions; they cannot verify real electrical or hydraulic behaviour.

Changed implementation files are `custom_components/openreef/__init__.py`,
`custom_components/openreef/dosing.py`,
`custom_components/openreef/frontend/openreef-panel.js`, the Node 1 reference
YAML, and its new `esphome_components/openreef_tmc2209/` driver wrapper.
The build guide, hardware-brief pointer, test harness, regression tests and CI
workflow were also updated. Unrelated workspace changes were left untouched.

## Hardware acceptance still required

Use the [build and commissioning steps](manual/dosingnode-s3zero-design.md#5-checked-build-and-commissioning--2026-10-25).
Keep all pump outlets away from the aquarium for these checks.

1. Verify wiring, fuses, supply voltage, motor polarity, stepper coil pairs and
   motor current. Check D4184 TRIG pull-downs and TMC ENN fail-off behaviour.
2. Test cold boot, ESP reset and brownout with the motor rail powered. No
   uncommanded motor movement is acceptable.
3. Calibrate and measure every pump independently. Verify actual small doses
   and repeated pulses; a reported switch state is not a flow measurement.
4. Verify stop/disable, watchdog trip, API/Wi-Fi loss, HA shutdown and reboot
   during motion. Confirm no automatic catch-up dose, guessed make-up fill or
   replayed matched drain. Deliberately failed tests go to a catch container.
5. Run full AWC cycles with source, tank substitute and waste containers.
   Measure drain/fill balance, confirm the reservoir ledger, ATO suspension
   and restart fault behaviour.
6. Verify the shelf-bottle link and freshness expiry. Record actual bottle
   contents, calibration, daily dose and caps before enabling a small schedule.
7. Supervise the first aquarium runs, compare measured volumes and salinity,
   and keep automatic rinse disabled.

## Remaining limits

- This pumps-only node has no independent shutoff relay, real flow meter,
  physical reservoir float or leak/high-level sensor. Software cannot stop a
  shorted MOSFET, detect every blocked/slipping tube or prove that a commanded
  dose reached the tank. A fuse is electrical protection, not dose control.
- Bound HA sensor states are reports, not proof of physical freshness. Sensor
  failure and stale readings still need physical protection and commissioning.
- ESPHome counters estimate completed motor commands. Partial delivery on
  interruption is uncertain and intentionally does not become guessed drain
  debt. After any fault, reconcile tank, fresh and waste levels before clearing.
- Generic HA-timed pump switches depend on HA to stop them, and cannot be
  used for automatic matched feed-water drainage. They do not gain
  the Node 1 firmware's local watchdog or food-enable lease merely by binding
  them in OpenReef. Reece's pumps should use the reference firmware paths.
- Independently limit the volume that can enter or leave the tank and prevent
  siphoning. An independent cutoff and physical level/leak protection are
  additional safeguards before unattended use, not something a passing test
  suite provides.
- Durable per-dose reservations trade flash writes for crash-safe allowance
  tracking. High-frequency phyto operation needs a long-duration bench test,
  including persistence, timing, thermal behaviour and flash-write endurance.

Keep the integration and Node 1 firmware from this audit together: updating
only one side does not provide the full safety behaviour described here.
