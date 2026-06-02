# OpenReef Product Roadmap

OpenReef is an open-source, Home Assistant-native reef controller intended to compete with Neptune Apex on capability while being easier to install, understand, and trust.

Use this roadmap as the working checklist. Detailed Apex comparison and Labs inventory live in [OPENREEF_COMPETITIVE_AUDIT.md](OPENREEF_COMPETITIVE_AUDIT.md).

## What Is Next

These are the next useful passes before widening beta beyond trusted testers.

- [ ] Make copied smoke-test text setup-neutral so it does not list only the current user's sensors/equipment.
- [ ] Add low-memory HA OS smoke-test notes.
- [x] Add rollback and beta reset instructions (docs/BETA_ROLLBACK_AND_RESET.md).
- [x] Add first Python tests for config migration (dependency-free, `tests/test_config_migration.py`; caught and fixed a corrupted-block migration crash). Entity-search/safe-toggle tests still need a HA test harness.
- [ ] Add first frontend smoke-test notes/screenshots for desktop and mobile.
- [x] Add nitrate, phosphate, dissolved oxygen, leak, water-level, flow, and PAR sensors as optional Core mappings.
- [x] Add Apex/Trident beta setup guide with Apex controller, Trident, Trident NP, FMM, and full-ecosystem presets.
- [x] Add Reef Health Score V2.3 in Core: Apex/read-only friendly, parameter-specific trends, learning mode, compact default with expandable insight UI.
- [x] Add Dosing & Consumption Advisor V1 (advisory): Trident-style Alk/Ca/Mg consumption rates, projection-to-limit, and advisory dose tips. Reuses Reef Health Score stability as the single source of truth.
- [x] Add Manual Chemistry V1: manual entry, configurable profile-based schedules, freshness scoring, history, and Dosing Advisor fallback from manual results.
- [x] Add Manual Chemistry V1.1: charted manual-test trends and batch historical test entry.
- [x] Add Manual Chemistry V1.2: per-parameter target/freshness tuning plus CSV export/import helpers.
- [x] Add Dosing Advisor V1.3 safety overhaul: product-system setup, verified-strength gates, kalkwasser safety handling, and copied dosing summaries.
- [ ] Add Maintenance Tasks V1 without Google dependency.

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

## In Progress / Needs Smoke Testing

- [ ] Beta tester install and feedback flow with a real external tester.
- [ ] Apex/Trident guided setup with a tester who has Apex entities already in Home Assistant.
- [ ] Long-range trends on a Home Assistant instance with more than 30 days of recorder history.
- [ ] Mobile setup and settings on multiple phone sizes.
- [ ] Low-memory HA OS VM repeat-use testing.
- [ ] Persistent notification behaviour over several days.
- [ ] ATO duty cycle over several days.
- [ ] Scheduled modes over several days.

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
- [ ] Probe health/last-seen checks.
- [x] Apex/Trident import helper for HA-synced entities.

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

### Chemistry And Dosing Parity

- [ ] Manual water test entry.
- [ ] Chemistry history dashboard.
- [ ] Target ranges by parameter.
- [ ] Dosing log.
- [ ] Dosing reminders.
- [x] Advisory dose calculator.
- [ ] Trident/Apex synced chemistry display.
- [x] Trident-style alkalinity/calcium/magnesium trend cards.
- [ ] Trident NP-style nitrate/phosphate trend cards.
- [ ] Controlled dosing guardrails, advisory first.
- [ ] Automated dosing only after safety review and smoke tests.

### Water And Maintenance Parity

- [ ] Maintenance task list.
- [ ] Recurring task generation.
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
- [x] Guided onboarding tour V1 (Phase 1): in-panel cartoon guide with spotlight coach-marks over Mission Control, Cheeky/Professional tone toggle, emoji placeholder avatar that auto-swaps to real art. Phases 2 (walking avatar), 3 (live-state reactions), 4 (optional TTS) to follow.
- [ ] Open hardware recommendations.
- [ ] Ready-made OpenReef units for non-technical reef keepers.

## Ready-Made Unit Track

- [ ] Supported hardware list.
- [ ] Recommended HA OS device profile.
- [ ] Preinstalled OpenReef image or appliance setup guide.
- [ ] First-run setup checklist for customers.
- [ ] Backup and restore instructions.
- [ ] Remote support-safe diagnostics workflow.
- [ ] Update strategy.
- [ ] Recovery/reset instructions.
- [ ] Optional starter kit hardware map: temp probe, pH path, smart plugs, leak sensor, ATO relay, dosing path.

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
| Camera | `CameraScreen.tsx`, camera API routes | Live Cameras V1 in Core (MJPEG, grid + focus, Mission Control card) | Add HLS/recording/PTZ |
| Reef diagram | `ReefDiagramScreen.tsx` | Labs/reference | Equipment visualization phase |
| Calibration | `SettingsScreen.tsx` calibration section | Labs/reference | Monitoring parity |
| AI advisor | `AIChemistryAdvisor.tsx`, `ai-service.ts` | Labs/reference | Read-only AI phase |
| Guardian/avatar/TTS | `GuardianScreen.tsx`, `SimliAvatar.tsx`, TTS route | Labs/reference | Optional AI phase |
| Coral spawning | `SpawningScreen.tsx`, spawning API | Labs/reference | Advanced opt-in phase |
| Google Sheets sync | Sheets API routes | Labs/reference | Optional export/sync later |
| Google Tasks sync | Tasks API routes | Labs/reference | Optional sync after local Tasks V1 |

## Release Gate For Every New Feature

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
