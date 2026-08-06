"""Capture targeting + gating unit tests.

The capture engine itself does file I/O + pulls camera image bytes (awkward to
fake), but its *decisions* are pure and worth guarding: which camera gets
captured (`_resolve_capture_camera` — first online, respects override/selection),
and whether a capture even fires (`_dispatch_capture` — only when enabled AND the
event's trigger toggle is on). HA stubbed (`_ha_stubs`) + faked (`_fake_ha`).

Run standalone:  python3 tests/test_capture.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

sys.path.insert(0, _HERE)
import _ha_stubs  # noqa: E402

_ha_stubs.install()

sys.path.insert(0, os.path.join(_ROOT, "custom_components"))
import openreef as integration  # noqa: E402

from _fake_ha import FakeEntry, FakeHass  # noqa: E402

CONF_SETTINGS = integration.CONF_SETTINGS
resolve = integration._resolve_capture_camera
dispatch = integration._dispatch_capture
mark_camera_io_started = integration._mark_camera_io_started
mark_camera_io_finished = integration._mark_camera_io_finished


# --- _resolve_capture_camera: pick the first ONLINE mapped camera -----------

def _cams(cameras):
    return {"cameras": cameras}


def test_resolve_returns_none_when_no_cameras():
    assert resolve(FakeHass(states={}), _cams({}), {}) is None


def test_resolve_picks_the_online_camera():
    hass = FakeHass(states={"camera.x": "idle"})
    assert resolve(hass, _cams({"c": {"entity_id": "camera.x", "label": "Display"}}), {}) == (
        "c", "camera.x", "Display",
    )


def test_resolve_skips_offline_and_takes_next():
    hass = FakeHass(states={"camera.a": "unavailable", "camera.b": "idle"})
    cams = {"a": {"entity_id": "camera.a", "label": "A"}, "b": {"entity_id": "camera.b", "label": "B"}}
    assert resolve(hass, _cams(cams), {})[1] == "camera.b"


def test_resolve_returns_none_when_all_offline():
    hass = FakeHass(states={"camera.a": "unavailable"})
    assert resolve(hass, _cams({"a": {"entity_id": "camera.a", "label": "A"}}), {}) is None


def test_resolve_skips_unmapped_camera():
    hass = FakeHass(states={"camera.b": "idle"})
    cams = {"a": {"entity_id": "", "label": "A"}, "b": {"entity_id": "camera.b", "label": "B"}}
    assert resolve(hass, _cams(cams), {})[0] == "b"


def test_resolve_respects_override():
    hass = FakeHass(states={"camera.a": "idle", "camera.b": "idle"})
    cams = {"a": {"entity_id": "camera.a", "label": "A"}, "b": {"entity_id": "camera.b", "label": "B"}}
    assert resolve(hass, _cams(cams), {}, override="b")[0] == "b"


# --- _dispatch_capture: fire only when enabled AND the trigger is on --------

def _capture_entry(enabled, triggers=None):
    cfg = {
        "cameras": {"c": {"entity_id": "camera.x", "label": "X"}},
        "capture": {"enabled": enabled, "triggers": triggers or {}},
    }
    return FakeEntry(options={CONF_SETTINGS: cfg})


def test_dispatch_skipped_when_capture_disabled():
    entry = _capture_entry(False, {"criticalAlerts": True})
    hass = FakeHass(entries=[entry])
    dispatch(hass, entry, "critical_alert", "Temp critical")
    assert hass.tasks == []


def test_dispatch_skipped_when_trigger_toggle_off():
    entry = _capture_entry(True, {"criticalAlerts": False})
    hass = FakeHass(entries=[entry])
    dispatch(hass, entry, "critical_alert", "Temp critical")
    assert hass.tasks == []


def test_dispatch_fires_when_enabled_and_trigger_on():
    entry = _capture_entry(True, {"criticalAlerts": True})
    hass = FakeHass(entries=[entry])
    dispatch(hass, entry, "critical_alert", "Temp critical")
    assert len(hass.tasks) == 1


# --- shared camera I/O guard -----------------------------------------------

def test_camera_io_guard_blocks_overlap_and_releases():
    hass = FakeHass()
    assert mark_camera_io_started(hass, "camera.x") is True
    assert mark_camera_io_started(hass, "camera.x") is False
    mark_camera_io_finished(hass, "camera.x")
    assert mark_camera_io_started(hass, "camera.x") is True
    mark_camera_io_finished(hass, "camera.x")


# --- coral photo upload (Reef Layer) ----------------------------------------
# The upload handler shares the captures store. Its guards are the point:
# unknown corals, non-base64, and non-JPEG/PNG payloads must all bounce, and a
# good upload must write the file AND pin the URL onto the persisted coral.

def test_coral_photo_upload_saves_and_pins_url():
    import base64 as _b64
    import tempfile
    from _fake_ha import FakeConnection, run

    cfg = integration._normalise_core_config(
        {"livestock": {"corals": {"torchy": {"name": "Torchy", "species": "torch"}}}}
    )
    tmp = tempfile.mkdtemp(prefix="openreef_coral_")
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry], config_dir=tmp)

    async def _noop_register(_hass):
        return None

    original = integration._async_register_captures_path
    integration._async_register_captures_path = _noop_register
    try:
        jpeg = b"\xff\xd8\xff\xe0" + b"reefbytes" * 8
        image = "data:image/jpeg;base64," + _b64.b64encode(jpeg).decode()
        conn = FakeConnection()
        run(integration.websocket_coral_photo_upload(
            hass, conn, {"id": 1, "type": "openreef/coral_photo_upload", "coralId": "torchy", "image": image}
        ))
        assert not conn.errors, conn.errors
        url = conn.results[0].payload["url"]
        assert url.startswith(f"{integration.CAPTURES_STATIC_URL}/corals/torchy.jpg?v=")
        saved = os.path.join(tmp, integration.CAPTURES_DIR_NAME, "corals", "torchy.jpg")
        with open(saved, "rb") as fh:
            assert fh.read() == jpeg
        persisted = conn.results[0].payload["config"]["livestock"]["corals"]["torchy"]["photoUrl"]
        assert persisted == url, "URL must survive the normaliser round-trip"
    finally:
        integration._async_register_captures_path = original


def test_coral_photo_upload_rejects_junk():
    import base64 as _b64
    import tempfile
    from _fake_ha import FakeConnection, run

    cfg = integration._normalise_core_config(
        {"livestock": {"corals": {"torchy": {"species": "torch"}}}}
    )
    entry = FakeEntry(options={CONF_SETTINGS: cfg})
    hass = FakeHass(entries=[entry], config_dir=tempfile.mkdtemp(prefix="openreef_coral_"))

    async def _noop_register(_hass):
        return None

    original = integration._async_register_captures_path
    integration._async_register_captures_path = _noop_register
    try:
        gif = "data:image/gif;base64," + _b64.b64encode(b"GIF89a....").decode()
        cases = [
            ({"coralId": "ghost", "image": "data:image/jpeg;base64,AAAA"}, "unknown_coral"),
            ({"coralId": "torchy", "image": "data:image/jpeg;base64,@@not-base64@@"}, "bad_image"),
            ({"coralId": "torchy", "image": gif}, "bad_image"),
        ]
        for extra, code in cases:
            conn = FakeConnection()
            run(integration.websocket_coral_photo_upload(
                hass, conn, {"id": 1, "type": "openreef/coral_photo_upload", **extra}
            ))
            assert conn.error_codes == [code], f"{extra} -> {conn.error_codes}"
            assert not conn.results
    finally:
        integration._async_register_captures_path = original


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
