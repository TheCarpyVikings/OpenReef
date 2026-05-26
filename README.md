# OpenReef

OpenReef is a private-beta reef aquarium controller dashboard for Home Assistant OS.

This repository contains the native pair:

- `custom_components/openreef` — Home Assistant custom integration for setup, mappings, services, diagnostics, and WebSocket commands.
- `openreef` — Home Assistant add-on that hosts the Next.js dashboard through Ingress.
- `src` — OpenReef dashboard application.

## Private Beta Install

1. Install the OpenReef custom integration through HACS as a custom integration repository.
2. Restart Home Assistant.
3. Add OpenReef in Settings → Devices & services.
4. Add this repository to the Home Assistant add-on store.
5. Install and start the OpenReef add-on.
6. Open OpenReef from the sidebar and map your entities.

Controls are locked by default. Each equipment switch must be explicitly mapped and armed before OpenReef will send control service calls.

## Development

```bash
pnpm install
pnpm lint
pnpm exec tsc --noEmit
pnpm build
```

For local dashboard development outside the add-on, configure server-side Home Assistant access with environment variables:

```bash
HA_URL=http://homeassistant.local:8123
HA_TOKEN=...
```

Do not expose Home Assistant tokens to browser-side `NEXT_PUBLIC_*` variables.
