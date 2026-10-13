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
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .callbacks import can_receive_callbacks
from .const import (
    CONF_COMPANY_ID,
    CONF_POLL_INTERVAL,
    CONF_USE_CALLBACKS,
    CONF_WEBHOOK_SECRET,
    CONFIG_VERSION,
    DOMAIN,
)
from .coordinator import FloLogicConfigEntry
from .vendor.pyflologic import (
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    ApiKeyAuth,
    FloLogicAuthError,
    FloLogicClient,
    FloLogicError,
)

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): PASSWORD,
        vol.Required(CONF_COMPANY_ID): NumberSelector(
            NumberSelectorConfig(min=1, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_WEBHOOK_SECRET): PASSWORD,
    }
)


class FloLogicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a FloLogic config flow."""

    VERSION = CONFIG_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(entry: FloLogicConfigEntry) -> FloLogicOptionsFlow:
        """Return the options flow."""
        del entry
        return FloLogicOptionsFlow()

    async def _async_validate(
        self, api_key: str, company_id: int
    ) -> tuple[int | None, dict[str, str]]:
        """Try the credentials, returning how many valves they see or an error."""
        client = FloLogicClient(
            ApiKeyAuth(api_key, company_id),
            session=async_get_clientsession(self.hass),
        )
        try:
            vids = await client.async_list_vids()
        except FloLogicAuthError:
            return None, {"base": "invalid_auth"}
        except FloLogicError:
            return None, {"base": "cannot_connect"}
        return len(vids), {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and check the API credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            company_id = int(user_input[CONF_COMPANY_ID])
            # The company is the account: one entry per company, however many
            # valves and houses it covers.
            await self.async_set_unique_id(str(company_id))
            self._abort_if_unique_id_configured()
            _, errors = await self._async_validate(user_input[CONF_API_KEY], company_id)
            if not errors:
                data = {
                    CONF_API_KEY: user_input[CONF_API_KEY],
                    CONF_COMPANY_ID: company_id,
                }
                if user_input.get(CONF_WEBHOOK_SECRET):
                    data[CONF_WEBHOOK_SECRET] = user_input[CONF_WEBHOOK_SECRET]
                return self.async_create_entry(
                    title=f"FloLogic company {company_id}", data=data
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the API key stopped working."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a new API key for an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            _, errors = await self._async_validate(
                user_input[CONF_API_KEY], int(entry.data[CONF_COMPANY_ID])
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): PASSWORD}),
            description_placeholders={"company_id": str(entry.data[CONF_COMPANY_ID])},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the API key or the signing secret.

        Fields left empty keep their current value, since a password field
        cannot show what is stored.
        """
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            updates: dict[str, Any] = {}
            if user_input.get(CONF_API_KEY):
                _, errors = await self._async_validate(
                    user_input[CONF_API_KEY], int(entry.data[CONF_COMPANY_ID])
                )
                updates[CONF_API_KEY] = user_input[CONF_API_KEY]
            if user_input.get(CONF_WEBHOOK_SECRET):
                updates[CONF_WEBHOOK_SECRET] = user_input[CONF_WEBHOOK_SECRET]
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=updates)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_KEY): PASSWORD,
                    vol.Optional(CONF_WEBHOOK_SECRET): PASSWORD,
                }
            ),
            description_placeholders={"company_id": str(entry.data[CONF_COMPANY_ID])},
            errors=errors,
        )


class FloLogicOptionsFlow(OptionsFlow):
    """Handle FloLogic options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage polling and callbacks."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_USE_CALLBACKS):
                if not self.config_entry.data.get(CONF_WEBHOOK_SECRET):
                    errors[CONF_USE_CALLBACKS] = "secret_required"
                elif not can_receive_callbacks(self.hass):
                    errors[CONF_USE_CALLBACKS] = "no_url"
            if not errors:
                return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            # The floor is the library's advice about the
                            # cloud: FloLogic documents no rate limit, so
                            # this errs well short of finding one.
                            min=MIN_POLL_INTERVAL,
                            max=3600,
                            step=30,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_USE_CALLBACKS,
                        default=options.get(CONF_USE_CALLBACKS, False),
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )
