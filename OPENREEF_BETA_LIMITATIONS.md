# OpenReef Beta Limitations

OpenReef Core is in active beta. It is designed to be safe by default, but it should still be tested carefully before controlling life-support equipment.

## Current Scope

OpenReef Core currently focuses on:

- Mission Control
- Live Stats and targeted trends
- Safe manual Controls
- Energy totals and per-device energy mapping
- Settings
- Alerts
- Feed, Maintenance, custom modes, and schedules
- Equipment safety helpers, including ATO duty cycling and display-wavemaker restart warnings

## Not Yet Production-Ready

- Automated dosing
- Automated water changes
- Direct hardware control outside Home Assistant entities
- AI control or advice-driven automation
- Camera streaming
- Advanced analytics and reports
- Full Neptune Apex import automation

## Safety Notes

- OpenReef only controls mapped Home Assistant switch entities.
- Switch control stays locked until the device is armed in Settings.
- Mode actions require confirmation.
- Display wavemakers should be inspected before restart if they have been off.
- ATO duty cycling only applies when enabled. If it is off, OpenReef leaves the ATO available for normal continuous/manual power.

## Known Beta Trade-Offs

- Long trend ranges depend on Home Assistant recorder/statistics retention.
- Entity suggestions are capped and targeted, so unusual entity names may still need manual mapping.
- Settings are intentionally detailed because OpenReef is currently exposing safety controls early for beta testing.
- Labs/old dashboard features are preserved in the repository but are not the stable controller path.

## Before Giving To A Tester

- Confirm OpenReef opens and refreshes without Home Assistant disconnecting.
- Confirm setup can be completed on desktop and phone.
- Confirm Find matches does not crash Home Assistant.
- Confirm controls only work for mapped and armed equipment.
- Confirm the Settings -> System Check beta handoff checklist is clean enough for the tester's setup.
- Confirm copied support summaries do not contain tokens or secrets.
