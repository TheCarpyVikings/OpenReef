# Changelog

## 0.1.11

- Bust Docker's cached Git clone layer whenever the add-on version changes, preventing Home Assistant from running stale frontend code after an update.
- Default the beta add-on to manual start so Home Assistant will not relaunch it automatically while testers are proving stability.

## 0.1.10

- Disable automatic Home Assistant entity polling on dashboard load.
- Require a manual click on the HA status badge before OpenReef requests HA entities.
- Keep page-close/request abort behavior so refreshing or leaving OpenReef cannot leave browser-triggered HA requests running.

## 0.1.9

- Reduce Home Assistant load from the dashboard by replacing 5-second entity polling with 60-second visible-only polling.
- Abort in-flight entity requests when the OpenReef page is closed or refreshed.
- Cache entity snapshots server-side so multiple tabs/devices do not repeatedly hit Home Assistant Core.
- Make the HA status badge manually retryable and keep errors readable.

## 0.1.8

- Use the documented Home Assistant app REST and WebSocket proxy URLs.
- Add a startup preflight log for Supervisor token/API proxy availability.
- Keep the last HA connection error visible instead of flickering back to a generic connecting state.
- Fix the dashboard logo URL under `/app/..._openreef` and migrate legacy default branding names.

## 0.1.7

- Keep browser API calls inside OpenReef when Home Assistant serves the app at `/app/..._openreef`.

## 0.1.6

- Handle unstripped `/api/hassio_ingress/...` and `/app/..._openreef` prefixes in the nginx ingress proxy.

## 0.1.5

- Use Home Assistant's `X-Ingress-Path` header when rewriting Next.js asset and API URLs.
- Remove the explicit root `ingress_entry` so the Apps UI uses the Supervisor-managed ingress session URL.
- Teach browser API calls to stay under `/api/hassio_ingress/...` when Home Assistant serves the app there.

## 0.1.4

- Remove a noisy nginx MIME warning from the Ingress proxy log.

## 0.1.3

- Fix blank Home Assistant Ingress screen by preserving the OpenReef ingress prefix for Next.js assets and app API calls.
- Add a trailing-slash redirect for the OpenReef ingress root so relative assets resolve correctly.
- Update the browser metadata title/description to OpenReef.

## 0.1.2

- Improve Home Assistant Ingress routing for the new Apps UI.
- Remove brittle Supervisor IP allow-list from the internal nginx proxy.
- Send nginx access/error logs to the app log for easier first-install debugging.

## 0.1.1

- Fix Home Assistant Apps/Supervisor local build context.
- Add required Home Assistant app Docker labels.

## 0.1.0

- Private-beta OpenReef add-on package.
- Next.js standalone runtime behind Home Assistant Ingress.
- Server-side Home Assistant gateway using the Supervisor token.
- Explicit control arming support through the OpenReef integration settings.
