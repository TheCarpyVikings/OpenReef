"""Real Home Assistant authorization tests, isolated from the lightweight stubs.

Run in a venv with homeassistant==2026.10.4:
    python tests/ha_runtime/security_checks.py

No HTTP listener, real config, credentials or devices are used. Requests pass
through HA's actual auth middleware and view wrapper with synthetic accounts.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from homeassistant.components.http.auth import async_setup_auth, async_sign_path
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized, UnknownUser
from homeassistant.helpers.http import KEY_HASS, request_handler_factory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "custom_components"))
import openreef as integration
from openreef import diagnostics
from openreef.media import OpenReefMediaView, async_sign_capture_paths


class SecurityChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="openreef-ha-auth-test-")
        self.hass = HomeAssistant(self.temp.name)
        self.root = Path(self.temp.name) / integration.CAPTURES_DIR_NAME
        (self.root / "corals").mkdir(parents=True)
        self.relative = "corals/test_20261026T120000.jpg"
        (self.root / self.relative).write_bytes(b"synthetic photo")
        self.users = {
            name: SimpleNamespace(id=name, is_admin=(name == "admin"), is_active=True,
                                  local_only=False, refresh_tokens={})
            for name in ("admin", "user", "read_only", "content")
        }
        self.tokens = {}
        for name, user in self.users.items():
            token = SimpleNamespace(id=f"{name}-refresh", user=user)
            user.refresh_tokens[token.id] = token
            self.tokens[token.id] = token
        self.hass.auth = SimpleNamespace(
            async_get_user=AsyncMock(side_effect=lambda name: self.users.get(name)),
            async_get_refresh_token=lambda token_id: self.tokens.get(token_id),
            async_validate_access_token=lambda token: self.tokens.get(token),
        )
        self.app = web.Application()
        self.app[KEY_HASS] = self.hass
        with patch("homeassistant.components.http.auth.Store.async_load", AsyncMock(return_value={"content_user": "content"})):
            await async_setup_auth(self.hass, self.app)
        self.view = OpenReefMediaView(self.hass, self.root)
        self.handler = request_handler_factory(self.hass, self.view, self.view.get)

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        self.temp.cleanup()

    async def request(self, url=None, *, user=None, filename=None):
        url = url or f"{integration.CAPTURES_STATIC_URL}/{self.relative}"
        filename = filename if filename is not None else url.split("?", 1)[0].removeprefix(integration.CAPTURES_STATIC_URL + "/")
        request = make_mocked_request(
            "GET", url,
            headers={"Authorization": f"Bearer {user}-refresh"} if user else {},
            app=self.app, match_info={"filename": filename},
        )
        # Run the actual HA middleware, including JWT expiry/path/user checking.
        return await self.app.middlewares[0](request, self.handler)

    async def test_anonymous_capture_request_is_denied(self):
        with self.assertRaises(web.HTTPUnauthorized):
            await self.request()

    async def test_capture_setup_registers_private_view_and_no_static_route(self):
        self.hass.http = SimpleNamespace(register_view=Mock(), async_register_static_paths=AsyncMock())
        await integration._async_register_captures_path(self.hass)
        await integration._async_register_captures_path(self.hass)
        self.hass.http.register_view.assert_called_once()
        self.assertIsInstance(self.hass.http.register_view.call_args.args[0], OpenReefMediaView)
        self.hass.http.async_register_static_paths.assert_not_awaited()

    async def test_admin_bearer_allowed_and_non_admin_denied(self):
        response = await self.request(user="admin")
        self.assertIsInstance(response, web.FileResponse)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        for user in ("user", "read_only"):
            with self.subTest(user=user), self.assertRaises(web.HTTPForbidden):
                await self.request(user=user)

    async def test_signed_url_works_and_is_bound_to_path_expiry_and_session(self):
        payload = await async_sign_capture_paths(self.hass, self.root, [self.relative], "admin-refresh")
        url = payload["urls"][self.relative]
        self.assertIn("authSig=", url)
        self.assertIsInstance(await self.request(url), web.FileResponse)
        with self.assertRaises(web.HTTPUnauthorized):
            await self.request(url.replace("test_", "other_", 1))
        expired = async_sign_path(self.hass, f"{integration.CAPTURES_STATIC_URL}/{self.relative}",
                                  timedelta(seconds=-1), refresh_token_id="admin-refresh")
        with self.assertRaises(web.HTTPUnauthorized):
            await self.request(expired)
        del self.tokens["admin-refresh"]
        with self.assertRaises(web.HTTPUnauthorized):
            await self.request(url)

    async def test_generic_ha_signature_does_not_grant_non_admin_access(self):
        url = async_sign_path(self.hass, f"{integration.CAPTURES_STATIC_URL}/{self.relative}",
                              timedelta(minutes=1), refresh_token_id="read_only-refresh")
        with self.assertRaises(web.HTTPForbidden):
            await self.request(url)

    async def test_media_path_and_symlink_denied_even_to_admin(self):
        outside = Path(self.temp.name) / "outside.jpg"
        outside.write_bytes(b"private synthetic marker")
        (self.root / "corals" / "linked.jpg").symlink_to(outside)
        for relative in ("../outside.jpg", "corals/linked.jpg", "corals/missing.jpg", "settings.json"):
            with self.subTest(relative=relative), self.assertRaises(web.HTTPNotFound):
                await self.request(user="admin", filename=relative)
        result = await async_sign_capture_paths(self.hass, self.root,
            [self.relative, "../outside.jpg", "corals/linked.jpg", "corals/missing.jpg", "settings.json"],
            "admin-refresh")
        self.assertEqual(set(result["urls"]), {self.relative})
        with self.assertRaises(ValueError):
            await async_sign_capture_paths(self.hass, self.root, [self.relative] * 101, "admin-refresh")

    async def test_signing_websocket_uses_real_admin_decorator(self):
        for user in ("user", "read_only"):
            connection = SimpleNamespace(user=self.users[user], refresh_token_id=f"{user}-refresh")
            with self.subTest(user=user), self.assertRaises(Unauthorized):
                integration.websocket_sign_capture_urls(self.hass, connection, {"id": 1, "paths": [self.relative]})

    async def test_every_registered_service_denies_non_admin_and_unknown_users(self):
        # Registration and authorization are real HA. Replace only each action's
        # body so an allowed action cannot start hardware or background work.
        services = (
            (integration.SERVICE_APPLY_MODE, "_handle_apply_mode", {"mode_id": "running"}),
            (integration.SERVICE_RECORD_MANUAL_READING, "_handle_record_manual_reading", {"parameter": "ph", "value": 8.1}),
            (integration.SERVICE_RECORD_TASK_COMPLETION, "_handle_record_task_completion", {"task_id": "test"}),
            (integration.SERVICE_ARM_EQUIPMENT, "_handle_arm_equipment_service", {"equipment_id": "pump"}),
            (integration.SERVICE_DISARM_EQUIPMENT, "_handle_disarm_equipment_service", {"equipment_id": "pump"}),
            (integration.SERVICE_ACKNOWLEDGE_ALERT, "_handle_acknowledge_alert", {"sensor_id": "ph"}),
            (integration.SERVICE_TEST_NOTIFICATION, "_handle_test_notification", {}),
            (integration.SERVICE_REFRESH_TRUST_CHECK, "_handle_refresh_trust_check", {}),
            (integration.SERVICE_HEARTBEAT, "_handle_heartbeat", {}),
        )
        for service, name, data in services:
            body = AsyncMock()
            with patch.object(integration, name, body):
                await integration.async_setup(self.hass, {})
            for user in ("user", "read_only", "missing"):
                with self.subTest(service=service, user=user), self.assertRaises((Unauthorized, UnknownUser)):
                    await self.hass.services.async_call(integration.DOMAIN, service, data,
                        blocking=True, context=Context(user_id=user))
                body.assert_not_awaited()
            for user in ("admin", None):
                await self.hass.services.async_call(integration.DOMAIN, service, data,
                    blocking=True, context=Context(user_id=user))
            self.assertEqual(body.await_count, 2)
            self.assertIs(body.await_args.args[0], self.hass)

    async def test_diagnostics_redacts_nested_beta_tokens_without_losing_settings(self):
        entry = SimpleNamespace(data={}, options={
            integration.CONF_SETTINGS: {"tank": {"name": "Synthetic reef"}},
            integration.beta_feedback.OPT_KEY: {"token": "SYNTHETIC-NOT-A-REAL-TOKEN", "enabled": True},
        })
        result = await diagnostics.async_get_config_entry_diagnostics(self.hass, entry)
        self.assertNotIn("SYNTHETIC-NOT-A-REAL-TOKEN", repr(result))
        self.assertEqual(result["options"][integration.CONF_SETTINGS]["tank"]["name"], "Synthetic reef")


if __name__ == "__main__":
    unittest.main(verbosity=2)
