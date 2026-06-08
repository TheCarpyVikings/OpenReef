"""Trust Moat tests for OpenReef.

Covers the new local-first readiness layer: probe health, Trust Check, Reef Replay,
and alert acknowledgement. Run standalone with:

    python3 tests/test_trust_moat.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeEntry, FakeHass, FakeState, run  # noqa: E402


def _cfg(extra=None):
    base = {
        "sensors": {
            "temp": {
                "entity_id": "sensor.temp",
                "enabled": True,
                "alertsEnabled": True,
            }
        },
        "sensorHealth": {"enabled": True},
    }
    if extra:
        base.update(extra)
    return integration._normalise_core_config(base)


def test_sensor_health_flags_stale_and_flatline():
    old = datetime.now(timezone.utc) - timedelta(hours=13)
    hass = FakeHass()
    hass.states.set("sensor.temp", FakeState("26.0", last_changed=old))
    cfg = _cfg({"sensorHealth": {"enabled": True, "staleAfterMinutes": 60, "flatlineHours": 12}})

    titles = [item["title"] for item in integration._sensor_health_items(hass, cfg)]

    assert any("stale" in title for title in titles)
    assert any("flatlined" in title for title in titles)


def test_sensor_health_flags_sudden_jump():
    now = datetime.now(timezone.utc)
    hass = FakeHass(states={"sensor.temp": "27.4"})
    cfg = _cfg(
        {
            "sensorHealth": {
                "enabled": True,
                "jumpWindowMinutes": 30,
                "jumpPercent": 25,
                "lastValues": {
                    "temp": {
                        "value": 25.0,
                        "updatedAt": (now - timedelta(minutes=5)).isoformat(),
                    }
                },
            }
        }
    )

    result = integration._sensor_health_items(hass, cfg)

    assert any("jumped suddenly" in item["title"] for item in result)
    assert "temp" in cfg["sensorHealth"]["lastJumps"]


def test_trust_check_updates_status_and_items():
    hass = FakeHass(states={"sensor.temp": "26.0"})
    cfg = _cfg({"sensorHealth": {"enabled": False}})

    trust = integration._trust_check_summary(hass, cfg, update=True)

    assert trust["status"] == "warning"
    assert cfg["trustCheck"]["lastStatus"] == "warning"
    assert cfg["trustCheck"]["lastRun"]
    assert {item["key"] for item in trust["items"]} >= {"sensors", "notifications", "heartbeat"}


def test_trust_check_warns_when_armed_life_support_has_no_edge_failsafe():
    hass = FakeHass(states={"sensor.temp": "26.0", "switch.heater": "on"})
    cfg = _cfg(
        {
            "equipment": {
                "heater": {
                    "label": "Heater",
                    "type": "heater",
                    "switch_entity_id": "switch.heater",
                    "armed": True,
                }
            },
            "edgeFailsafes": {"enabled": False},
        }
    )

    trust = integration._trust_check_summary(hass, cfg, update=True)
    edge = next(item for item in trust["items"] if item["key"] == "edge_failsafes")

    assert edge["status"] == "warning"
    assert "not marked as reviewed" in edge["detail"]


def test_trust_check_accepts_reviewed_edge_failsafe_for_armed_heater():
    now = datetime.now(timezone.utc).isoformat()
    hass = FakeHass(states={"sensor.temp": "26.0", "switch.heater": "on"})
    cfg = _cfg(
        {
            "equipment": {
                "heater": {
                    "label": "Heater",
                    "type": "heater",
                    "switch_entity_id": "switch.heater",
                    "armed": True,
                }
            },
            "edgeFailsafes": {
                "enabled": True,
                "heater": True,
                "lastReviewed": now,
                "notes": "bench tested",
            },
        }
    )

    trust = integration._trust_check_summary(hass, cfg, update=True)
    edge = next(item for item in trust["items"] if item["key"] == "edge_failsafes")

    assert edge["status"] == "ok"


def test_reef_replay_groups_activity_near_alert():
    now = datetime.now(timezone.utc)
    cfg = _cfg(
        {
            "alerts": {
                "history": [
                    {
                        "timestamp": now.isoformat(),
                        "sensor_id": "temp",
                        "state": "critical",
                        "title": "Temperature outside range",
                        "message": "Too hot",
                    }
                ]
            },
            "activity": [
                {
                    "timestamp": (now + timedelta(minutes=3)).isoformat(),
                    "message": "Heater turned off",
                    "type": "control",
                }
            ],
        }
    )

    incidents = integration._reef_replay_incidents(cfg)

    assert incidents[0]["title"] == "Temperature outside range"
    assert incidents[0]["events"][0]["message"] == "Heater turned off"


def test_acknowledge_alert_records_ack_and_dismisses_notifications():
    cfg = _cfg(
        {
            "alerts": {"persistentNotifications": True},
            "alertEscalation": {"enabled": True, "criticalOnly": True},
        }
    )
    entry = FakeEntry(options={integration.CONF_SETTINGS: cfg})
    hass = FakeHass(states={"sensor.temp": "30.0"}, entries=[entry])

    saved = run(integration._async_acknowledge_alert(hass, entry, "temp"))

    assert "temp" in saved["alertEscalation"]["acknowledged"]
    dismissed = [
        call.data.get("notification_id")
        for call in hass.services.calls
        if call.domain == "persistent_notification" and call.service == "dismiss"
    ]
    assert "openreef_alert_temp" in dismissed
    assert "openreef_escalation_temp" in dismissed


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
