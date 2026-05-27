# OpenReef Product Roadmap

OpenReef is not a basic aquarium dashboard. The target is an open-source, Home Assistant-native reef controller that can compete with Neptune Apex on capability while being easier to install, understand, and trust.

This roadmap keeps the full product ambition visible while forcing every feature through small, smoke-tested releases. The old Next.js/Labs work remains valuable source material, but OpenReef Core is the production path.

## Product Principles

- **Home Assistant-native first:** core setup, monitoring, control, safety, and settings must work without the optional Labs add-on.
- **No crash paths:** no feature may request all HA state, poll broad APIs, leak tokens, or keep runaway browser work alive after leaving the page.
- **Safe control by default:** mapped equipment is read-only until explicitly armed in Settings.
- **Frictionless setup:** users choose from suggested HA entities, with manual entity ID entry only as fallback.
- **Apex-level power, OpenReef-level usability:** advanced control should feel approachable to reef keepers who are not software people.
- **Labs is preservation, not abandonment:** old features stay available as migration references until they are rebuilt safely in Core.

## Release Gates

Every feature stage must pass these before it becomes part of OpenReef Core:

- Open/refresh OpenReef repeatedly on a low-memory HA OS VM without HA disconnects or OOM.
- No full `/api/states` fetches or broad unbounded entity scans.
- Browser receives no HA tokens, Supervisor tokens, API keys, or private secrets.
- All writes go through OpenReef validation, services, or targeted WebSocket commands.
- Missing entities and optional mappings produce empty states, not crashes.
- Works on desktop and mobile.
- Settings are editable without redraw/focus loss.
- Feature can be disabled or hidden if it is not configured.

## Current Foundation

Status: **Core MVP in active beta**

- HA custom integration: `custom_components/openreef`
- HA-native sidebar panel: `custom_components/openreef/frontend/openreef-panel.js`
- Core screens: Mission Control, Live Stats, Controls, Energy, Settings
- MVP sensors: tank temperature, pH, salinity, room temperature, CO2, humidity
- Safe controls: switch mapping required, explicit arming required
- Energy: totals and per-equipment mappings, optional cost fields
- Trends: targeted one-entity history views with selectable ranges
- Labs/old Next.js work: preserved for later migration

## Roadmap Phases

### Phase 0 - Stability Baseline

Goal: make the HA-native controller boringly stable before adding complexity.

- Keep Core installable through HACS.
- Keep the optional add-on/Labs separate from Core.
- Harden setup wizard, settings editing, entity search, trends, and control toggles.
- Add smoke-test notes for low-memory HA OS.
- Document rollback and beta reset steps.

Exit criteria:

- OpenReef can be used daily without disconnecting HA.
- Entity search and trend viewing are repeatable without HA restart.
- First-time setup can be completed by a non-technical user.

### Phase 1 - Controller Essentials

Goal: match the everyday controller jobs a reef keeper expects.

- Alerts and alarms for sensor thresholds.
- Notification routing through HA notifications.
- Feed modes: fish feed, coral feed, timed pause, automatic return to running.
- Maintenance mode with timed equipment behavior.
- Mode scheduler and manual mode override.
- Equipment interlocks, for example heater blocked if temperature probe is unavailable.
- Better Mission Control summary and configurable cards.
- Persistent activity/event log.

Exit criteria:

- A user can safely run daily reef operations from Core without Labs.
- Every automated action is visible, reversible, and auditable.

### Phase 2 - Testing, Dosing, And Maintenance

Goal: turn OpenReef into a reef husbandry assistant, not just a switch panel.

- Manual water test entry for alkalinity, calcium, magnesium, nitrate, phosphate, pH, salinity, temperature.
- Test history trends and parameter target ranges.
- Maintenance task system: recurring tasks, overdue status, categories, priority.
- Optional Google Tasks migration strategy replaced or wrapped by HA-native storage first.
- Dosing log and dosing reminders.
- Simple dose calculators, gated as advisory only.
- Reagent/filter/media replacement tracking.

Exit criteria:

- A user can track reef chemistry and maintenance inside OpenReef without external spreadsheets.
- No cloud dependency is required for the core workflow.

### Phase 3 - Lighting And Environment

Goal: bring back lighting and environmental control safely.

- Light entity mapping and grouped lighting profiles.
- Manual light controls with arming/permission model.
- Sunrise/sunset schedule.
- Moonlight profile and lunar phase support.
- Acclimation mode.
- Room environment cards for CO2, humidity, room temperature, and ventilation helpers.
- Day/night analytics for pH, temperature, and lighting periods.

Exit criteria:

- Lighting works through HA entities only.
- Schedules are previewable before activation.
- No direct hardware assumptions are baked into Core.

### Phase 4 - Water Change And AWC

Goal: support manual and automated water-change workflows without unsafe automation.

- Manual water-change logging.
- Water-change schedule and reminders.
- Pre-change checklist.
- Drain/fill equipment mappings.
- AWC simulation/preview before any automation is armed.
- AWC armed mode with explicit confirmations and interlocks.
- Saltwater mixing station support later, as a separate feature gate.

Exit criteria:

- Manual water changes are useful first.
- Automated water changes cannot run until mappings, safeguards, and confirmations are complete.

### Phase 5 - Analytics And Reports

Goal: make OpenReef feel smarter than Apex while staying explainable.

- Reef Health Score migrated into Core.
- Rate-of-change charts.
- Anomaly timeline.
- Correlation heatmap.
- Day/night analysis.
- Weekly/monthly reports.
- Exportable PDF/CSV reports.
- Explainable warnings: "what changed", "why it matters", "what to check".

Exit criteria:

- Analytics are read-only and cannot affect equipment.
- Every warning links back to visible source data.

### Phase 6 - Camera And Visual Monitoring

Goal: restore camera features without tying Core stability to media pipelines.

- HA camera entity picker.
- Snapshot view.
- Low-load still-image refresh mode.
- Optional live stream view.
- Time-lapse capture planning.
- Visual comparison later, behind explicit experimental flags.

Exit criteria:

- Opening the camera screen cannot crash HA or the browser.
- Live streaming is optional and isolated.

### Phase 7 - AI Guardian

Goal: add intelligence after the controller is stable and explainable.

- AI advisor starts as read-only.
- Uses redacted, minimal reef status summaries.
- No API keys in browser or diagnostics.
- Clear "advice, not automation" labeling.
- Optional cloud provider configuration.
- Later: incident summaries, report drafting, and setup assistant.

Exit criteria:

- AI cannot control equipment.
- AI works even when disabled by showing normal non-AI Core UI.

### Phase 8 - Coral Spawning And Advanced Modes

Goal: restore specialist features once lights, pumps, schedules, and safety are mature.

- Spawning profile configuration.
- Lunar/sunset schedule helpers.
- Light and pump choreography.
- Preview timeline.
- Manual start only at first.
- Automation only after interlocks and clear warnings exist.

Exit criteria:

- Advanced modes are opt-in and never appear in beginner setup by default.

### Phase 9 - Ready-Made OpenReef Units

Goal: make OpenReef accessible to reef keepers who do not want to build HA themselves.

- HA OS image or documented appliance build.
- Preinstalled OpenReef integration.
- First-run guided setup.
- Suggested supported hardware list.
- Backup/restore path.
- Support diagnostics bundle.
- Clear tester/customer update path.

Exit criteria:

- A non-technical reef keeper can power on, join network, open HA, and complete OpenReef setup.

## Feature Migration Tracker

| Feature | Current Source | Core Status | Target Phase | Notes |
| --- | --- | --- | --- | --- |
| Mission Control | Core panel + old `MissionControlScreen.tsx` | In Core MVP | 0-1 | Continue expanding with configurable cards, alerts, events. |
| Live Stats | Core panel + old `LiveStatsScreen.tsx` | In Core MVP | 0 | Add richer HA-native trend controls and history UX. |
| Controls | Core panel + old controls/entities code | In Core MVP | 0-1 | Keep arming in Settings, switches in Controls. Add interlocks next. |
| Energy | Core panel + old `EnergyScreen.tsx` | In Core MVP | 0-1 | Improve per-device totals and cost modeling. |
| Settings | Core panel + old `SettingsScreen.tsx` | In Core MVP | 0 | Needs to become the central configuration surface. |
| Entity Suggestions | `entity-suggestions.ts`, Core WS search | In Core MVP | 0 | Keep targeted and capped. No full-state fetches. |
| Reef Health Score | `ReefHealthScore.tsx` | Labs/reference | 1/5 | Core summary first, analytics later. |
| Alerts/Alarms | `SettingsContext` alarm helpers | Labs/reference | 1 | Build HA-native alert config and repair issues. |
| Feed/Maintenance Modes | `SettingsContext` modes | Partial service support | 1 | Needs timer, preview, and return-to-running behavior. |
| Tasks/Maintenance | `TasksScreen.tsx`, Google Tasks API | Labs/reference | 2 | Prefer HA-native/local storage first; cloud sync optional later. |
| Manual Tests | `ManualStatsScreen.tsx`, history components | Labs/reference | 2 | Add chemistry entry and trends. |
| Dosing/Reminders | settings/task categories | Planned | 2 | Advisory first, automation later. |
| Lights | `LightsScreen.tsx`, lighting settings | Labs/reference | 3 | Rebuild around HA light entities and schedules. |
| Day/Night Analysis | `DayNightAnalysis.tsx` | Labs/reference | 3/5 | Depends on stable lights and sensor history. |
| Water Change | `WaterChangeScreen.tsx` | Labs/reference | 4 | Manual logging before automation. |
| Reports | `ReportsScreen.tsx` | Labs/reference | 5 | Depends on stable history and events. |
| Analytics | `AnalyticsScreen.tsx`, analytics components | Labs/reference | 5 | Read-only, explainable, downsampled data. |
| Camera | `CameraScreen.tsx`, camera API routes | Labs/reference | 6 | Start with HA camera snapshots, live stream later. |
| AI Chemistry Advisor | `AIChemistryAdvisor.tsx`, `ai-service.ts` | Labs/reference | 7 | Redacted server-side summaries only. |
| Guardian/Avatar | `GuardianScreen.tsx`, `SimliAvatar.tsx`, TTS route | Labs/reference | 7 | Optional, cloud-dependent, never required for Core. |
| Reef Diagram | `ReefDiagramScreen.tsx` | Labs/reference | 5/8 | Useful once equipment mapping is mature. |
| Spawning | `SpawningScreen.tsx`, spawning API/settings | Labs/reference | 8 | Advanced opt-in feature. |
| Public/Ready-Made Units | Docs/process | Planned | 9 | Needs install, backup, support, and hardware plan. |

## Near-Term Backlog

### Next Core Slice

- Alerts/alarms configuration in Settings.
- Mission Control alarm card.
- HA notification target selection.
- Feed and maintenance mode editor.
- Timed mode countdown and automatic return to running.
- Activity log for mode changes and manual control actions.

### Stability Hardening

- Add Python tests for mission card config migration.
- Add tests for targeted history request shape.
- Add frontend smoke checklist with desktop/mobile screenshots.
- Add diagnostics summary for Core config without secrets.
- Add "support bundle" issue template for beta testers.

### Documentation

- Update README install path for Core-only OpenReef.
- Add beta tester guide.
- Add known limitations.
- Add "Labs features are preserved but experimental" note.
- Add ready-made unit planning doc later.

## Smoke-Test Checklist Template

Use this for every feature slice.

- Fresh install opens OpenReef without setup crash.
- Existing install migrates config.
- Setup/settings forms can be edited for 60 seconds without losing focus.
- Entity pickers return capped suggestions only.
- Feature works with missing optional entities.
- Feature works after HA restart.
- Browser hard refresh works.
- Mobile layout is usable.
- No secrets in browser responses, logs, localStorage, diagnostics, or page source.
- HA Core memory remains stable during repeated use.

## Decision Log

- **2026-05-27:** OpenReef Core is the product foundation. Labs/Next.js remains a feature archive and optional experimental surface.
- **2026-05-27:** Features migrate into Core in small smoke-tested slices rather than as one large dashboard port.
- **2026-05-27:** Stability beats speed. A feature that risks HA stability stays in Labs until redesigned.
