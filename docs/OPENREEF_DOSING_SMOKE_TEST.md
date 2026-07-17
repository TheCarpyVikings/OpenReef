# OpenReef Dosing Smoke Test

Use this after installing or updating OpenReef Core in a real Home Assistant instance. It walks every acceptance criterion of the dosing feature. Sections 1–6 need **no hardware**; sections 7–10 need a doser flashed with the reference firmware ([`docs/manual/kalk-doser-esphome-design.md`](manual/kalk-doser-esphome-design.md)).

Safety first: dose into a **measuring cylinder or bucket**, never the tank, until section 9 passes. Kalkwasser is high-pH — the guard checks below exist because a stuck doser is a crashed tank.

## Setup

- Open Home Assistant with the OpenReef panel in the sidebar; hard-refresh the browser (Ctrl+Shift+R) after updating.
- The Dosing tab appears between Water Change and Controls. If it's missing, check Settings → Dosing → "Show the Dosing tab".
- With a doser: flash the reference firmware, confirm its ~24 entities appear in HA (Settings → Devices), and keep the pump's outlet in a measuring vessel.

## 1. Tab, Empty State, And Advisor (no hardware)

- The Dosing tab renders visually consistent with the Water Change tab (cards, pills, section heads).
- With no channels configured, the tab shows the "Nothing dosing yet" card — friendly copy, an "Add a channel" button, and no errors.
- The Dosing & Consumption Advisor section renders at the bottom of the tab (it moved here from Mission Control).
- If alkalinity/calcium/magnesium are mapped, the advisor populates within ~a minute of opening the tab without pressing anything.
- The Mission Control "Dosing" tile (when enabled in the Mission card settings) jumps to the Dosing tab.

## 2. Channel Setup Flow (no hardware)

- Settings → Dosing → "+ Kalkwasser doser" creates a channel seeded with continuous mode and 65% night weighting.
- The tab now shows the channel as a 3-step setup checklist (bind entities → calibrate → set volume) — not a fake "OK" state.
- Rename the channel, change its chemical, Save: both persist after a browser hard refresh.
- Add a second channel with the plain "Add channel" row (e.g. "Alk", chemical Alkalinity, doses mode). Remove it again: with no pump bound this removes without ceremony.

## 3. Schedule Editing And The Plain-Language Line (no hardware)

- On a channel, set Daily volume 300 ml, mode Continuous, window 00:00–00:00. The summary line under the schedule reads back the plan in plain words and updates live as you type.
- Enable Night weighting at 65%: the summary mentions the overnight share.
- Switch mode to "N doses per day" with 8 doses in a 08:00–20:00 window: the summary shows "8 doses of …".
- Nothing here requires a reflash or restart — it's all config.

## 4. Guards Are Toggles, Not Code (no hardware)

- The pH failsafe is a pause-above / resume-below **pair** — confirm there is no field anywhere that doses *when pH is low* (that pattern is deliberately unbuildable).
- On a kalk channel with no pH entity picked, an amber "No pH failsafe" warning appears and must be explicitly acknowledged before the channel will arm.
- Clearing the pause/resume fields restores the safe defaults (8.45/8.30) rather than storing zero.
- Max daily left at 0 shows "automatic (daily volume + 25%)".
- Settings → Dosing → Dosing alerts: all five families (missed doses, reservoir low, tube life, calibration due, sync & drift) exist and default ON.

## 5. Dry-Run Preview And Ramp (no hardware)

- With a daily volume set, the tab's "Tomorrow's plan" section lists the channel; Preview renders dose times and the realised total — and the pump does not move (it isn't even bound).
- Enable "Ramp up a new tank" on the channel: the card shows the ramp percentage and hint. Log a checkpoint with a test value: the percentage steps up by the configured step.
- The advisor row on the channel card either shows a suggestion with an Apply button, "matches the current schedule", or the advisor's state (learning/locked) — never a blank.
- Apply a suggestion: the daily volume field updates, the panel shows "Save to sync", and Save persists it.

## 6. Persistence Across HA Restart (no hardware)

- Configure a channel fully (schedule, guards, reservoir size), Save, then restart Home Assistant.
- After restart: channel, schedule, guard values, and notifications toggles are all intact.
- The Repairs page stays clean through the restart (no "missing mapped entities" / "armed equipment unavailable" phantom repairs — fixed in 0.4.108).

## 7. Entity Binding And Sync (doser required)

- On the channel, press "Auto-bind entities": expect "24 of 24 bound" (the reference firmware's names are a frozen contract). Any misses appear by role in the overrides list.
- Save. Within ~30 seconds (an 8 s read-back verify plus the tab's refresh cadence) the card footer shows the synced timestamp — every number OpenReef wrote was read back from the device.
- Change the daily volume, Save again: watch the firmware's dose-volume and interval numbers change in HA Developer Tools → States. **No reflash. This is acceptance criterion #2.**
- Pull the doser's power: the tab banner turns red ("Doser offline") within a minute and explains the device keeps dosing its last synced schedule. Restore power: it clears and re-syncs.

## 8. Calibration Blocks Until Done (doser required)

- With entities bound but no calibration stored: the card pill reads "Not calibrated", the checklist shows step 2 open, and **scheduled dosing does not start** even with the channel enabled — firmware refuses while steps/ml is 0.
- Prime the line until liquid reaches the outlet (bounded 10 s runs — there is no unbounded ON anywhere).
- "Run 100 revolutions", catch the output, measure it (Kamoer KPHM100 ≈ 27 ml), enter it, "Save calibration". The status line shows steps/ml and the timestamp; the calibration history keeps prior entries for drift comparison.
- "Verify with 10 ml dose" into the measuring cylinder: delivered volume within ~5% of 10 ml. **Criteria #3 and #4 pass.**

## 9. Every Guard Demonstrably Blocks (doser required)

For each, attempt "Dose now" (or wait for a scheduled dose) and confirm (a) no liquid moves, (b) the panel names the reason, (c) the firmware's Last Skip Reason sensor agrees:

- **Enable off**: channel disabled → blocked.
- **pH ≥ stop**: temporarily lower the pause threshold below the current pH → "paused at ≥ …, resumes below …". Raise it back → dosing resumes only below the resume value (hysteresis).
- **pH sensor unavailable**: make the picked pH entity unavailable → dosing pauses (fail-safe), banner explains.
- **Daily cap**: set max daily just above the dosed-today figure, dose past it → "Daily cap reached".
- **Reservoir low**: lift the float (or empty the vessel) → skipped with reason.
- **AWC active**: start a water change → the Dosing banner shows "suspended — water change running"; the firmware's HA-suspend switch is on; it clears after the change **and** its stabilisation hold-off. **Criterion #5 passes.**

## 10. Ledgers, Alerts, And Reboot (doser required)

- Dosed-today and the progress bar track the firmware sensor; the bar's tick marks the daily target, the bar end the hard cap. **Criterion #6.**
- Set the reservoir size and let a few doses run: remaining volume decrements and "days left" appears. "Refilled — reset ledger" restores it and nudges a re-prime.
- Tube hours accumulate in the card footer; "Reset — tube replaced" zeroes them.
- Block the schedule silently (e.g. power the pump motor off but keep the ESP32 up... or just disable the enable switch directly on the device): within ~20 minutes a **missed doses** notification arrives, and the banner offers Re-spread / Skip — for kalk, Skip is the highlighted default, and nothing ever re-doses automatically.
- Reboot the ESP32 mid-day: dosed-today survives (firmware persistence), settings survive, and HA reconciles without double-counting. Restart HA too: same. **Criterion #7 passes.**

## If Something Fails

- Settings → System → Logs, filter "openreef", and capture the lines around the failure.
- The channel card footer's sync state ("failed"/"offline") plus the Last Skip Reason sensor usually identify the layer at fault (HA-side vs firmware-side).
- Rollback pin: HACS → OpenReef → Redownload → pick the previous version. Dosing config is preserved — it lives in the OpenReef config entry, not the firmware.

## 11. Merged Reefnode (single ESP32-S3) Additions — Stage D

Running the merged node (`docs/manual/reefnode-s3-reference.yaml`)? Everything
above still applies, plus:

- [ ] `Reefnode Master Enable` turns ON a few seconds after boot; a leak trip
      (or the hardware coil float) drops it, kills every pump, and stays
      latched until `Reefnode Clear Lock`.
- [ ] Kalk auto-bind reports **25 of 25** (rev 3); live-food auto-bind **22 of 22**
      (driver-aware — the live-food channel uses the brushed suffix table in
      `docs/manual/reefnode-s3-design.md` §3).
- [ ] Live-food `Calibrate 30s` runs exactly 30 s; the panel derives ml/s.
- [ ] A live-food dose with `Live Food Chaser (s)` > 0 runs the AWC fresh pump
      afterwards — and SKIPS (with `Live Food Chaser Skipped` = on, no ledger
      debit) when a water change owns that pump.
- [ ] Mark the culture stale (clear `mixedAt` shelf-life expiry) → within a
      minute HA forces `Live Food Dosing Enabled` OFF and the skip sensor reads
      `disabled`; "Refreshed today" re-enables on the next sync.
- [ ] Full bring-up order: `reefnode-s3-design.md` §5.

