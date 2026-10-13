"""Config, reauth, reconfigure and options flows."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.const import (
    CONF_COMPANY_ID,
    CONF_POLL_INTERVAL,
    CONF_USE_CALLBACKS,
    CONF_WEBHOOK_SECRET,
    CONFIG_VERSION,
    DOMAIN,
)
from custom_components.flologic.vendor.pyflologic import (
    FloLogicAuthError,
    FloLogicConnectionError,
)

from .conftest import API_KEY, SECRET, make_entry, setup_integration

CREDENTIALS = {CONF_API_KEY: "new-key", CONF_COMPANY_ID: 102}


@pytest.fixture
def flow_client() -> Generator[MagicMock]:
    """Patch the client the config flow builds to check credentials."""
    with patch(
        "custom_components.flologic.config_flow.FloLogicClient", autospec=True
    ) as client_class:
        client = client_class.return_value
        client.async_list_vids = AsyncMock(return_value=["414B91", "93DBB1"])
        yield client


@pytest.fixture
def no_setup() -> Generator[None]:
    """Keep a created entry from actually setting up."""
    with patch("custom_components.flologic.async_setup_entry", return_value=True):
        yield


class TestUserStep:
    async def test_creates_an_entry_per_company(
        self, hass: HomeAssistant, flow_client: MagicMock, no_setup: None
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CREDENTIALS, CONF_WEBHOOK_SECRET: "whsec"}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "FloLogic company 102"
        assert result["data"] == {
            CONF_API_KEY: "new-key",
            CONF_COMPANY_ID: 102,
            CONF_WEBHOOK_SECRET: "whsec",
        }
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        assert entry.unique_id == "102"
        assert entry.version == CONFIG_VERSION

    async def test_the_secret_is_optional(
        self, hass: HomeAssistant, flow_client: MagicMock, no_setup: None
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert CONF_WEBHOOK_SECRET not in result["data"]

    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (FloLogicAuthError("Invalid company ID."), "invalid_auth"),
            (FloLogicConnectionError("down"), "cannot_connect"),
        ],
    )
    async def test_errors_leave_the_form_usable(
        self,
        hass: HomeAssistant,
        flow_client: MagicMock,
        no_setup: None,
        error: Exception,
        reason: str,
    ):
        flow_client.async_list_vids.side_effect = error
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": reason}

        flow_client.async_list_vids.side_effect = None
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

    async def test_a_company_can_only_be_added_once(
        self, hass: HomeAssistant, flow_client: MagicMock, no_setup: None
    ):
        make_entry().add_to_hass(hass)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


class TestReauth:
    async def test_a_new_key_is_stored(
        self, hass: HomeAssistant, flow_client: MagicMock, no_setup: None
    ):
        entry = make_entry()
        entry.add_to_hass(hass)
        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "rotated"}
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_API_KEY] == "rotated"

    async def test_a_rejected_key_is_not_stored(
        self, hass: HomeAssistant, flow_client: MagicMock, no_setup: None
    ):
        entry = make_entry()
        entry.add_to_hass(hass)
        flow_client.async_list_vids.side_effect = FloLogicAuthError("Invalid API key.")
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "wrong"}
        )
        assert result["errors"] == {"base": "invalid_auth"}
        assert entry.data[CONF_API_KEY] == API_KEY


class TestReconfigure:
    async def test_only_the_secret_can_be_replaced(
        self, hass: HomeAssistant, flow_client: MagicMock, no_setup: None
    ):
        entry = make_entry()
        entry.add_to_hass(hass)
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_WEBHOOK_SECRET: "new-secret"}
        )
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_WEBHOOK_SECRET] == "new-secret"
        assert entry.data[CONF_API_KEY] == API_KEY
        flow_client.async_list_vids.assert_not_awaited()

    async def test_a_new_key_is_checked(
        self, hass: HomeAssistant, flow_client: MagicMock, no_setup: None
    ):
        entry = make_entry()
        entry.add_to_hass(hass)
        flow_client.async_list_vids.side_effect = FloLogicAuthError("Invalid API key.")
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "wrong"}
        )
        assert result["errors"] == {"base": "invalid_auth"}
        assert entry.data[CONF_API_KEY] == API_KEY
        assert entry.data[CONF_WEBHOOK_SECRET] == SECRET


class TestOptions:
    async def test_polling_alone(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 300, CONF_USE_CALLBACKS: False}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert config_entry.options == {
            CONF_POLL_INTERVAL: 300,
            CONF_USE_CALLBACKS: False,
        }

    async def test_callbacks_need_a_secret(
        self, hass: HomeAssistant, mock_client: MagicMock
    ):
        await async_process_ha_core_config(hass, {"external_url": "https://ha.example"})
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="102",
            version=CONFIG_VERSION,
            data={CONF_API_KEY: API_KEY, CONF_COMPANY_ID: 102},
        )
        await setup_integration(hass, entry)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 60, CONF_USE_CALLBACKS: True}
        )
        assert result["errors"] == {CONF_USE_CALLBACKS: "secret_required"}

    async def test_callbacks_need_a_reachable_url(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 60, CONF_USE_CALLBACKS: True}
        )
        assert result["errors"] == {CONF_USE_CALLBACKS: "no_url"}

    async def test_callbacks_with_an_external_url(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await async_process_ha_core_config(hass, {"external_url": "https://ha.example"})
        await setup_integration(hass, config_entry)
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 60, CONF_USE_CALLBACKS: True}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        mock_client.async_add_callback.assert_awaited_once()
