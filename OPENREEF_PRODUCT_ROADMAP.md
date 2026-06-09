# OpenReef Product Roadmap

OpenReef is the open, Home Assistant-native **intelligence layer for reefing** — software that runs on any HA hardware (including a reefer's existing Apex, Trident, HYDROS, ESPHome, probes, and smart plugs) and adds the trust, prediction, and camera/control-event context that hardware-led controller ecosystems still leave exposed. It reaches Apex parity, then leapfrogs.

Use this roadmap as the working checklist. The full market teardown (Apex, HYDROS, GHL, Red Sea, Reef Factory, open-source peers, AI frontier), the 6 universal failures, and the leapfrog ladder live in [OPENREEF_COMPETITIVE_AUDIT.md](OPENREEF_COMPETITIVE_AUDIT.md).

## Strategy: Intelligence Layer + Trust Moat

The whole controller category still leaves the same software trust gap — reliability confidence, silent failure, notification confidence, setup clarity, cross-vendor intelligence, and incident context. **Nobody owns trust.** That is OpenReef's headline bet.

### Trust Moat (headline leapfrog)

The category's deepest unmet need: a controller you can trust to catch problems and keep a tank alive when things fail. Build these as HA-native slices, reusing the shipped alert-notification + daily-tick + maintenance-reminder engines.

- [x] **OpenReef Trust Check V1** — visible readiness panel for stale sensors, notification test status, camera reachability, local incident-history health, unsafe mappings, armed unavailable devices, backup-review age, and heartbeat/restart survival.
- [x] **Controller watchdog + heartbeat V1** — scheduled all-clear heartbeat, optional HA notify target, and missed-heartbeat recovery notification.
- [x] **Probe/sensor health V1** — stale last-updated detection, flatline detection, impossible-jump hints, and display/sump temperature mismatch cross-check.
- [x] **Escalating multi-channel alerts V1** — persistent notification + optional phone push + repeat cadence + acknowledgement + optional siren/light outputs.
- [x] **Tank Black Box / Reef Replay V1** — incident timeline combining alert history, activity log, captures, and feed-watch sessions. Parameter-graph overlays and share/export bundles remain future polish.
- [x] **Edge failsafes V1** — parameterised ESPHome recipes for heater/ATO/return-pump local safety plus Trust Check review gating. Kit-specific pin maps and bench validation remain part of the curated-kit hardware track.

### Trust Moat Implementation Contract

Keep the first Trust Moat pass additive only:

- [x] Add config blocks for `watchdog`, `sensorHealth`, `alertEscalation`, and `trustCheck`.
- [x] Add HA service/websocket actions for alert acknowledgement, notification test, trust-check refresh, and heartbeat status.
- [x] Preserve existing configs through normal migration; no breaking schema or service changes.
- [x] Keep automated dosing behind a hard safety wall. Advisory dosing is already a strength; unsafe automation would damage the trust brand.

### Tier 2 — Intelligence (longer-horizon vision)

Software-intelligence plays OpenReef can make defensible when grounded in local HA data and OpenReef's own event history. These are what get the community — and Neptune — talking.

- [ ] **Predictive Reef Guardian** — local-first forecasting ("KH trending below 7 in ~5 days at current consumption — nudge the dose"); builds on the Dosing Advisor + Reef Health trends.
- [ ] **Computer-vision tank intelligence** (on Camera V2) — fish not eating / head-count ("is a fish missing") / aggression / coral growth / pest & disease spotting / equipment anomalies.
- [ ] **Natural-language "ask your tank" copilot** — Q&A over the user's real data + activity log.
- [ ] **Opt-in, privacy-first benchmarking** — "tanks like yours dose X; your alk consumption is 80th percentile."

Do not overclaim AI. ReefMind/ReefCtrl-style tools are real; OpenReef's defensible angle is local-first intelligence tied directly to HA control events, camera evidence, safety interlocks, and private user data.

## What Is Next

These are the next useful passes before widening beta beyond trusted testers.

- [x] Build Trust Check V1 with readiness categories, notification test, and heartbeat status.
- [x] Add probe/sensor health V1: stale last-updated, flatline, impossible jump, and redundant-temperature mismatch hints.
- [x] Add alert acknowledgement + repeat/escalation settings before adding more automation.
- [x] Add Tank Black Box / Reef Replay V1 using existing alert history, activity log, captures, and feed-watch sessions.
- [x] Add ESPHome edge-failsafe recipe V1 and Trust Check review gate.
- [x] Add Trust Moat smoke-test checklist for live HA/browser/hardware verification.
- [ ] Polish Apex switcher flow: Trident/Trident NP synced chemistry display, import summary, support summary wording.
- [x] Make copied smoke-test text setup-neutral so it does not list only the current user's sensors/equipment.
- [ ] Add low-memory HA OS smoke-test notes.
- [x] Add rollback and beta reset instructions (docs/BETA_ROLLBACK_AND_RESET.md).
- [x] Add first Python tests for config migration (dependency-free, `tests/test_config_migration.py`; caught and fixed a corrupted-block migration crash). Entity-search/safe-toggle tests still need a HA test harness.
- [ ] Add first frontend smoke-test notes/screenshots for desktop and mobile.
- [x] Add nitrate, phosphate, dissolved oxygen, leak, water-level, flow, and PAR sensors as optional Core mappings.
- [x] Add Apex/Trident setup guide with helper choices for Apex controller, Trident, Trident NP, FMM, and full-ecosystem presets.
- [x] Add Reef Health Score V2.3 in Core: Apex/read-only friendly, parameter-specific trends, learning mode, compact default with expandable insight UI.
- [x] Add Dosing & Consumption Advisor V1 (advisory): Trident-style Alk/Ca/Mg consumption rates, projection-to-limit, and advisory dose tips. Reuses Reef Health Score stability as the single source of truth.
- [x] Add Manual Chemistry V1: manual entry, configurable profile-based schedules, freshness scoring, history, and Dosing Advisor fallback from manual results.
- [x] Add Manual Chemistry V1.1: charted manual-test trends and batch historical test entry.
- [x] Add Manual Chemistry V1.2: per-parameter target/freshness tuning plus CSV export/import helpers.
- [x] Add Dosing Advisor V1.3 safety overhaul: product-system setup, verified-strength gates, kalkwasser safety handling, and copied dosing summaries.
- [x] Add Maintenance Tasks V1 without Google dependency: HA-native recurring tasks (curated + custom), every-N-days cadence, due/overdue tracking, mark-done + history, Maintenance tab + Mission card + Attention surfacing + modest Reef Health nudge, and a `record_task_completion` service. (v0.4.80)

## Product Rules

- [x] Home Assistant-native Core is the production path.
- [x] Labs/old Next.js code is preserved as migration reference.
- [x] Control stays locked until mapped and explicitly armed.
- [x] Entity search must be targeted and capped.
- [x] No feature may fetch all HA states by default.
- [x] Browser responses must not expose HA tokens, Supervisor tokens, API keys, or secrets.
- [x] Every automated action needs preview, confirmation, logging, and a disable path.
- [ ] Every feature slice must pass desktop, mobile, restart, refresh, and low-memory smoke tests.

## Done / Core Beta

### Foundation

- [x] HACS custom integration install path.
- [x] HA-native OpenReef sidebar panel.
- [x] Single OpenReef config entry.
- [x] Core settings stored in the integration config.
- [x] Optional Labs/add-on separated from the stable controller path.
- [x] Support summary, beta smoke test, and feedback template copy tools.
- [x] Diagnostics with secret redaction.
- [x] Repair issues for missing mappings and unavailable armed equipment.

### Monitoring

- [x] Display tank temperature.
- [x] Sump temperature.
- [x] pH.
- [x] Salinity.
- [x] ORP.
- [x] Alkalinity.
- [x] Calcium.
- [x] Magnesium.
- [x] Nitrate.
- [x] Phosphate.
- [x] Dissolved oxygen.
- [x] Leak detector.
- [x] High and low water-level sensors.
- [x] Flow rate.
- [x] PAR.
- [x] Room temperature.
- [x] CO2.
- [x] Humidity.
- [x] Optional sensor enable/disable.
- [x] Targeted entity suggestions.
- [x] Live Stats.
- [x] Per-sensor trend modal with 1h, 6h, 24h, 7d, and 30d ranges.

### Control And Safety

- [x] Safe mapped switch control.
- [x] Explicit arming per equipment item.
- [x] Disarmed controls locked in UI.
- [x] Equipment profiles for ATO, heater/chiller, return pump, skimmer, display wavemaker, lighting, doser, feeder, RODI, and other.
- [x] Feed, Maintenance, Running, and custom modes.
- [x] Mode previews before control.
- [x] Mode timers and auto-return.
- [x] Mode schedules with multiple times per day.
- [x] ATO duty cycle: on duration and interval.
- [x] ATO block/warning when return flow is not confirmed.
- [x] Skimmer auto-off helper when return pump is off.
- [x] Heater requires display tank temperature warning.
- [x] Display wavemaker restart warnings and reminders.
- [x] Activity log for mode and ATO actions.

### Dashboard

- [x] Mission Control.
- [x] Reef Health Score V2.3 with profile-aware weighting, parameter-specific trend interpretation, learning mode, hard safety caps, and compact explainable/expandable insight UI.
- [x] Dosing & Consumption Advisor (advisory): Alk/Ca/Mg consumption rate, projection-to-limit, advisory dose tips, and borrowed stability. Mission card + settings, hideable.
- [x] Configurable Mission Control cards.
- [x] Attention section for alerts, missing mappings, interlocks, and armed unavailable equipment.
- [x] Controls screen.
- [x] Energy totals and per-equipment energy mappings.
- [x] Energy display in Wh.
- [x] Settings sections collapsed by default.
- [x] Theme color picker.
- [x] System Check.
- [x] Trust Check V1: readiness panel, watchdog heartbeat, probe-health checks, alert acknowledgement/escalation, and Reef Replay incident timeline.

## In Progress / Needs Smoke Testing

- [ ] Beta tester install and feedback flow with a real external tester.
- [ ] Apex/Trident guided setup with a tester who has Apex entities already in Home Assistant.
- [ ] Long-range trends on a Home Assistant instance with more than 30 days of recorder history.
- [ ] Mobile setup and settings on multiple phone sizes.
- [ ] Low-memory HA OS VM repeat-use testing.
- [ ] Persistent notification behaviour over several days.
- [ ] ATO duty cycle over several days.
- [ ] Scheduled modes over several days.

## Camera V2 Track

Cameras that fuse live video with OpenReef's data — the angle neither a Neptune Apex (no camera)
nor a generic cam app (no tank data) can match. Built one phase at a time; tick as each ships.

- [x] **A. Event-triggered clip capture** — auto-record a short clip (snapshot fallback) when an
  alert goes critical/warning, a mode fires, or safety trips. User-configurable triggers,
  keep-last-N auto-prune, Recordings gallery linked to the activity log. Live view also upgraded to
  smooth WebRTC. *(shipped + hardware-verified, v0.4.72)*
- [x] **B. Reef timelapse** — scheduled snapshots (configurable cadence, daylight-window only) played
  back in-panel as a zero-ffmpeg slideshow with Full-day/Growth modes. 4-tier downsampling retention
  (every frame → 1/day → 1/week → 1/month) keeps months of growth in a few hundred frames. Reuses A's
  storage + serving. *(shipped, v0.4.73)*
- [x] **C. Live overlay + shareable tank card** — user-selected stats (+ Reef Health, tank name) burned
  onto the live feed with the health-reactive Reef Buddy and a rotating anti-Apex quip (cheeky + calm only,
  shown to everyone — the dig is the point). One-tap **Share card** bakes it all into an image via canvas
  → native share sheet / download. *(shipped, v0.4.74)*
- [x] **D. Feed-watch** — applying Feed mode records a **snapshot burst** across the whole feeding window
  (bounded by the feed timer) as a scrubbable **feed session** in a Feeds view, to confirm every fish came
  out and ate. Supersedes the single Phase A feed clip while on. *(shipped, v0.4.75)*

**Camera V2 arc complete (A→D).**

## Apex Parity

### Monitoring Parity

- [x] Temperature, pH, salinity, ORP, alkalinity, calcium, magnesium.
- [x] Nitrate first-class Core sensor.
- [x] Phosphate first-class Core sensor.
- [x] Dissolved oxygen optional sensor.
- [x] Leak sensor mapping.
- [x] Optical/high/low water level sensor mapping.
- [ ] Liquid level/depth sensor mapping.
- [x] Flow sensor mapping.
- [x] PAR sensor mapping.
- [ ] Additional probe/module grouping.
- [ ] Probe calibration helpers.
- [x] Probe health/last-seen checks.
- [x] Apex/Trident import helper for HA-synced entities.
- [x] Trust Check surface for stale/unavailable mapped sensors.

### Control Parity

- [x] Outlet/switch control through HA entities.
- [x] Feed and maintenance modes.
- [x] Mode schedules.
- [x] Energy/power visibility for mapped devices.
- [ ] Auto feeder scheduling.
- [ ] Dosing pump scheduling.
- [ ] Dosing pump manual control guardrails.
- [ ] Pump profiles through HA entities.
- [ ] Lighting profiles through HA entities.
- [ ] Return pump/feed/maintenance interlock templates.
- [ ] Leak-triggered emergency actions.
- [ ] Flow-triggered warnings and actions.
- [ ] Water-level-triggered warnings and actions.
- [ ] Power-monitor anomaly warnings.
- [x] Heartbeat/silence alarm for OpenReef runtime health.

### Chemistry And Dosing Parity

- [x] Manual water test entry.
- [x] Chemistry history dashboard.
- [x] Target ranges by parameter.
- [ ] Dosing log.
- [ ] Dosing reminders.
- [x] Advisory dose calculator.
- [ ] Trident/Apex synced chemistry display.
- [x] Trident-style alkalinity/calcium/magnesium trend cards.
- [ ] Trident NP-style nitrate/phosphate trend cards.
- [ ] Controlled dosing guardrails, advisory first.
- [ ] Automated dosing only after safety review and smoke tests.
- [ ] Dosing remains advisory until Trust Check, alert acknowledgement, and dose-log guardrails are smoke-tested.

### Water And Maintenance Parity

- [x] Maintenance task list.
- [x] Recurring task generation.
- [ ] Reagent tracking.
- [ ] Filter/media replacement tracking.
- [ ] Manual water-change logging.
- [ ] Water-change schedule and reminders.
- [ ] AWC preview/simulation.
- [ ] AWC armed workflow.
- [ ] AWC interlocks for high/low level, return pump, fresh reservoir, and waste reservoir.
- [ ] RODI support.
- [ ] Saltwater mixing station support.

### Lighting And Environment Parity

- [ ] Light entity mapping.
- [ ] Channel mapping for multi-channel lights.
- [ ] Lighting presets.
- [ ] Sunrise/sunset ramp schedule.
- [ ] Moonlight and lunar phase support.
- [ ] Acclimation mode.
- [ ] Refugium light schedule.
- [ ] Ventilation/fan helpers from CO2, humidity, and room temperature.

## Better Than Apex

- [x] OpenReef Trust Check readiness panel.
- [x] Controller heartbeat + silence alarm.
- [x] Sensor/probe stale, flatline, redundant-temperature mismatch, and impossible-jump detection.
- [x] Alert acknowledgement + escalating multi-channel loop.
- [x] Tank Black Box / Reef Replay incident timeline.
- [ ] Beginner setup with no programming language.
- [ ] Visual safety builder instead of Apex-style text programming.
- [ ] Explainable alerts: what changed, why it matters, and what to check.
- [ ] Better long-range trends and range selection.
- [x] Reef Health Score V2.3 in Core.
- [x] Rate-of-change warnings.
- [ ] Anomaly timeline.
- [ ] Correlation heatmap.
- [ ] Day/night analysis.
- [ ] Weekly/monthly reef reports.
- [ ] CSV/PDF export.
- [ ] Shareable support bundle with redaction.
- [ ] Read-only AI Guardian summaries.
- [ ] AI report drafting.
- [x] Guided onboarding tour: in-panel cartoon Reef Buddy guide with spotlight coach-marks, Cheeky/Professional tone toggle, and real avatar art. Phase 2 (walking avatar between cards) and Phase 3 (live-state reactive corner buddy) shipped; Phase 4 (optional TTS/voice) shelved by decision.
- [ ] Open hardware recommendations.
- [ ] Ready-made OpenReef units for non-technical reef keepers.

## Hardware — Two Tracks

**Track A (owned): curated starter kits + recommended-hardware list.** For reefers who want Apex-like capability without learning HA from scratch. Lean, hardware-agnostic, no inventory lock-in.

- [ ] Supported / recommended-hardware list (probes, smart plugs, leak, ATO relay, dosing path).
- [ ] Recommended HA OS device profile.
- [ ] Curated starter-kit hardware map: temp probe, pH path, smart plugs, leak sensor, ATO relay, dosing path.
- [x] Blessed ESPHome edge-failsafe recipes V1: parameterised heater/ATO/return-pump example and review checklist.
- [x] Trust Check validates the recommended kit path V1: mapped sensors, notification test, camera status, and on-device failsafe notes.
- [ ] Kit-specific ESPHome pin maps and bench-test records for the chosen starter-kit hardware.

**Track B (partner, under NDA, royalty model): ready-made OpenReef appliance.** A separate reefing company manufactures turnkey units; OpenReef provides the software. This repo does not document the partner's hardware internals — but the software must support a clean appliance experience:

- [ ] First-run setup checklist for customers.
- [ ] Backup and restore instructions.
- [ ] Remote support-safe diagnostics workflow.
- [ ] Update strategy.
- [ ] Recovery/reset instructions.

## Labs Migration Tracker

| Feature | Source | Status | Target |
| --- | --- | --- | --- |
| Mission Control | `MissionControlScreen.tsx` | Migrated to Core | Keep improving |
| Live Stats | `LiveStatsScreen.tsx` | Migrated to Core | Keep improving |
| Controls | `EntitySwitch.tsx`, old HA helpers | Migrated to Core | Keep improving |
| Energy | `EnergyScreen.tsx` | Partly migrated to Core | Add power anomaly work |
| Settings | `SettingsScreen.tsx` | Partly migrated to Core | Continue simplifying |
| Entity picker | `EntityPicker.tsx`, `SafeEntityPicker.tsx` | Migrated to Core | Keep targeted/capped |
| Manual tests | `ManualStatsScreen.tsx`, `ParamHistoryModal.tsx` | Labs/reference | Chemistry V1 |
| Reef Health Score | `ReefHealthScore.tsx` | Migrated to Core V2.3 | Add history after stability soak |
| Tasks | `TasksScreen.tsx`, Google Tasks API | Labs/reference | HA-native Tasks V1 |
| Lights | `LightsScreen.tsx` | Labs/reference | Lighting phase |
| Water change/AWC | `WaterChangeScreen.tsx` | Labs/reference | Water phase |
| Analytics | `AnalyticsScreen.tsx`, analytics components | Labs/reference | Read-only analytics phase |
| Reports | `ReportsScreen.tsx` | Labs/reference | Reports phase |
| Camera | `CameraScreen.tsx`, camera API routes | Camera V2 A→D in Core: live WebRTC, event capture, timelapse, live overlay + shareable card, feed-watch | HLS high-quality / PTZ / motion alerts later |
| Reef diagram | `ReefDiagramScreen.tsx` | Labs/reference | Equipment visualization phase |
| Calibration | `SettingsScreen.tsx` calibration section | Labs/reference | Monitoring parity |
| AI advisor | `AIChemistryAdvisor.tsx`, `ai-service.ts` | Labs/reference | Read-only AI phase |
| Guardian/avatar/TTS | `GuardianScreen.tsx`, `SimliAvatar.tsx`, TTS route | Labs/reference | Optional AI phase |
| Coral spawning | `SpawningScreen.tsx`, spawning API | Labs/reference | Advanced opt-in phase |
| Google Sheets sync | Sheets API routes | Labs/reference | Optional export/sync later |
| Google Tasks sync | Tasks API routes | Labs/reference | Optional sync after local Tasks V1 |

## Release Gate For Every New Feature

- [ ] Trust Check still reports an honest status after the feature is enabled.
- [ ] Notification test still works, and alerts can be acknowledged.
- [ ] Fresh install opens without setup crash.
- [ ] Existing install migrates config.
- [ ] Settings can be edited for 60 seconds without losing focus.
- [ ] Entity pickers return capped suggestions only.
- [ ] Missing optional entities show empty states.
- [ ] Feature works after HA restart.
- [ ] Browser hard refresh works.
- [ ] Mobile layout is usable.
- [ ] No secrets in browser responses, logs, localStorage, diagnostics, or page source.
- [ ] HA Core memory remains stable during repeated use.
- [ ] User can disable or hide the feature if not configured.

## Decision Log

- [x] 2026-05-27: OpenReef Core is the product foundation.
- [x] 2026-05-27: Labs/Next.js remains a feature archive and optional experimental surface.
- [x] 2026-05-27: Features migrate into Core in small smoke-tested slices.
- [x] 2026-05-27: Stability beats speed.
- [x] 2026-05-30: Roadmap reset around Apex parity, Better Than Apex differentiation, and checkbox-driven owner tracking.
- [x] 2026-05-30: Dosing & Consumption Advisor ships advisory-only (no automated dosing) and reuses the Reef Health Score stability analysis as the single source of truth, so the two surfaces never disagree.
- [x] 2026-06-01: Dosing Advisor V1.1 adds manual-test freshness gates, stricter confidence checks, solution-strength calculator fields, and support-summary diagnostics before beta handoff.
- [x] 2026-06-02: Dosing Advisor V1.2 adds product presets for common dosing systems, separates exact-strength products from maintenance-style methods, and keeps Custom as the safe fallback.
- [x] 2026-06-02: Dosing Advisor V1.3 moves from per-parameter product picks to an advisory-only product-system safety model with primary/secondary products, kalkwasser guardrails, exact-advice locks, and standalone dosing summaries.
- [x] 2026-06-04: Maintenance V2 ships HA-native reminders (daily tick → persistent notification + optional phone push), fixed-day scheduling, skip/snooze, and minimal water-change volume logging.
- [x] 2026-06-04: Positioning set to "the intelligence layer for reefing"; the **Trust Moat** (watchdog/heartbeat, probe-health/drift, escalating multi-channel alerts, ESPHome edge failsafes) is the headline leapfrog after a full-market competitive audit. Predictive/vision/copilot are Tier-2 vision.
- [x] 2026-06-04: Hardware is two tracks — owner sells/recommends curated starter kits + recommended hardware; an NDA partner manufactures ready-made units for royalties (software must stay appliance-ready).
- [x] 2026-06-08: Competitive strategy tightened around evidence levels, softened anti-vendor wording, current 2026 competitors, no AI overclaim, and a reordered Trust-first build path: Trust Check/heartbeat → probe health → alert escalation → Tank Black Box/Reef Replay → Apex switcher polish → parity automation.
- [x] 2026-06-08: Trust Moat V1 implemented in Core: additive config migration, Trust Check panel, watchdog heartbeat, probe-health alerts, alert acknowledgement/escalation, notification test, heartbeat/trust WebSockets/services, and Reef Replay V1 with unit coverage.
- [x] 2026-06-08: Edge failsafe V1 added: ESPHome heater/ATO/return-pump recipe example, validation checklist, `edgeFailsafes` config, System Check review controls, and Trust Check warnings for armed life-support equipment without reviewed on-device failsafes.
- [x] 2026-06-08: Trust Moat smoke-test checklist added for live HA, browser, notification, restart, Reef Replay, and edge-failsafe review gates.
- [x] 2026-06-08: Trust Moat handoff copy completed: support summaries now include Trust Check, heartbeat, probe-health, escalation, edge-failsafe, and Reef Replay state; copied smoke-test text is setup-neutral for beta testers.
