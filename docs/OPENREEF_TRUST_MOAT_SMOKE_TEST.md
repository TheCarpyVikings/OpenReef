# OpenReef Trust Moat Smoke Test

Use this after installing or updating OpenReef Core in a real Home Assistant instance. It checks the Trust Moat features without requiring dangerous automation.

## Setup

- Open Home Assistant with the OpenReef panel available in the sidebar.
- Use a test tank, simulator, or non-life-support entities where possible.
- Keep dosing advisory-only.
- Do not connect a real heater, ATO pump, or return pump to new edge-failsafe hardware until the relay polarity and boot state have been bench-tested.

## 1. Migration And Fresh Load

- Fresh install opens the OpenReef panel without setup crash.
- Existing install keeps previous tank name, sensors, equipment, cameras, alerts, maintenance, and dosing settings.
- Settings can be edited for at least 60 seconds without losing focus.
- Browser hard refresh reloads the same config.

## 2. Trust Check

- Go to Settings -> System Check.
- In Trust Check, select Refresh.
- Confirm the Trust Check panel reports mapped sensors, notification path, heartbeat, camera reachability, incident history, backup review, and edge failsafes.
- Leave backup review empty and confirm Trust Check reports it honestly as unknown.
- Add today's backup review date and confirm the backup item improves on refresh.

## 3. Notification Test And Acknowledgement

- In Settings -> Alerts, enable Home Assistant persistent notifications.
- In Settings -> System Check or Settings -> Alerts, select Test notification.
- Confirm a Home Assistant persistent notification appears.
- If a notify target is configured, confirm the phone push arrives.
- Force a safe test warning with a temporary fake sensor value or widened/narrowed threshold.
- Confirm the alert appears in OpenReef and Home Assistant.
- Select Ack on the alert.
- Confirm repeat/escalation stops until the alert resolves or changes state.

## 4. Watchdog Heartbeat

- In System Check -> Watchdog, keep Watchdog and Heartbeat enabled.
- Set the optional all-clear notify target if phone verification is needed.
- Call the `openreef.heartbeat` service.
- Confirm `watchdog.lastHeartbeat` updates after refreshing OpenReef.
- If notify target is set, confirm the all-clear push arrives.

## 5. Probe Health

- Enable Probe Health.
- Set a short stale/flatline window on a test sensor.
- Confirm Trust Check and Alerts report stale/flatline warnings.
- Restore normal settings before leaving the system unattended.

## 6. Reef Replay

- Trigger a safe test alert.
- Record a nearby activity item by applying a harmless mode or saving settings.
- Go to System Check -> Reef Replay.
- Confirm the incident timeline shows the alert and nearby activity.

## 7. Edge Failsafes

- Review [OPENREEF_EDGE_FAILSAFE_RECIPES.md](OPENREEF_EDGE_FAILSAFE_RECIPES.md).
- In System Check -> Edge Failsafes, leave reviewed off while heater/ATO/return-pump equipment is armed.
- Confirm Trust Check warns that on-device failsafes are not marked as reviewed.
- Mark only the recipe that has actually been bench-tested.
- Confirm Trust Check clears only for the marked recipe.

## 8. Restart

- Restart Home Assistant.
- Confirm OpenReef reloads.
- Confirm Trust Check still shows an honest status.
- Confirm heartbeat/notification settings survive.
- Confirm acknowledged alerts and alert history survive.

## Pass Criteria

- No secrets appear in browser-visible data, copied summaries, or diagnostics.
- No unarmed equipment can be controlled.
- Alerts can be muted and acknowledged.
- Notification test works.
- Trust Check reports unknowns honestly instead of pretending unverified hardware is safe.
- Reef Replay shows enough timeline context to explain a test incident.
- Edge failsafes are warnings/review gates until actual hardware is bench-tested.
