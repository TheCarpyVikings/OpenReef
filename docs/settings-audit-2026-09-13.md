# Settings audit — 2026-09-13

Reece: "the whole thing is getting crowded. Simplify. Move valuable and regularly accessed
settings and data to the correct screens. Reserve Settings for settings only."

Method: every one of the 30 sections rendered through the test harness with a real normalised
config, then measured (fields, checkboxes, action buttons, pills, prose words) and read. Five
sections need runtime state the harness lacks (Sensors, NPS, Hatchery, Lighting, Energy) and
were read from source instead.

## 1. What is wrong, in one paragraph

Settings is one flat list of 30 collapsible sections in no user-facing order, holding about
8,000 words. Roughly a third of that is not settings: live readouts (System Check, Lighting
"today", ATO duty), operations (AWC calibration and flood acknowledge, timelapse grab/clear,
capture-now, alert ack/mute, cysts-pouch stamp), and regularly-edited *data* (the coral
registry, the NPS species list and food shelf, the maintenance task list). Another third is
explanatory prose that reads like a manual and cannot be collapsed. The cooling section was the
worst offender until 0.7.175 and is the pattern for the fix: readouts and controls go to a
dialog off the feature's own screen; Settings keeps fields.

## 2. Section by section

Order is today's render order. Verdict: **keep** (settings), **trim** (collapse prose or drop
a duplicate), **move** (something inside belongs on another screen).

| # | Section | Size | Verdict | What moves, and where |
|---|---|---|---|---|
| 1 | Profile | 6 fields | keep | — |
| 2 | Guide & buddy | 3 buttons | keep | — |
| 3 | Mission Control | 8 checks | keep | fold into a **Display** group |
| 4 | Live Stats | 3 checks | keep | fold into **Display** |
| 5 | Sensors | mapping + Apex guide | trim | Apex/Trident beta helper prose → "How this works" |
| 6 | Cooling headroom | 27 fields, 713 words | trim | prose → "How this works" (readouts already moved, 0.7.175) |
| 7 | Manual Tests | 9 checks, preset | keep | preset button already on the Manual tab; drop here |
| 8 | Maintenance | 17 checks, 461 words, 13 pills | **move** | the task list (add / remove / ten "suggested") is data → **Maintenance tab**, "Manage tasks" dialog. Reminders stay |
| 9 | Dosing | 6 fields, 8 checks, 423 words | trim | channel setup is config and stays; prose → "How this works" |
| 10 | Automatic Water Change | 32 fields, 20 checks, 564 words, 8 sub-sections | **move** | calibration ceremony (calibrate / run / tubing replaced) and **Ack flood** are operations → **Water Change tab** dialog; Simulation toggle is already on the tab (empty state + demo strip) → drop the third copy |
| 11 | Mixing Station | 22 fields, 736 words | trim | calibration already on the tab; prose → "How this works" |
| 12 | Automated NPS | 10 fields, species library, food shelf | **move** | **Species you keep** (24 checkboxes, grouped) and the **Food shelf** (11 presets + product cards) are livestock/inventory data → **NPS tab**, "Species & shelf" dialog. Feed-exchange, truce and the food-pump creators stay |
| 13 | Brine hatchery | 18 fields | **move** | "Cysts opened" stamp is an operation → the hatchery rack tile. Vessel setup, container ledger and enrichment defaults stay; prose → "How this works" |
| 14 | Cultures | 9 fields, jars | keep | — |
| 15 | Equipment | mapping list | keep | — |
| 16 | Cameras | list | keep | — |
| 17 | Auto-capture | 4 fields, 9 checks | trim | **Capture now** already on the Cameras tab → drop here |
| 18 | Reef timelapse | 8 fields | **move** | **Grab** (duplicate) and **Clear** (destructive, settings-only) → Cameras tab timelapse section |
| 19 | Live overlay & tank card | 6 checks | keep | fold into **Display** |
| 20 | Feed-watch | 4 fields | keep | — |
| 21 | Vision (Frigate) | 7 fields | keep | — |
| 22 | Reef Pulse | 17 checks, 766 words | trim | block descriptions → one-line labels + "How this works"; fold into **Display**. Open question: the per-device **face** pick is used when you set up a wall — stays here unless Reece wants it on the Present button |
| 23 | Tank diagram | 3 fields + coral registry (416 words, 39 hints) | **move** | the **Reef layer coral registry** (pick species / colour, add, starter set) is livestock data → **Diagram tab**, "Reef layer" dialog. The three mapping fields stay |
| 24 | Mode Actions | 6 fields, presets, schedules | keep | — |
| 25 | Alerts | escalation, quiet hours + live list | **move** | the per-sensor **Ack / Mute 1h / Mute 24h** list is live state and exists nowhere else → **Mission Control** attention area (and Log). Escalation + quiet hours stay |
| 26 | Lighting schedule | 6 fields + "today" readout | keep | the computed window is a preview of the setting; acceptable |
| 27 | Interlocks | 3 fields, 6 checks, ATO duty pill | keep | — |
| 28 | Energy Totals | 6 fields | keep | — |
| 29 | System Check | 11 fields, 5 pills, 389 words, 6 sub-sections | **move** | it is a diagnostics page: Trust Check rows + refresh, the readiness table, Validate, Copy support summary → a **System Check dialog** off the Mission Control system cards (they already deep-link here). Watchdog, Probe health, Edge failsafes and Reef Replay fields stay |
| 30 | Backup & restore | 2 buttons | keep | — |

## 3. The structure

Thirty flat sections become six groups in the order of the nav rail, each with a heading and
a jump chip at the top of the tab:

1. **Profile & display** — Profile, Guide & buddy, Mission Control, Live Stats, Overlay, Reef
   Pulse, Tank diagram
2. **Sensors & tests** — Sensors, Manual Tests, Cooling headroom, Lighting schedule
3. **Water** — Dosing, Automatic Water Change, Mixing Station, Maintenance
4. **Feeding** — NPS, Brine hatchery, Cultures
5. **Watch** — Cameras, Auto-capture, Timelapse, Feed-watch, Vision
6. **Safety & system** — Equipment, Mode Actions, Alerts, Interlocks, Energy, System Check,
   Backup

Plus one shared helper, `_howItWorks(id, html)`: a collapsed "How this works" block (the
pattern the Dosing Advisor already uses) so the manual-length paragraphs in Cooling, Mixing,
AWC, Hatchery, Dosing, Pulse and Sensors collapse by default and the fields sit at the top.

## 4. Stages

Each stage is its own release, tests in lockstep, no change to any saved config shape.

- **Stage A — structure and trims (no behaviour change).** Six groups + jump chips;
  `_howItWorks` on the seven prose-heavy sections; drop the four duplicates (capture-now,
  timelapse grab, AWC simulation toggle, manual-tests preset).
- **Stage B — operations out.** Alerts ack/mute → Mission Control; AWC calibration + Ack flood
  → Water Change dialog; timelapse Clear → Cameras; Cysts opened → hatchery tile; System Check
  readouts → dialog off the Mission system cards.
- **Stage C — data out.** Coral registry → Diagram dialog; NPS species + food shelf → NPS
  dialog; Maintenance task editor → Maintenance tab.

## 5. Decisions for Reece

1. Stage order A → B → C, one release each? (Recommended: yes — A is safe and immediately
   visible; B and C each touch a feature tab and deserve their own soak.)
2. Group names and membership in §3 — anything you would file elsewhere?
3. Reef Pulse: keep the per-device face pick in Settings, or move it to the Present button?
4. Maintenance task editor: a dialog on the Maintenance tab, or an inline "Manage tasks"
   section at the bottom of that tab?

## 6. Decisions (Reece, 2026-09-13)

1. One release per stage — agreed.
2. Groups as in §3 — agreed.
3. Reef Pulse face pick — Reece asked for a recommendation. There are two pickers: the
   **saved faces** (rewrite the twelve wall toggles in config) and the **on-this-screen face**
   (localStorage, per device, so the wall iPad can wear a different face). The saved faces are
   a setting and stay. The per-device face is what you reach for standing at the wall, so it
   belongs on the Pulse wall's own control strip (0.7.34's mode switching already lives
   there). Recommendation: move the per-device pick in Stage B, keep the saved faces here.
4. Maintenance task editor — Reece asked for the options explained. **Dialog**: a "Manage
   tasks" button on the Maintenance tab opens a modal with the list, add/remove, cadence and
   the ten suggested tasks; editing is a deliberate act, the tab stays a checklist, and it
   matches the cooling and System Check dialogs. **Inline**: a collapsed "Manage tasks"
   section at the foot of the tab; one tap fewer, but the page grows and remove buttons sit
   near the done-ticks on a phone. Recommendation: dialog. Awaiting Reece's call.

## 7. Stage A — built as 0.7.176 (2026-09-13)

- `_settingsGroups()` + `_settings()`: six groups in nav-rail order, `#or-group-<id>`
  anchors, sticky jump chips (`settings-jump` scrolls the group into view). Existing deep
  links (`data-section` / `or-section-<id>`) are untouched.
- `_howItWorks(id, body)`: closed by default, persisted through the same
  `toggle-health-section` state as the Mission Control sections (`how-<id>`). Applied where
  the audit found paragraphs over ~70 words: cooling forecast (114 w) and vent (84 w), the
  mixing rate explainer (115 w), the hatchery pouch/fridge pair and the enrichment/first-dose
  pair. Reef Pulse already had a `<details>` wall guide, so it was left. AWC and Dosing had
  nothing over 40 words — their weight is fields, which is correct for Settings.
- Duplicates dropped: Capture now, Grab a frame now, Apply suggested routine (each now points
  at its tab). The AWC demo-mode toggle STAYS: with real hardware configured and demo off, the
  Water Change tab has no other way into demo mode.
- Tests: new `tests/test_panel_settings.mjs` (4). Mixing and NPS suites open their how blocks
  before reading the copy.

## 8. Stage B — built as 0.7.177 (2026-09-13)

Operations out of Settings, each to the screen where the thing it acts on is seen:

| moved | from | to |
|---|---|---|
| Ack / Mute 1h / Mute 24h per sensor | Settings → Alerts | Mission Control → Attention rows (`_alertActionButtons`, rendered under the issue that raised it; issues now carry `sensorId`). Settings keeps notifications, escalation, quiet hours, history. |
| Pump calibration (calibrate, timed runs, multi-point fit, tubing replaced, second source) | Settings → AWC | Water Change tab → **Pumps & calibration** dialog (`_awcPumpsDialog`, `_awcPumpCard`). Settings keeps each pump's switch entity and shows its ml/s. |
| Flood consent ("I understand — run without a leak sensor") | Settings → AWC | The same dialog AND a banner at the top of the Water Change tab (`_awcFloodNotice`). Settings says where to acknowledge and keeps the quiet "acknowledged" reminder. |
| Clear timelapse | Settings → Timelapse | Cameras tab → Timelapse header, disabled when there are no frames. |
| "Opened a new pouch" cysts stamp | Settings → Brine hatchery | The hatchery's own tile (`_npsPouchLine`: pouch age + New pouch). Settings keeps the age sentence. |
| Trust Check panel, readiness snapshot, Advanced diagnostics, Reef Replay, Refresh checks, Copy support summary, Test notification | Settings → System Check | **System Check** dialog (`_systemCheckDialog`), opened from the Mission Control system cards, the Trust Check summary card (`_missionSummaryCard` grew `opts.action`) and a Full System Check button on the Trust panel. Settings keeps last backup review, Watchdog, Probe Health, Edge Failsafes (`_systemCheckParts` feeds both). |
| Per-device Pulse face | Settings → Reef Pulse | The Pulse wall's control card, under the mode list (`_pulseDeviceFacesMarkup`). A wall that may not change mode still renders no card — that contract predates this and stands, so the device face is only pickable where mode switching is allowed. Saved faces stay in Settings. |

Stayed in Settings on purpose: the AWC demo-mode toggle (see §7).

Tests: `test_panel_settings.mjs` 8 (+4), AWC flood test reads the dialog body, cultures and
NPS pouch tests read the tile line. All panel suites green.

## 9. Stage C — built as 0.7.178 (2026-09-13)

Data editors out of Settings, each a dialog off the tab that shows the data (Reece chose the
dialog over an inline section, §6):

| moved | from | to |
|---|---|---|
| Reef layer coral registry (species/colour pickers, add, starter set) | Settings → Tank diagram | Diagram tab → **🪸 Reef layer** dialog (`_coralDialog` wraps `_coralRegistryMarkup`). Settings keeps system type, aquascape and the three wall toggles. |
| Species you keep + Food shelf (presets, product cards) | Settings → Automated NPS | NPS tab → **Species & shelf** dialog (`_npsLibraryDialogBody` re-derives the library from the summary and lazy-loads it). Settings keeps the enable toggle, feed-exchange, truce, food-pump creators and the water-exchange link. The NPS tab body itself still carries no forms — the dialog renders globally. |
| Task editor (add, remove, suggested, cadence, steps) | Settings → Maintenance | Maintenance tab → **Manage tasks** dialog (`_maintenanceTasksDialogBody`). Settings keeps tracking, AWC logging and reminders. |

Every editing dialog carries `_saveControls()` in its head, so a change made there saves
without a trip to Settings. All three flags clear on any tab change.

Tests: `test_panel_settings.mjs` 9 (+1); NPS and maintenance suites read the dialog bodies
where they used to read Settings.

## 10. Where this leaves Settings

Fields, toggles and mappings only, in six groups, ~4,000 words lighter. Every readout, every
operation and every livestock/stock editor now lives on its own screen or in a dialog off it.
Two things stayed by design: the AWC demo-mode toggle (§7) and the Lighting "today" window,
which is a preview of the setting it sits under.
