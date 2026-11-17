# Firmware: per-device API and OTA encryption

The ESPHome reference configurations in `docs/manual/*-reference.yaml` and
`esphome/openreef_edge_failsafes.example.yaml` target **ESPHome 2026.10.0 or newer**.
They use API encryption and `ota: platform: esphome` with `encryption:`, keyed from a
`!secret` entry.

**Do this with the tank in a safe state:** pump outputs isolated, a working copy of the
current config kept, and a physical (USB) recovery route available.

## Keys

Generate a separate, random API key for **each device** and store it locally in your
ESPHome `secrets.yaml` under the name the reference file uses. Never reuse one key across
devices, and never commit real keys.

## Migrating an existing device

- **Already on encrypted OTA:** confirm the existing key and the host ESPHome version
  match, review the full configuration, then follow your usual maintenance update.
- **Older firmware with password/plain OTA only:** encrypted OTA will not fall back to
  plaintext. Either follow ESPHome's staged migration (enable the API key first, then
  require encrypted OTA where supported), or install the new configuration over USB.
  Don't strip encryption from the final config just to make an upload succeed.

## Before compiling or flashing

- Validate the actual file with `esphome config`.
- Check GPIO assignments, master relay polarity, float and leak sensors, pump calibration,
  current limits and interlocks against your real hardware. The reference files are a
  starting point, not proof of a safe installation.
- The edge example doesn't restart the ATO maximum-runtime timer, and it refuses to run
  the heater when the temperature reading is non-finite or the leak state is unknown.
  After any firmware update, confirm these fail-safes physically under controlled
  conditions.

References: [ESPHome API](https://esphome.io/components/api/) ·
[ESPHome encrypted OTA and migration](https://esphome.io/components/ota/esphome/)
