"""Config flow: first setup, duplicates, reauth, and options."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pyflologic import FloLogicAuthError, FloLogicConnectionError, User
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.const import (
    CONF_DEVICE_CODE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TOKEN,
    CONF_POLL_INTERVAL,
    DOMAIN,
)

from .conftest import setup_integration

CREDENTIALS = {CONF_EMAIL: "owner@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture
def flow_client() -> Generator[MagicMock]:
    """Patch the client the config flow builds to validate credentials."""
    with patch(
        "custom_components.flologic.config_flow.FloLogicClient", autospec=True
    ) as client_class:
        client = client_class.return_value
        client.async_connect = AsyncMock()
        client.async_disconnect = AsyncMock()
        client.user = User({"id": "4297", "email": "owner@example.com"})
        yield client


async def start_user_flow(hass: HomeAssistant) -> dict:
    """Open the user step."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


class TestUserFlow:
    """Adding an account."""

    async def test_success_creates_one_entry_for_the_account(
        self, hass: HomeAssistant, flow_client: MagicMock
    ) -> None:
        result = await start_user_flow(hass)
        assert result["type"] is FlowResultType.FORM

        with patch("custom_components.flologic.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], CREDENTIALS
            )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "owner@example.com"
        # The account's user ID, not a valve's: keying on a valve is what
        # makes a second valve on the same account unaddable.
        assert result["result"].unique_id == "4297"

    async def test_a_device_identity_is_generated_and_stored(
        self, hass: HomeAssistant, flow_client: MagicMock
    ) -> None:
        """FloLogic registers a device per code/token pair, so it must persist."""
        result = await start_user_flow(hass)
        with patch("custom_components.flologic.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], CREDENTIALS
            )

        data = result["data"]
        assert data[CONF_DEVICE_NAME] == "Home Assistant"
        assert data[CONF_DEVICE_CODE].startswith("AND-")
        assert data[CONF_DEVICE_TOKEN]

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (FloLogicAuthError("bad"), "invalid_auth"),
            (FloLogicConnectionError("down"), "cannot_connect"),
        ],
    )
    async def test_failures_are_reported_and_recoverable(
        self,
        hass: HomeAssistant,
        flow_client: MagicMock,
        error: Exception,
        expected: str,
    ) -> None:
        flow_client.async_connect.side_effect = error
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": expected}

        # The form must still be usable after a failure.
        flow_client.async_connect.side_effect = None
        with patch("custom_components.flologic.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], CREDENTIALS
            )
        assert result["type"] is FlowResultType.CREATE_ENTRY

    async def test_the_same_account_cannot_be_added_twice(
        self,
        hass: HomeAssistant,
        flow_client: MagicMock,
        config_entry: MockConfigEntry,
    ) -> None:
        config_entry.add_to_hass(hass)
        result = await start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_the_validation_session_is_always_closed(
        self, hass: HomeAssistant, flow_client: MagicMock
    ) -> None:
        """Including on the failure path, or a rejected login leaks a socket."""
        flow_client.async_connect.side_effect = FloLogicAuthError("bad")
        result = await start_user_flow(hass)
        await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
        flow_client.async_disconnect.assert_awaited()


class TestReauth:
    """Recovering from a changed password."""

    async def test_a_new_password_is_accepted(
        self,
        hass: HomeAssistant,
        flow_client: MagicMock,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        await setup_integration(hass, config_entry)
        result = await config_entry.start_reauth_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-secret"}
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert config_entry.data[CONF_PASSWORD] == "new-secret"

    async def test_a_still_wrong_password_is_rejected(
        self,
        hass: HomeAssistant,
        flow_client: MagicMock,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        await setup_integration(hass, config_entry)
        flow_client.async_connect.side_effect = FloLogicAuthError("still bad")
        result = await config_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}
        assert config_entry.data[CONF_PASSWORD] == "pw-MUST-NOT-LEAK"

    async def test_reauth_reuses_the_stored_device_identity(
        self,
        hass: HomeAssistant,
        flow_client: MagicMock,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        """A fresh identity here would register a phantom device each time."""
        await setup_integration(hass, config_entry)
        result = await config_entry.start_reauth_flow(hass)
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-secret"}
        )
        device = flow_client.async_connect.call_args
        assert device is not None
        assert config_entry.data[CONF_DEVICE_CODE] == "AND-test"


class TestOptions:
    """The polling interval."""

    async def test_the_interval_can_be_changed(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        await setup_integration(hass, config_entry)
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 600}
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert config_entry.options[CONF_POLL_INTERVAL] == 600
