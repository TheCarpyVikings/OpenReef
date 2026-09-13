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
