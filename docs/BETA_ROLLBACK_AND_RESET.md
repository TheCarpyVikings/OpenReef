# OpenReef beta — rollback & reset

OpenReef is moving fast during beta. This is the safety net: how to undo an update,
reset the configuration, and recover if something goes wrong. **OpenReef never controls
equipment unless you map and arm it, so a bad update cannot switch your gear — but it's
still worth being able to roll back.**

## Before every beta update: take a Home Assistant backup (30 seconds)

This is the single best safety net — it reverts **both** the integration files **and** your
OpenReef config in one step.

1. **Settings → System → Backups → Create backup** (a partial backup is fine; include
   "Home Assistant configuration" / add-ons as you like).
2. Then update OpenReef in HACS and restart.

If an update misbehaves, **Settings → System → Backups → (your backup) → Restore** puts you
back exactly where you were.

## Roll back to a previous version

- **Easiest:** restore the backup you took before updating (above).
- **Via HACS:** HACS → OpenReef → the three-dot menu → **Redownload**, and pick an earlier
  version if one is offered, then **restart Home Assistant** and hard-refresh the panel.
  *(Note: this repo currently tracks its default branch, so HACS may only offer the latest.
  Tagging GitHub releases would let HACS list older versions to pick from — worth doing once
  beta widens.)*
- **Manual fallback:** replace `config/custom_components/openreef/` with an older copy of the
  folder (from a backup or a specific git commit), then restart.

After any rollback: **restart Home Assistant**, then hard-refresh the OpenReef panel in the
browser so the cached frontend reloads.

## Reset the OpenReef configuration (start clean)

A clean slate — removes all OpenReef sensor/equipment mappings and settings. Your actual
Home Assistant entities (Apex/Trident sensors, smart plugs, etc.) are **not** touched.

1. **Settings → Devices & Services → OpenReef → ⋮ → Delete** (removes the single config entry).
2. **Add Integration → OpenReef** to set it up fresh, or just re-open the panel and run Setup
   again.

Config and personality prefs that live in the browser (tone, reef-buddy on/off, "tour done"
flag, Apex/controller answer) are stored in that browser's local storage — clear the site's
local storage, or just toggle them back in Settings → Guide & buddy / Profile.

## If an update won't load at all

1. Restore your pre-update backup (fastest).
2. If you can't: delete `config/custom_components/openreef/`, reinstall from HACS, restart.
3. Grab diagnostics for a bug report: **Settings → Devices & Services → OpenReef → ⋮ →
   Download diagnostics** (secrets are redacted) and share it.

## For maintainers: the migration safety check

Config migration is what runs against an existing tester's config on every update — the thing
most likely to break silently. It's covered by tests that need no Home Assistant install:

```
python3 tests/test_config_migration.py
```

Run it before shipping a release that touches `const.py` (`DEFAULT_CORE_CONFIG`,
`CORE_SCHEMA_VERSION`) or `__init__.py` config normalisation.
