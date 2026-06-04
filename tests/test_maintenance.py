"""Maintenance Tasks — the record_task_completion service handler.

The due/overdue logic + UI are frontend; the one backend runtime path is the HA
service that logs a completion (so a physical button/automation can mark a task
done). Tested through the real handler with HA stubbed (`_ha_stubs`) + faked
(`_fake_ha`). (Config seeding/normalisation is covered in test_config_migration.)

Run standalone:  python3 tests/test_maintenance.py
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeEntry, FakeHass, run  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
record = integration._handle_record_task_completion


def _entry():
    cfg = {
        "maintenance": {
            "seeded": True,
            "tasks": {"water_change": {"label": "Water change", "cadenceDays": 7, "enabled": True}},
            "completions": {},
        }
    }
    return FakeEntry(options={CONF_SETTINGS: cfg})


def _call(data):
    return SimpleNamespace(data=data)


def _saved(entry):
    return entry.options[CONF_SETTINGS]["maintenance"]


def test_record_completion_appends_with_notes():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change", "notes": "60L WC, corals happy"})))
    completions = _saved(entry)["completions"]["water_change"]
    assert len(completions) == 1
    assert completions[0]["notes"] == "60L WC, corals happy"
    assert completions[0]["timestamp"]  # stamped


def test_record_completion_logs_activity():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    run(record(hass, _call({"task_id": "water_change"})))
    activity = entry.options[CONF_SETTINGS].get("activity", [])
    assert any("Water change" in item.get("message", "") for item in activity)


def test_record_completion_unknown_task_raises():
    entry = _entry()
    hass = FakeHass(entries=[entry])
    raised = False
    try:
        run(record(hass, _call({"task_id": "does_not_exist"})))
    except Exception:  # noqa: BLE001 - ServiceValidationError (stubbed as Exception)
        raised = True
    assert raised, "an unknown task_id must be rejected"
    assert _saved(entry)["completions"] == {}  # nothing logged


def test_record_completion_not_configured_raises():
    raised = False
    try:
        run(record(FakeHass(entries=[]), _call({"task_id": "water_change"})))
    except Exception:  # noqa: BLE001 - HomeAssistantError (stubbed)
        raised = True
    assert raised


# --- tiny standalone runner -------------------------------------------------

def _main() -> int:
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed", "" if not failed else f"— FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
