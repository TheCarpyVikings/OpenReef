"""Offline regressions for media confinement; real HA auth tests run separately."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import _ha_stubs

_ha_stubs.install()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))
import openreef as integration
from openreef.media_paths import capture_path, media_file_path, safe_media_id
from _fake_ha import FakeConnection, FakeEntry, FakeHass


def _fixture(directory, *, sessions=None, cameras=None):
    config = {"feedSessions": sessions or [], "cameras": cameras or {}}
    entry = FakeEntry({integration.CONF_SETTINGS: config})
    return FakeHass(entries=[entry], config_dir=str(directory)), entry


async def _save(hass, entry, config):
    entry.options[integration.CONF_SETTINGS] = config
    return config


def _reject(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Unsafe path was accepted")


def test_media_paths_reject_absolute_traversal_encoded_and_non_media_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "captures"
        for value in ("../outside.jpg", "/tmp/outside.jpg", "a/../b.jpg", "a\\b.jpg",
                      "a//b.jpg", "a/%2e%2e/b.jpg", "\x00.jpg", ".", ".."):
            _reject(lambda value=value: capture_path(root, value))
        for value in ("", "settings.json", "other/place/photo.jpg", "corals/photo.html"):
            _reject(lambda value=value: media_file_path(root, value))
        assert media_file_path(root, "timelapse/display_1/20261026_120000.jpg") == root / "timelapse/display_1/20261026_120000.jpg"
        assert safe_media_id("display-1.old")


def test_media_paths_reject_file_directory_and_root_symlinks():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "captures"
        outside = Path(tmp) / "outside"
        root.mkdir()
        outside.mkdir()
        (outside / "photo.jpg").write_bytes(b"outside")
        (root / "photo.jpg").symlink_to(outside / "photo.jpg")
        (root / "corals").symlink_to(outside, target_is_directory=True)
        alias = Path(tmp) / "alias"
        alias.symlink_to(root, target_is_directory=True)
        _reject(lambda: media_file_path(root, "photo.jpg"))
        _reject(lambda: media_file_path(root, "corals/photo.jpg"))
        _reject(lambda: media_file_path(alias, "photo.jpg"))


def test_camera_normalization_preserves_safe_existing_ids_and_drops_paths():
    config = integration._normalise_core_config({"cameras": {
        "display_tank": {"entity_id": "camera.display"},
        "old.camera-1": {"entity_id": "camera.old"},
        "../../outside": {"entity_id": "camera.bad"},
        "/tmp/outside": {"entity_id": "camera.bad"},
    }})
    assert set(config["cameras"]) == {"display_tank", "old.camera-1"}


def test_delete_feed_session_rejects_unknown_ids_and_absolute_paths():
    with tempfile.TemporaryDirectory() as tmp:
        outside = Path(tmp) / "outside"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_text("synthetic")
        hass, _ = _fixture(tmp)
        for session_id in (str(outside), "../../outside", "unknown_session"):
            connection = FakeConnection()
            asyncio.run(integration.websocket_delete_feed_session(
                hass, connection, {"id": 1, "session_id": session_id}))
            assert connection.error_codes == ["invalid_session"]
            assert marker.read_text() == "synthetic"


def test_delete_known_feed_session_does_not_follow_symlinks():
    with tempfile.TemporaryDirectory() as tmp:
        hass, entry = _fixture(tmp, sessions=[{"id": "known_session"}])
        frame_dir = integration._feeds_dir(hass, "known_session")
        frame_dir.mkdir(parents=True)
        (frame_dir / "000_120000.jpg").write_bytes(b"frame")
        outside = Path(tmp) / "outside.jpg"
        outside.write_bytes(b"keep")
        (frame_dir / "linked.jpg").symlink_to(outside)
        with patch.object(integration, "_async_save_config", _save):
            connection = FakeConnection()
            asyncio.run(integration.websocket_delete_feed_session(
                hass, connection, {"id": 1, "session_id": "known_session"}))
        assert not connection.errors
        assert outside.read_bytes() == b"keep"
        assert not (frame_dir / "000_120000.jpg").exists()
        assert entry.options[integration.CONF_SETTINGS]["feedSessions"] == []


def test_known_feed_session_symlink_directory_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        hass, _ = _fixture(tmp, sessions=[{"id": "known_session"}])
        outside = Path(tmp) / "outside"
        outside.mkdir()
        marker = outside / "photo.jpg"
        marker.write_bytes(b"keep")
        directory = integration._feeds_dir(hass, "known_session")
        directory.parent.mkdir(parents=True)
        directory.symlink_to(outside, target_is_directory=True)
        for handler in (integration.websocket_delete_feed_session, integration.websocket_list_feed_frames):
            connection = FakeConnection()
            asyncio.run(handler(hass, connection, {"id": 1, "session_id": "known_session"}))
            assert connection.error_codes == ["invalid_session"]
            assert marker.read_bytes() == b"keep"


def test_clear_timelapse_requires_known_camera_and_keeps_unrelated_files():
    with tempfile.TemporaryDirectory() as tmp:
        hass, _ = _fixture(tmp, cameras={"display": {"entity_id": "camera.display"}})
        directory = integration._timelapse_dir(hass, "display")
        directory.mkdir(parents=True)
        jpg = directory / "20261026_120000.jpg"
        jpg.write_bytes(b"frame")
        keep = directory / "keep.txt"
        keep.write_text("keep")
        for camera_id in (str(directory), "../../outside", "unknown"):
            connection = FakeConnection()
            asyncio.run(integration.websocket_clear_timelapse(hass, connection, {"id": 1, "camera_id": camera_id}))
            assert connection.error_codes == ["invalid_camera"]
            assert jpg.exists()
        connection = FakeConnection()
        asyncio.run(integration.websocket_clear_timelapse(hass, connection, {"id": 1, "camera_id": "display"}))
        assert not connection.errors
        assert not jpg.exists()
        assert keep.read_text() == "keep"


def test_capture_retention_ignores_outside_names_and_symlink_files():
    with tempfile.TemporaryDirectory() as tmp:
        hass, _ = _fixture(tmp)
        root = integration._captures_dir(hass)
        root.mkdir()
        outside = Path(tmp) / "outside.jpg"
        outside.write_bytes(b"keep")
        (root / "linked.jpg").symlink_to(outside)
        real = root / "manual_20261026_120000_abcdef.jpg"
        real.write_bytes(b"delete")
        asyncio.run(integration._async_delete_capture_files(hass, [
            {"thumbnail": str(outside)}, {"thumbnail": "../outside.jpg"},
            {"thumbnail": "linked.jpg"}, {"thumbnail": real.name},
        ]))
        assert outside.read_bytes() == b"keep"
        assert not real.exists()


def test_explicit_unknown_camera_does_not_capture_another_camera():
    hass, _ = _fixture("/tmp/unused-openreef-security", cameras={"display": {"entity_id": "camera.display"}})
    hass.states.set("camera.display", "idle")
    config = {"cameras": {"display": {"entity_id": "camera.display"}}}
    assert integration._resolve_capture_camera(hass, config, {}, override="unknown") is None
    assert integration._resolve_capture_camera(hass, config, {}, override="../display") is None


if __name__ == "__main__":
    tests = [(name, value) for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"{len(tests)}/{len(tests)} passed")
