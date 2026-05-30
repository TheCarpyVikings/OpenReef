# OpenReef Beta Smoke Test

Use this before giving OpenReef to a beta tester and ask the tester to run the same checks after setup.

## Before Testing

1. Update OpenReef in HACS.
2. Restart Home Assistant.
3. Open OpenReef from the Home Assistant sidebar.
4. Open **Settings -> System Check**.
5. Press **Refresh checks**.

## Desktop Stability

- Open OpenReef from the sidebar.
- Hard refresh the browser.
- Leave OpenReef and return to it.
- Confirm Home Assistant does not show **Connection lost / Reconnecting**.
- Confirm **Find matches** does not restart or disconnect Home Assistant.

## Setup And Mapping

- Open **Setup** and step through the wizard.
- For Apex or Trident testers, choose **Apex / Trident beta** on the sensor step.
- Enable only the sensors the tester actually owns.
- Use **Find matches** for at least two sensors.
- Add equipment only if the tester wants real switch control.
- Review the Safety step before finishing.

## Live Stats And Trends

- Confirm mapped readings appear in **Live Stats**.
- Open trends for temperature and pH if available.
- Test 1 hour, 24 hours, 7 days, and 30 days.
- Long trend ranges depend on Home Assistant recorder/statistics history.

## Controls And Modes

- Keep equipment disarmed unless it is safe to control.
- Confirm disarmed equipment cannot be switched on/off from Controls.
- Arm one safe device and test the switch.
- Open Feed and Maintenance mode confirmation dialogs.
- Apply a mode only when the preview matches what should happen.
- Return to Running and confirm equipment is restored or intentionally left unchanged.

## Safety Checks

- Confirm ATO duty cycle is off unless the tester wants timed ATO power windows.
- If ATO duty cycle is on, confirm the on duration and interval are correct.
- If display wavemakers are mapped, confirm the tester understands the restart warning.
- Confirm wavemaker reminders are enabled if display wavemakers can be turned off.

## Mobile Checks

- Open OpenReef on a phone.
- Check Mission Control, Live Stats, Controls, Energy, Settings, and System Check.
- Open Setup and confirm the wizard scrolls normally.
- Open a trend modal and confirm the range buttons are usable.
- Confirm buttons are tappable and text remains readable.

## Report Back

Ask the tester to send:

- Home Assistant version.
- OpenReef version.
- Which entities mapped correctly.
- Which suggestions were wrong or missing.
- Any mobile layout issues.
- Any Home Assistant disconnects/restarts.
- **Settings -> System Check -> Copy feedback template** output.
- **Settings -> System Check -> Copy support summary** output.

Do not ask testers to send API keys, passwords, or Home Assistant long-lived access tokens.
