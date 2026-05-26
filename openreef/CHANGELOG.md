# Changelog

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
