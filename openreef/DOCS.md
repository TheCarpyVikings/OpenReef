# OpenReef Labs

OpenReef Labs is the optional experimental add-on for advanced OpenReef features that are not part of the stable HA-native core yet.

## Features

- Preserves the existing Next.js dashboard for future migration.
- Keeps experimental AI, camera, reports, spawning, water change, analytics, diagrams, tasks, and lights out of the stable controller path.
- Does not provide the core OpenReef MVP controller by default.

OpenReef Core now lives in the Home Assistant `openreef` custom integration and native sidebar panel. Use that for Mission Control, Live Stats, Controls, Energy, and Settings.

## Installation

1. Install the OpenReef custom integration through HACS from this repository.
2. In Home Assistant, go to Settings → Devices & services and add OpenReef.
3. Open OpenReef from the Home Assistant sidebar and complete setup.
4. Install this add-on only if you want to test experimental Labs features.

## Configuration

The core controller does not depend on this add-on. Labs features are disabled unless the add-on image is built with `NEXT_PUBLIC_OPENREEF_ENABLE_LABS=true`.

### Add-on Options

| Option | Description |
|--------|-------------|
| `log_level` | Add-on log level |

## How It Works

OpenReef now uses a HA-native hybrid architecture:

- The Home Assistant integration owns setup, mappings, services, diagnostics, repair notices, and the stable sidebar panel.
- The add-on is optional Labs space for advanced features that are migrated later.
- Equipment service calls are blocked unless the matching mapped control is armed in OpenReef Core.
