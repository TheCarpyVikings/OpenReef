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

## 11b. Dosing Node (S3 Zero, multi-node Node 1) Variant

Running Node 1 (`docs/manual/dosingnode-s3zero-reference.yaml` — pumps only, no
physical sensors, no master relay)? §1–§10 apply unchanged, §11's relay and
float lines do NOT. Instead:

- [ ] Bench gates first: `dosingnode-s3zero-design.md` §2 — D4184 TRIG floats
      LOW (pump does not run with TRIG disconnected; 10 kΩ to GND added if it
      did), and the GP43 ROM boot chatter is understood as harmless.
- [ ] Boot log arrives over native USB (USB_CDC); no `Master Enable` entity
      exists and none is expected.
- [ ] Kalk auto-bind reports **25 of 25** (rev 3); live-food auto-bind
      **22 of 22** — the stubbed reservoir-low floats keep the counts whole.
- [ ] `Kalk Reservoir Low` and `Live Food Reservoir Low` both read **off**
      (clear) permanently — they are template stubs; the software reservoir
      ledger is the empty-guard on this node. A `reservoir_low` skip reason on
      this node is therefore impossible and would be a firmware defect.
- [ ] Explicit-bind drain + fill only; leave source 2, leak, display-high and
      the tank floats UNBOUND (they live on future nodes). The AWC runs
      without them — take the flood-failsafe acknowledgement in AWC settings
      when the panel asks (0.6.7+).
- [ ] Watchdog trip still latches: force a >180 s drain into a bucket — pumps
      killed, node latched, `Clear Lock` ("OpenReef Dosing Clear Lock")
      re-arms. This is a SOFTWARE latch; there is no relay behind it.
- [ ] Live-food chaser still works (the fresh pump it borrows is on this node,
      GP2) and still skips when a water change owns that pump.

## 12. 48-Hour Full-Arc Soak (Stage F — one node, everything on)

The arc's exit test: hourly micro-changes + source alternation + kalk + live
food + 2-part spacing running TOGETHER on one node for two days. Run it after
§11 (reefnode) or §11b (dosing node) passes, water plumbed, reservoirs sized
for ≥ 2 L of changes.

**Unattended-run posture, per topology:** the reefnode's master fail-OFF relay
+ hardware coil float are what make an unattended soak safe against a shorted
driver — do not run §12 on that topology before the relay is fitted. Node 1
has no relay by design: its soak posture is sized reservoirs (never plumb more
water than the tank can absorb), dose lines ending in air above the waterline,
the fused 12 V rail, and the flood-failsafe acknowledgement taken knowingly.
On Node 1 the 2-part spacing checks below are one-sided (no Ca head exists to
stamp its group), and source alternation lines apply only if a second source
is fitted — which on Node 1 it is not.

**Setup (once):**

- [ ] AWC schedule: interval mode, every 60 min, full-day window, 0.96 L/day
      (= 40 ml per change), simultaneous method, salt-matched fresh source(s).
- [ ] `microChangeThresholdMl` = 260; ATO configured; alternation policy ON if
      fresh2 is fitted.
- [ ] Kalk channel: continuous schedule inside its window; live food: doses
      mode with a chaser; spacing ENABLED with Alk ↔ Ca = 30 min.
- [ ] Note the starting ledger (`net imbalance` card), reservoir levels, and
      each channel's `dosed today`.

**T+1 h — first cycle:**

- [ ] Exactly one ~40 ml change ran; the ATO was NEVER suspended for it
      (micro-change path) and the panel's status card interpolated live.
- [ ] No `spacing` skips on the skip sensor — the compile-time stagger keeps
      scheduled kalk clear of any Ca head; a manual Ca dose inside the gap is
      refused with the wait time and the queue offer.

**T+24 h — cadence honesty (§G numbers):**

- [ ] ~24 changes logged (±1 at the seams); daily volume within 5 % of 0.96 L.
- [ ] ATO availability stayed ≳ 98 % (no suspend on salt-matched micro
      changes); zero missed-dose false alarms on any channel.
- [ ] Live food went STALE at its shelf life: HA forced the enable switch OFF,
      skip sensor reads `disabled`, panel shows the stale lockout. Mark
      refreshed → dosing resumes on the next sync.

**T+48 h — ledger vs history:**

- [ ] The history window now holds < 2 days of events, but the net-imbalance
      card still reads from the PERSISTENT ledger (compare against your noted
      start — the delta must equal cumulative drain − fill, not the window
      sum). This is the §G hard gate for hourly cadence.
- [ ] Reservoir `days remaining` projections match actual consumption within
      10 %; tube/wear odometers advanced ~48 h of run-seconds equivalents.
- [ ] Pull HA's network cable for one mid-hour cycle: the node still runs its
      schedule + guard chain (dose fires or skips locally, watchdogs armed);
      on reconnect HA reconciles `dosed today` without double-count and the
      ledgers catch up.
- [ ] Zero unexplained skip reasons, zero fault latches, zero watchdog trips
      across the full 48 h — anything else is a stop-ship finding.
