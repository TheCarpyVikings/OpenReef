# OpenReef Straton Beta Test Guide

Date: 2026-06-07

This guide is deliberately short. The goal is to prove whether OpenReef can reach/read a real ATI Straton without making the tester fight another messy app.

## Plain Answer

OpenReef Straton does not yet fully replace ATI first-time setup.

Right now it is a safer planner, backup, local-save, and read-only evidence tool. It must not write schedules to the light until real hardware proves readback, save/apply, and rollback.

The key setup question is:

- If the tester can use a new/reset or stuck Straton through OpenReef before using ATI's app, that is useful setup-bypass evidence.
- If the tester must fully set up the Straton in ATI's app first, then OpenReef has not fixed the main setup pain yet.
- If OpenReef only reads a light that is already on the home LAN, that helps adapter mapping but does not prove first-time setup bypass.

## What Ragnar Can Test Without A Straton

Standalone prototype:

1. Open `http://127.0.0.1:5174/`.
2. Open `Connect`.
3. Check the first screen shows two paths: `New or reset Straton` and `Light already on your network`.
4. Click `Use AP address`.
5. Confirm the add-by-address form uses `192.168.100.1`.
6. Add the fixture locally.
7. Try templates, quick controls, schedule, spectrum, acclimation, export/import, and local save.
8. Open `Help`.
9. Only expand `Advanced beta tools` if you want tester messages, safety checks, returned notes, or ATI JSON mapping samples.

Main OpenReef controller:

1. Open Home Assistant.
2. Open OpenReef.
3. Go to `Lights`.
4. Confirm the normal view starts with fixtures, quick controls, schedule, templates, backup, and local receipt tools.
5. Expand `Advanced Straton tools` only for AP fallback, safe path scanning, tester-note intake, and adapter evidence.
6. Do not use `Controller GET` without a real fixture on the same network.

## What Must Be Pushed First

The Home Assistant/OpenReef integration only updates after the Straton files are committed, pushed, and the beta tester updates/reloads their OpenReef install.

Use [straton-push-checklist.md](straton-push-checklist.md) for the narrow commit list and pre-push checks.

## First Message To The Beta Tester

Send this after the controller changes are pushed:

```text
Please test the OpenReef Straton connection only. Do not change your live ATI lighting schedule yet.

Open:
Home Assistant -> OpenReef -> Lights

Important:
- Save local plan only saves an OpenReef receipt.
- OpenReef must not write schedules to the Straton yet.
- Hardware writes stay locked until readback, save/apply, and rollback are proven.

First tell me:
1. Is your light ReefTECH Wi-Fi Straton/Flex/Pro, or Straton X with Reef Pilot Bluetooth?
2. Is the light already on your home network, brand new/reset, or stuck in ATI setup?
```

## Beta Tester Steps For ReefTECH Wi-Fi Straton/Flex/Pro

Use this path for the Wi-Fi/AP generation.

1. Open `Home Assistant -> OpenReef -> Lights`.
2. Add or select the Straton fixture.
3. Set `Adapter` to `ReefTECH Wi-Fi`.
4. If the light is already on the home network, enter its LAN IP/host.
5. If the light is new/reset or stuck before ATI setup, expand `Advanced Straton tools` and click `Use AP fallback`.
6. Confirm the host is `192.168.100.1` for AP fallback.
7. Set `Connection path` and `Setup state` as honestly as possible.
8. Click `Scan safe paths`.
9. If OpenReef finds a JSON/read path, copy the Straton support note and send it back.
10. If OpenReef only reaches the root page but finds no JSON, copy the support note and send it back.
11. If OpenReef cannot reach `192.168.100.1`, the controller/AP network route is blocked. Send that result back before blaming the light.

Do not click anything that writes a schedule to the Straton.

## Beta Tester Steps For Straton X / Reef Pilot Bluetooth

Use this path for the newer Bluetooth/Reef Pilot generation.

1. Open `Home Assistant -> OpenReef -> Lights`.
2. Add/select the fixture.
3. Set `Adapter` to `Reef Pilot Bluetooth`.
4. Do not treat AP fallback or `192.168.100.1` as proof for this hardware generation.
5. Send notes about pairing/control, Reef Pilot app behavior, Live PAR/Energy, template/group behavior, and whether schedule saves are clearly confirmed.
6. Copy the Straton support note and send it back.

## What Counts As Useful Evidence

Strong setup-bypass evidence needs all of this:

1. ReefTECH Wi-Fi fixture.
2. New/reset or stuck setup state before ATI app setup.
3. AP fallback staged at `192.168.100.1`.
4. Home Assistant/OpenReef controller can reach that AP route.
5. A safe read-only path returns useful JSON.

Useful but weaker evidence:

- LAN read evidence from an already configured light.
- Root reachability without useful JSON.
- A returned support note showing a route blocker.
- Straton X/Reef Pilot Bluetooth observations.

Not enough evidence:

- A phone can see the Straton Wi-Fi, but the Home Assistant controller cannot reach it.
- OpenReef reads a light only after ATI's app completed setup.
- Synthetic example notes from the app.

## What Ragnar Should Check When The Note Comes Back

1. Open `Lights`.
2. Expand `Advanced Straton tools`.
3. Paste the returned support note into tester-note intake.
4. Click `Analyze note`.
5. Check whether OpenReef classifies it as strong pre-setup evidence, LAN-only read evidence, route blocker, Reef Pilot Bluetooth evidence, reachable-only evidence, or incomplete.
6. Keep hardware writes locked unless readback, save/apply, and rollback are proven on real hardware.

## Current Product Claim

OpenReef Straton is a researched, safer, beta-ready planner and read-only evidence workflow for ATI Straton lights.

It is designed to discover whether OpenReef can replace the painful ATI setup path, but it must not claim full onboarding or hardware-write replacement yet.
