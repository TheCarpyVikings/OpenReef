"""Authenticated delivery and short-lived access URLs for private captures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.http.const import KEY_HASS_USER

from .const import CAPTURES_STATIC_URL
from .media_paths import media_file_path

MEDIA_URL_TTL = timedelta(minutes=10)
MEDIA_URL_BATCH_LIMIT = 100


class OpenReefMediaView(HomeAssistantView):
    """Keep camera captures private, including when a client knows the filename."""

    url = CAPTURES_STATIC_URL + "/{filename:.*}"
    name = "api:openreef:captures"
    requires_auth = True

    def __init__(self, hass, root: Path) -> None:
        self.hass = hass
        self.root = root

    async def get(self, request: web.Request, filename: str) -> web.StreamResponse:
        # HA validates bearer/authSig and resolves its actual user before this
        # handler. A read-only account cannot use HA's generic sign_path API to
        # bypass the same admin boundary as the recording WebSocket commands.
        user = request.get(KEY_HASS_USER)
        if user is None or not user.is_admin:
            raise web.HTTPForbidden

        def resolve() -> Path:
            path = media_file_path(self.root, filename)
            if not path.is_file():
                raise FileNotFoundError
            return path

        try:
            path = await self.hass.async_add_executor_job(resolve)
        except (ValueError, OSError):
            raise web.HTTPNotFound from None
        return web.FileResponse(path, headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        })

    async def head(self, request: web.Request, filename: str) -> web.StreamResponse:
        """Apply the same authorization to metadata requests as to file delivery."""
        return await self.get(request, filename)


async def async_sign_capture_paths(hass, root: Path, paths: list[str], refresh_token_id: str) -> dict:
    """Sign existing managed files for this authenticated session, never persist URLs."""
    if not isinstance(paths, list) or len(paths) > MEDIA_URL_BATCH_LIMIT:
        raise ValueError("Request at most 100 media paths")
    if not refresh_token_id:
        raise ValueError("An authenticated session is required")

    def existing_paths() -> list[str]:
        valid = []
        for relative in paths:
            try:
                path = media_file_path(root, relative)
                if path.is_file():
                    valid.append(relative)
            except (ValueError, OSError):
                continue
        return valid

    existing = await hass.async_add_executor_job(existing_paths)
    urls = {
        relative: async_sign_path(
            hass, f"{CAPTURES_STATIC_URL}/{quote(relative, safe='/')}", MEDIA_URL_TTL,
            refresh_token_id=refresh_token_id,
        )
        for relative in existing
    }
    return {"urls": urls, "expiresAt": (datetime.now(timezone.utc) + MEDIA_URL_TTL).isoformat()}
