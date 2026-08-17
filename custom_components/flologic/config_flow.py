"""Config flow for FloLogic."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_DEVICE_CODE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TOKEN,
    CONF_POLL_INTERVAL,
    DOMAIN,
)
from .coordinator import FloLogicConfigEntry
from .vendor.pyflologic import (
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    DeviceIdentity,
    FloLogicAuthError,
    FloLogicClient,
    FloLogicError,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


class FloLogicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a FloLogic config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(entry: FloLogicConfigEntry) -> FloLogicOptionsFlow:
        """Return the options flow."""
        del entry
        return FloLogicOptionsFlow()

    async def _async_validate(
        self, email: str, password: str, device: DeviceIdentity
    ) -> tuple[str | None, dict[str, str]]:
        """Try the credentials, returning the account's user ID or an error."""
        client = FloLogicClient(
            email=email,
            password=password,
            device=device,
            session=async_get_clientsession(self.hass),
            auto_reconnect=False,
        )
        try:
            await client.async_connect()
        except FloLogicAuthError:
            return None, {"base": "invalid_auth"}
        except FloLogicError:
            return None, {"base": "cannot_connect"}
        else:
            user = client.user
            return (user.user_id if user else None), {}
        finally:
            await client.async_disconnect()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Generated once and stored: FloLogic registers a device per
            # code/token pair, so regenerating would add a phantom device to
            # the account on every reconfigure.
            device = DeviceIdentity.generate("Home Assistant")
            user_id, errors = await self._async_validate(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD], device
            )
            if user_id and not errors:
                # The entry is the account, not a valve. Keying on a valve
                # would make a second valve on the same account unaddable.
                await self.async_set_unique_id(user_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data={
                        **user_input,
                        CONF_DEVICE_NAME: device.name,
                        CONF_DEVICE_CODE: device.code,
                        CONF_DEVICE_TOKEN: device.token,
                    },
                )
            if not errors:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the credentials stopped working."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a new password for an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            device = DeviceIdentity(
                name=entry.data[CONF_DEVICE_NAME],
                code=entry.data[CONF_DEVICE_CODE],
                token=entry.data[CONF_DEVICE_TOKEN],
            )
            user_id, errors = await self._async_validate(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD], device
            )
            if user_id and not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            if not errors:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    )
                }
            ),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


class FloLogicOptionsFlow(OptionsFlow):
    """Handle FloLogic options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the polling interval."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            # The floor is the library's, and it is advice
                            # about the cloud rather than about Home
                            # Assistant: polling harder risks rate limiting
                            # and gains nothing while pushes are healthy.
                            min=MIN_POLL_INTERVAL,
                            max=3600,
                            step=30,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
