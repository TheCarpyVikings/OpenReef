# OpenReef Competitive Audit

This audit compares OpenReef Core, old OpenReef/Labs, and Neptune Apex. The product roadmap stays short in [OPENREEF_PRODUCT_ROADMAP.md](OPENREEF_PRODUCT_ROADMAP.md).

## Sources

- [Neptune Apex A3 Series](https://www.neptunesystems.com/apex-a3-series/)
- [Neptune Trident and Trident NP](https://www.neptunesystems.com/trident/)
- [Neptune DOS](https://www.neptunesystems.com/dos/)
- [Bulk Reef Supply: What Does the Neptune Systems Apex Do?](https://www.bulkreefsupply.com/content/post/what-does-an-neptune-systems-apex-do)
- [Apex Fusion App Store listing and reviews](https://apps.apple.com/us/app/apex-fusion/id1114191823)
- [Reef2Reef Apex programming tutorial](https://www.reef2reef.com/ams/neptune-apex-programming-tutorials-part-1.685/)

## Executive Takeaway

OpenReef Core is now credible as a safe HA-native controller foundation, but it is not Apex-complete yet.

Apex is strongest because it is an ecosystem: controller, power bars, probes, leak/level/flow modules, auto tester, dosing, feeder, pumps, lights, cloud app, and lots of community examples.

OpenReef can win by avoiding Apex's biggest pain point: powerful control that often feels like programming and module management. OpenReef should offer the same control patterns through guided setup, visual safety rules, explainable alerts, and Home Assistant entity reuse.

## Source-Backed Facts

- Apex is sold as a controller ecosystem, not just an app: controller hardware, probes, outlets, modules, cloud access, and accessories.
- Apex A3 packages cover monitoring and control around temperature, pH, liquid level, leak detection, and expandable modules.
- Trident covers automated alkalinity, calcium, and magnesium testing.
- Trident NP covers automated nitrate and phosphate testing.
- DOS is positioned for precision dosing and automatic water-change workflows.
- BRS describes Apex as a central aquarium controller that monitors, controls, alerts, logs, and expands through modules and accessories.
- Public Apex tutorial content spends real time teaching programming syntax, virtual outputs, defer/min time logic, and advanced outlet behaviour.
- App Store review surfaces show that some users value Apex Fusion, while other users complain about confusing UX, stalls, and app polish.

## Product Inferences

- OpenReef should not try to clone Neptune hardware; it should read Home Assistant entities from Apex, Trident, Hydros, ESPHome, smart plugs, probes, and other hardware paths.
- The biggest OpenReef win is not only being cheaper or open source. It is making controller safety understandable to reef keepers who do not want to write logic.
- Apex parity should be built in slices: first monitor, then advise, then controlled manual actions, then carefully armed automation.
- Old OpenReef features remain valuable, but each one should migrate through the HA-native Core interface before it becomes part of the stable product.

## Apex Capability Matrix

| Capability | Apex Position | OpenReef Position | Gap |
| --- | --- | --- | --- |
| Controller foundation | Dedicated Apex hardware plus Fusion cloud | HA-native integration and sidebar panel | OpenReef depends on HA hardware/install |
| Power outlet control | Energy Bar outlets and 24V/1LINK ecosystem | HA switch entities with explicit arming | Need hardware guide and supported smart plug path |
| Power monitoring | Per-outlet monitoring through Energy Bar | Optional HA power/energy mappings | Need anomaly alerts and better per-device history |
| Temperature/pH | Core Apex monitoring | Core OpenReef monitoring | Competitive |
| ORP/salinity | Apex/Pro and module support | Core OpenReef optional sensors | Competitive if entities exist |
| Alk/Ca/Mg | Trident | Core OpenReef can display HA entities | Need import helper and chemistry-specific dashboard |
| Nitrate/phosphate | Trident NP | Not first-class Core yet | Add optional sensors and trends |
| Leak detection | Apex/FMM sensors | Not first-class Core yet | Add leak mappings and emergency actions |
| Water level/depth | Optical sensors and LLS | Not first-class Core yet | Add level/depth mappings and interlocks |
| Flow monitoring | FMK/FMM | Not first-class Core yet | Add flow mappings and warnings |
| Dosing | DOS and Trident-controlled dosing | Labs/reference only | Build advisory dosing before automation |
| Automatic water changes | DOS workflows | Labs/reference only | Build manual log, preview, then armed AWC |
| Feeding | AFS | Not Core yet | Add feeder entity mapping/schedules |
| Lighting | Apex modules/MXM/0-10V/profiles | Labs/reference only | Rebuild through HA light entities |
| Modes/programming | Fusion outlets/profiles/virtual outputs | Core visual modes and schedules | OpenReef has usability advantage |
| Alerts | Fusion alerts, email/SMS/app | Core threshold alerts and optional HA notifications | Add richer routing/escalation |
| Reports/analytics | Fusion history/graphs | Labs/reference | Add Core analytics and reports |
| Camera | Not the Apex core strength | Labs/reference | OpenReef can be better via HA cameras |
| Setup usability | Powerful but programming-heavy | Guided HA-native setup | OpenReef advantage if kept simple |

## OpenReef Core Matrix

| Area | Current Core Status | Notes |
| --- | --- | --- |
| Install | HACS custom integration | Add-on no longer required for stable Core |
| Panel | HA-native sidebar custom panel | Browser receives HA `hass` object, not tokens |
| Setup | Wizard with presets and entity suggestions | Apex/Trident beta preset exists |
| Entity access | Targeted search/runtime/history | Avoids full `/api/states` crash path |
| Monitoring | Temp, sump temp, pH, salinity, ORP, alk, calcium, magnesium, room temp, CO2, humidity | Add nitrate/phosphate/DO/leak/level/flow next |
| Trends | Single-entity targeted history with selectable ranges | Long ranges depend on HA recorder |
| Mission Control | Health cards, attention items, mode card, configurable cards | Add Reef Health Score later |
| Controls | Mapped/armed switch control only | Good safety foundation |
| Energy | Totals and per-equipment mappings | Add anomaly and standby detection later |
| Alerts | Thresholds, mute, history, persistent notifications | Add explainable guidance and routing |
| Modes | Running, Feed, Maintenance, custom modes, schedules | Strong early Apex-parity point |
| ATO safety | Duty cycle, return-pump checks | Useful differentiator |
| Wavemaker safety | Display wavemaker reminders and restart warning | User-driven safety differentiation |
| Handoff | Smoke test, feedback template, support summary | Good private beta workflow |

## Old OpenReef / Labs Inventory

| Old Feature | Files | Product Value | Migration Decision |
| --- | --- | --- | --- |
| Full dashboard shell | `DashboardApp.tsx` | Existing feature composition | Reference only |
| Controller Lite | `ControllerLiteApp.tsx` | MVP shape | Mostly superseded by Core |
| Setup wizard | `SetupWizard.tsx` | Onboarding ideas | Mostly migrated |
| Mission Control | `MissionControlScreen.tsx` | Health/alerts/tasks/equipment ideas | Continue migration |
| Live Stats | `LiveStatsScreen.tsx` | Sensor card ideas | Mostly migrated |
| Manual stats | `ManualStatsScreen.tsx`, `ParamHistoryModal.tsx` | Chemistry logging | Build Core Chemistry V1 |
| Reef Health Score | `ReefHealthScore.tsx` | Better-than-Apex summary | Build Core V1 soon |
| Energy | `EnergyScreen.tsx`, `EquipmentDetailModal.tsx` | Cost/power detail | Partly migrated |
| Tasks | `TasksScreen.tsx`, task API | Maintenance workflow | Build local/HA-native first |
| Lights | `LightsScreen.tsx` | Lighting profiles | Rebuild through HA lights |
| Water change | `WaterChangeScreen.tsx` | Manual/AWC workflow | Rebuild with preview/interlocks |
| Analytics | `AnalyticsScreen.tsx`, analytics components | Better-than-Apex insights | Rebuild read-only/downsampled |
| Reports | `ReportsScreen.tsx` | Shareable summaries | Later after history/events mature |
| Camera | `CameraScreen.tsx`, camera API | Visual monitoring | Rebuild with HA camera snapshots first |
| Reef diagram | `ReefDiagramScreen.tsx` | Equipment visualization | Later after equipment schema matures |
| AI advisor | `AIChemistryAdvisor.tsx`, `ai-service.ts` | Differentiator | Read-only, redacted, optional |
| Guardian/avatar | `GuardianScreen.tsx`, `SimliAvatar.tsx`, TTS route | Experimental UX | Optional Labs until Core is stable |
| Spawning | `SpawningScreen.tsx`, spawning API | Specialist advanced mode | Advanced opt-in later |
| Google Sheets | Sheets API routes | Existing manual-readings sync | Optional export/sync later |
| Google Tasks | Tasks API routes | Existing tasks sync | Optional sync after local Tasks V1 |
| Calibration | `SettingsScreen.tsx` calibration | Probe usability | Add Core calibration helpers |

## Apex Praise To Match

- Apex gives reef keepers remote monitoring and control from anywhere.
- The ecosystem can automate equipment responses to sensor changes and emergencies.
- Trident/Trident NP automate major reef chemistry tests.
- DOS supports dosing and automatic water-change workflows.
- Energy Bar/FMM/modules create a broad hardware path for outlets, power, leak, level, and flow.
- Community examples and tutorials help users build advanced logic.

## Apex Complaints To Attack

- Setup and outlet programming can be intimidating, especially for non-technical reef keepers.
- Public tutorials describe scattered docs, a unique programming language, and confused users around ATK, timers, feed mode, and alerts.
- App Store reviews call out confusing workflow, launch stalls, clunky design, and missing platform-native features.
- Hardware/module costs add up quickly.
- Some product-review surfaces show mixed ratings for accessories such as flow sensors, liquid level sensors, ATK, DDR, and EB832.
- Heavy ecosystem lock-in means users may feel forced into one vendor.

## OpenReef Opportunities

- Reuse Home Assistant entities instead of forcing one hardware ecosystem.
- Make setup suggestion-driven instead of copy/paste or programming-driven.
- Replace Apex-style programming with visual modes, schedules, interlocks, and safety previews.
- Make every alert explain what happened, why it matters, and what to check.
- Treat support as a first-class product feature with redacted summaries and shareable diagnostics.
- Build ready-made units for reef keepers who want Apex-like capability without learning HA from scratch.
- Support Apex owners by importing HA-synced Apex/Trident entities rather than asking them to rip out hardware.

## Recommended Build Order

1. Stabilize beta handoff and low-memory testing.
2. Add missing first-class monitoring sensors: nitrate, phosphate, dissolved oxygen, leak, water level, flow, PAR.
3. Add Manual Chemistry V1 and Reef Health Score V1.
4. Add Maintenance Tasks V1 and reagent/media tracking.
5. Add Apex/Trident import helper.
6. Add Lighting V1 through HA light entities.
7. Add Dosing V1 as advisory/logging/reminders before automation.
8. Add Water Change V1, then AWC preview, then armed AWC.
9. Add read-only analytics/reports.
10. Add camera snapshots.
11. Add read-only AI Guardian.
12. Add advanced spawning/mode choreography.
13. Package ready-made unit path.
