"""Config flow for OpenReef."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import CONF_SETTINGS, DEFAULT_CORE_CONFIG, DOMAIN, NAME


class OpenReefConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an OpenReef config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create the single OpenReef config entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            tank_name = user_input["tank_name"].strip() or NAME
            user_name = user_input.get("user_name", "").strip()
            settings = deepcopy(DEFAULT_CORE_CONFIG)
            settings["tank"]["name"] = tank_name
            settings["tank"]["owner"] = user_name

            return self.async_create_entry(
                title=tank_name,
                data={"tank_name": tank_name},
                options={CONF_SETTINGS: settings},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("tank_name", default=NAME): str,
                    vol.Optional("user_name", default=""): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OpenReefOptionsFlowHandler:
        """Return the options flow."""
        return OpenReefOptionsFlowHandler(config_entry)


class OpenReefOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle OpenReef options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit basic OpenReef profile options."""
        settings = deepcopy(
            self._config_entry.options.get(CONF_SETTINGS, DEFAULT_CORE_CONFIG)
        )
        tank = settings.setdefault("tank", {})

        if user_input is not None:
            tank["name"] = user_input["tank_name"].strip() or NAME
            tank["owner"] = user_input.get("user_name", "").strip()
            return self.async_create_entry(
                title="",
                data={**self._config_entry.options, CONF_SETTINGS: settings},
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "tank_name", default=tank.get("name", NAME)
                    ): str,
                    vol.Optional(
                        "user_name", default=tank.get("owner", "")
                    ): str,
                }
            ),
        )
