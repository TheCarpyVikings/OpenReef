# OpenReef

OpenReef is the open **intelligence layer for reefing** — a private-beta, Home Assistant-native reef controller that runs on any HA hardware (including your existing Apex, Trident, HYDROS, ESPHome, probes, and smart plugs) and adds the trust, prediction, and vision the hardware vendors can't ship.

The stable controller now lives in the Home Assistant custom integration:

- `custom_components/openreef` — Home Assistant custom integration, native sidebar panel, setup wizard, mappings, services, diagnostics, and repair notices.
- `src` — preserved Next.js dashboard application code for future migration work.

The optional OpenReef Labs add-on has moved to a separate private repository so normal users cannot discover it from the main OpenReef install path.

## Start Here

If you are new to OpenReef or Home Assistant, start with
[OPENREEF_DIY_MANUAL.md](OPENREEF_DIY_MANUAL.md). It walks through choosing a
Home Assistant install route, installing OpenReef through HACS, mapping sensors
safely, and running the first Trust Check.

## Private Beta Install

1. Install the OpenReef custom integration through HACS as a custom integration repository.
2. Restart Home Assistant.
3. Add OpenReef in Settings → Devices & services.
4. Open OpenReef from the Home Assistant sidebar.
5. Complete the native setup wizard and map your reef entities.

Controls are locked by default. Each equipment switch must be explicitly mapped and armed before OpenReef will send control service calls.

For tester handoff, use [BETA_TESTER_INSTALL_GUIDE.md](BETA_TESTER_INSTALL_GUIDE.md), [APEX_BETA_TESTER_GUIDE.md](APEX_BETA_TESTER_GUIDE.md), [OPENREEF_BETA_SMOKE_TEST.md](OPENREEF_BETA_SMOKE_TEST.md), and [OPENREEF_BETA_FEEDBACK_TEMPLATE.md](OPENREEF_BETA_FEEDBACK_TEMPLATE.md).

Product direction is tracked in [OPENREEF_PRODUCT_ROADMAP.md](OPENREEF_PRODUCT_ROADMAP.md), with Apex comparison and Labs migration detail in [OPENREEF_COMPETITIVE_AUDIT.md](OPENREEF_COMPETITIVE_AUDIT.md).

The add-on is no longer required for the MVP controller. OpenReef Labs is intentionally separate and private while experimental advanced screens are being rebuilt.

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
