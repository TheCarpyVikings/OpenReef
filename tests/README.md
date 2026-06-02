# OpenReef tests

First, dependency-free tests for the riskiest non-UI code: **config migration /
normalisation**, which runs against a beta tester's existing config on every update.

## Run

No Home Assistant or pip install required:

```
python3 tests/test_config_migration.py
```

Or with pytest if you have it:

```
pytest tests/
```

## How it works

`custom_components/openreef/__init__.py` imports `homeassistant.*` and `voluptuous` at module
level, but `_normalise_core_config` (and its helpers) are pure dict logic, and the module uses
`from __future__ import annotations` so type hints are never evaluated. `_ha_stubs.py` registers
lenient stub modules in `sys.modules` so the package imports, then the tests exercise the **real**
normalisation function — no mocks of the logic under test.

## What's covered

- Defaults / empty / non-dict input → full, current-schema config.
- Old (pre-`dosing`/`manualTests`) configs migrate, gain new blocks, and **preserve user data**
  (tank name/profile, sensor mappings + enabled flags).
- Garbage/corrupted values are coerced without crashing (a corrupted block can't crash migration).
- Idempotency (normalise∘normalise == normalise).
- Legacy Labs configs route through the converter without crashing.
- Safety: nothing comes out of migration `armed`; entity search stays capped (`SEARCH_LIMIT`).

## Next (need HA test harness / mocks)

Entity-search result caps end-to-end and safe-toggle/arming validation touch `hass` and would
need Home Assistant's test fixtures (or targeted mocks) — a good follow-up once `homeassistant`
is available in the dev env.
