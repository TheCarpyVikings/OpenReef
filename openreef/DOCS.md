# OpenReef

OpenReef is a private-beta reef aquarium controller dashboard for Home Assistant OS.

## Features

- **Interactive System Diagram** — Real-time visualization of your reef system with live sensor data
- **Explicitly Armed Equipment Control** — Controls are locked until each mapped entity is deliberately armed
- **Parameter History** — View historical trends for temperature, pH, salinity, and other water parameters
- **Energy Monitoring** — Track power consumption across all equipment

AI, Google integrations, advanced camera workflows, spawning, and automatic water change control are deferred for the core private beta.

## Installation

1. Install the OpenReef custom integration through HACS from this repository.
2. In Home Assistant, go to Settings → Devices & services and add OpenReef.
3. Add this repository to Settings → Add-ons → Add-on Store → Repositories.
4. Install and start the OpenReef add-on.
5. Open OpenReef from the Home Assistant sidebar and map your entities.

## Configuration

The add-on talks to Home Assistant through the Supervisor API proxy. No long-lived access token is entered into the browser.

### Add-on Options

| Option | Description |
|--------|-------------|
| `log_level` | Add-on log level |

## How It Works

OpenReef uses a native pair:

- The Home Assistant integration owns setup, mappings, services, diagnostics, and repair notices.
- The add-on hosts the dashboard through Home Assistant Ingress.
- The browser talks only to the OpenReef add-on; HA credentials stay server-side.
- Equipment service calls are blocked unless the matching mapped control is armed.
