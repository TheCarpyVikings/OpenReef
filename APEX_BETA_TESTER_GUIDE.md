# OpenReef Apex Beta Tester Guide

This guide is for testers who already have Neptune Apex or Trident data visible as Home Assistant entities.

## Install

1. Follow the main beta install guide in `BETA_TESTER_INSTALL_GUIDE.md`.
2. Install OpenReef through HACS as a custom integration.
3. Restart Home Assistant.
4. Go to **Settings -> Devices & services -> Add integration -> OpenReef**.
5. Open **OpenReef** from the Home Assistant sidebar.

The optional OpenReef Labs add-on is not required for this beta.

## First Setup

1. In the setup wizard, choose **Apex / Trident beta** on the sensor step.
2. Map the entities you already have in Home Assistant:
   - Display tank temperature
   - Sump temperature
   - Salinity
   - Alkalinity
   - ORP
   - Calcium
   - pH
   - Magnesium
3. Use **Find matches** first. Paste the entity ID only if OpenReef cannot suggest the right entity.
4. Add equipment if you want controls. Every switch starts safe until mapped and armed.
5. Review the Safety step before finishing setup.

## Safety Defaults

- Equipment cannot be controlled until it has a mapped switch and is explicitly armed.
- Display wavemakers should not auto-restart without inspection. Fish can enter stopped wavemakers.
- ATO duty cycle is optional. Leave it off if the ATO should stay powered continuously.
- If ATO duty cycle is enabled, OpenReef turns the ATO on for the configured seconds and forces it off outside that window.
- Heater warnings depend on a mapped display tank temperature entity.

## What To Test

- Open and refresh OpenReef several times.
- Use the Apex / Trident beta preset and confirm only owned sensors are enabled.
- Confirm each mapped sensor appears in Live Stats.
- Open trends for pH, temperature, alkalinity, calcium, and magnesium.
- Add equipment, map switch entities, then arm only the devices you are comfortable testing.
- Try Feed or Maintenance mode and check the confirmation screen before applying.
- Confirm ATO duty cycle stays off unless deliberately enabled.
- Use **Settings -> System Check** to review the beta handoff checklist, then **Copy support summary** if something looks wrong.
- Use **Copy beta smoke test** in System Check for the full step-by-step test script.
- Use **Copy feedback template** in System Check when reporting results.

## Please Report

- Home Assistant version.
- OpenReef version.
- Which Apex/Trident entities mapped correctly.
- Which suggestions were wrong or missing.
- Whether mobile setup is usable.
- The copied support summary, including the beta handoff checklist.
- The completed feedback template.

Do not send API keys, passwords, or Home Assistant long-lived access tokens.
