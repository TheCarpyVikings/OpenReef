# OpenReef Beta Tester Install Guide

This guide is for private beta testers installing OpenReef through Home Assistant Community Store.

If you are starting from no Home Assistant install at all, use `OPENREEF_DIY_MANUAL.md` first, then come back to this shorter beta handoff guide.

## Before You Start

- Use Home Assistant OS or a Home Assistant install that supports HACS custom integrations.
- Make sure the reef sensors and smart plugs you want to test are already visible in Home Assistant.
- Do not paste Home Assistant tokens, API keys, or passwords into OpenReef.
- Only arm equipment you are comfortable letting OpenReef control.

## Install Or Update OpenReef

1. Open Home Assistant.
2. Go to **HACS**.
3. Add the OpenReef repository as a custom integration if it is not already installed.
4. Download or update OpenReef.
5. Restart Home Assistant.
6. Go to **Settings -> Devices & services -> Add integration**.
7. Search for **OpenReef** and add it.
8. Open **OpenReef** from the Home Assistant sidebar.

If OpenReef does not appear in the sidebar, refresh the browser after Home Assistant has fully restarted.

## First Setup

1. Click **Setup**.
2. Confirm your tank name, optional owner name, and tank type.
3. Choose the closest sensor preset:
   - **Temperature only** for the safest basic setup.
   - **Everything available** if you want to enable all sensor categories, then turn off anything you do not own.
   - **No Apex / OpenReef sensors** for normal Home Assistant reef sensors such as temperature, pH, and salinity.
   - **Apex controller**, **Apex + Trident**, **Apex + Trident NP**, **Apex + FMM**, or **Apex full ecosystem** if those Neptune entities are already visible in Home Assistant.
4. Enable only the sensors you actually own.
5. Use **Find matches** for each enabled sensor.
6. Choose the best suggestion, or paste the entity ID if no suggestion is correct.
7. Add equipment only if you want OpenReef to control it during beta testing.
8. Map each equipment switch.
9. Arm only the equipment you are comfortable testing.
10. Review safety settings before finishing.
11. Run Trust Check in **Settings -> System Check** before leaving the install unattended.

## Safety Rules

- Unarmed equipment stays locked in the Controls screen.
- Mode actions show a preview before changing equipment.
- Display wavemakers need special care because fish can enter stopped wavemakers.
- If ATO duty cycle is enabled, OpenReef powers the ATO for the chosen number of seconds, then turns it off until the next interval.
- Leave ATO duty cycle off if your ATO should stay powered continuously.

## Smoke Test

After setup, open **Settings -> System Check** and press:

1. **Refresh checks**
2. **Copy beta smoke test**
3. **Copy support summary**

Run the copied smoke test on desktop and phone if possible.

## Report Feedback

Open **Settings -> System Check** and press **Copy feedback template**.

Send back:

- The completed feedback template.
- The copied support summary.
- Screenshots of anything confusing or broken.

Do not send API keys, passwords, Home Assistant long-lived access tokens, or private network credentials.
