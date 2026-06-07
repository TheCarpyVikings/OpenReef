# OpenReef Straton Push Checklist

Date: 2026-06-07

Use this when preparing the Straton work for a beta-tester update. The repo currently has unrelated dirty files, so keep the Straton push narrow.

## Stage Only These Straton Files

- `README.md`
- `custom_components/openreef/const.py`
- `custom_components/openreef/__init__.py`
- `custom_components/openreef/diagnostics.py`
- `custom_components/openreef/frontend/openreef-panel.js`
- `docs/straton-controller-integration.md`
- `docs/straton-beta-test-guide.md`
- `docs/straton-push-checklist.md`
- `scripts/check_straton_beta.sh`

Do not include unrelated roadmap, dosing, landing, public SVG, virtualenv, crop, cache, or generated files in the Straton commit.

## Pre-Push Checks

Run these from `/home/reece/Workspaces/Ragnars_Reef`:

```bash
./scripts/check_straton_beta.sh
```

The checker runs:

- Expected Straton file and checklist drift checks.
- JavaScript syntax passes.
- Python compile passes.
- TypeScript passes.
- ESLint passes without errors or warnings.
- Trailing whitespace and conflict-marker scans pass for the Straton files.
- Staged-file guard passes, or reports that no files are staged yet.

## Exact Narrow Commit Flow

Run these from `/home/reece/Workspaces/Ragnars_Reef` when you are ready to update the beta tester:

```bash
git status --short
```

You should expect unrelated dirty files in this repo. Do not stage them.

```bash
git diff -- README.md custom_components/openreef/const.py custom_components/openreef/__init__.py custom_components/openreef/diagnostics.py custom_components/openreef/frontend/openreef-panel.js docs/straton-controller-integration.md docs/straton-beta-test-guide.md docs/straton-push-checklist.md scripts/check_straton_beta.sh
```

If the diff only shows Straton work, stage the narrow set:

```bash
git add README.md custom_components/openreef/const.py custom_components/openreef/__init__.py custom_components/openreef/diagnostics.py custom_components/openreef/frontend/openreef-panel.js docs/straton-controller-integration.md docs/straton-beta-test-guide.md docs/straton-push-checklist.md scripts/check_straton_beta.sh
```

Confirm the staged files before committing:

```bash
git diff --cached --name-only
```

The staged list should be exactly:

```text
README.md
custom_components/openreef/__init__.py
custom_components/openreef/const.py
custom_components/openreef/diagnostics.py
custom_components/openreef/frontend/openreef-panel.js
docs/straton-beta-test-guide.md
docs/straton-controller-integration.md
docs/straton-push-checklist.md
scripts/check_straton_beta.sh
```

Check the staged diff itself before committing:

```bash
git diff --cached --check
git diff --cached --stat
```

Then commit and push:

```bash
git commit -m "Add Straton light beta workflow"
git push
```

After the push, ask the beta tester to update/reload OpenReef, then open the Home Assistant OpenReef panel and check for the `Lights` tab. The same after-push message is also available from `Lights` -> `Copy beta update`.

If `git diff --cached --name-only` includes unrelated files, unstage only those files before committing:

```bash
git restore --staged path/to/unrelated-file
```

## Copy/Paste Beta Tester Message

Send this only after the Straton files are pushed and the tester has a way to update/reload OpenReef. You can copy it from the `Lights` tab with `Copy beta update`, or use the text below.

```text
OpenReef Straton beta update

I have pushed a new read-only Straton light test into OpenReef. Please update/reload your OpenReef install first, then open:

Home Assistant -> OpenReef -> Lights

Important safety boundary:
- Please do not apply an OpenReef schedule to the Straton yet.
- Save local plan only creates an OpenReef receipt.
- Hardware writes are still locked until readback, save/apply, and rollback evidence are proven.

First thing to tell me:
1. Is your light ReefTECH Wi-Fi Straton/Flex/Pro, or Straton X with Reef Pilot Bluetooth?
2. Is the light already on your LAN, brand new/reset, or stuck in ATI setup?

If it is ReefTECH Wi-Fi:
1. Add/select the fixture in the Lights tab.
2. Set the adapter to ReefTECH Wi-Fi.
3. Set Connection path and Setup state.
4. Expand Advanced Straton tools.
5. If testing first-time/stuck setup, click Use AP fallback.
6. Click Scan safe paths.
7. Copy the Straton support note back to me.

If it is Straton X / Reef Pilot Bluetooth:
1. Set the adapter to Reef Pilot Bluetooth.
2. Do not treat AP route as proof for this hardware.
3. Send pairing/control notes, Live PAR/Energy observations, template/group behaviour, and whether schedule saves are clearly confirmed.

What I need back:
- The copied Straton support note.
- Whether OpenReef found a JSON/read path, reached only the root page, or could not reach the light.
- Any redacted screenshots or notes that do not include passwords, tokens, Wi-Fi credentials, account details, or public IPs.

The goal of this test is only to prove whether OpenReef can reach/read the light or collect Bluetooth evidence before guessing any hardware adapter.
```

## What The Beta Tester Should See After Update

In the Home Assistant OpenReef panel:

1. A native `Lights` tab.
2. A normal Straton planner view with fixture targets, quick controls, schedule preview, templates, backup, and local receipt tools.
3. `Copy support note` and `Save local plan` actions.
4. `Save local plan` saving only an OpenReef receipt, not writing to ATI hardware.
5. `Advanced Straton tools` containing setup rescue, `Use AP fallback`, `Scan safe paths`, tester-note intake, safety checks, and adapter evidence tools.

## First Tester Task

Ask the tester to run a read-only connection test only:

1. Add or select the Straton fixture.
2. Set `Adapter` to ReefTECH Wi-Fi or Reef Pilot Bluetooth for the tester's hardware generation.
3. Set `Connection path` and `Setup state`.
4. Expand `Advanced Straton tools`.
5. If testing first-time or stuck setup on ReefTECH Wi-Fi, click `Use AP fallback`.
6. Click `Scan safe paths` for ReefTECH Wi-Fi evidence.
7. Check `AP route` for ReefTECH Wi-Fi, or collect Reef Pilot Bluetooth pairing/control evidence for Straton X.
8. Copy and return the Straton support note.

Do not ask them to apply an OpenReef schedule to the light yet.

## Evidence That Would Move The Project Forward

- Hardware generation is recorded: ReefTECH Wi-Fi Straton/Flex/Pro, or Straton X with Reef Pilot Bluetooth.
- For ReefTECH Wi-Fi, AP fallback route is reachable from the Home Assistant controller.
- For Reef Pilot Bluetooth, Bluetooth pairing/control evidence is captured instead of treating AP route as proof.
- Brand-new/reset or stuck setup state is recorded.
- At least one safe read-only path returns JSON.
- The returned support note includes bypass verdict, AP route, safe scan counts, best path, schema fingerprint, hardware generation or Bluetooth evidence where relevant, and next action.
- The returned support note or tester message says whether OpenReef found a JSON/read path, reached only the root page, or could not reach the light.
- Repeated reads of the same path/firmware produce matching schema fingerprints.
- Later, one-change-at-a-time ATI export or network notes identify ReefTECH Wi-Fi load, save, and apply paths.
- Later, Reef Pilot Bluetooth app-control observations identify pairing, Live PAR/Energy, template/group, and schedule-save behavior.

## Must Stay Locked

- First-time ATI onboarding replacement is not proven until AP route, setup state, and JSON read evidence are all present.
- LAN read evidence is useful, but it is not proof that OpenReef bypassed ATI setup.
- Hardware writes stay locked until current-state readback, current-program readback, firmware/group context, save/apply endpoint evidence, and rollback evidence are all verified on real Straton hardware.
