"""Setup, failure handling, migration, and device removal."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic import async_remove_config_entry_device
from custom_components.flologic.const import CONF_POLL_INTERVAL, DOMAIN
from custom_components.flologic.vendor.pyflologic import (
    FloLogicAuthError,
    FloLogicConnectionError,
)

from .conftest import VID, make_entry, make_valve, set_valves, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_a_rejected_key_starts_reauthentication(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.async_refresh.side_effect = FloLogicAuthError("Invalid API key.")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_an_unreachable_api_retries_setup(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.async_refresh.side_effect = FloLogicConnectionError("down")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_the_poll_interval_comes_from_options(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    entry = make_entry({CONF_POLL_INTERVAL: 120})
    await setup_integration(hass, entry)
    assert entry.runtime_data.update_interval.total_seconds() == 120


async def test_the_default_poll_interval_is_the_librarys(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.runtime_data.update_interval.total_seconds() == 60


async def test_an_entry_from_the_unofficial_integration_is_refused(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """It holds an email and password; the issue says what to do instead."""
    old = MockConfigEntry(
        domain=DOMAIN,
        title="owner@example.com",
        unique_id="4297",
        version=1,
        data={"email": "owner@example.com", "password": "pw"},
    )
    old.add_to_hass(hass)
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert old.state is ConfigEntryState.MIGRATION_ERROR
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"unofficial_entry_{old.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders == {"title": "owner@example.com"}
    mock_client.async_refresh.assert_not_awaited()


async def test_removing_an_unofficial_entry_touches_nothing(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    old = MockConfigEntry(
        domain=DOMAIN, version=1, data={"email": "e", "password": "p"}
    )
    old.add_to_hass(hass)
    await hass.config_entries.async_remove(old.entry_id)
    mock_client.async_remove_callbacks.assert_not_awaited()


async def test_a_present_valves_device_cannot_be_deleted(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, VID)})
    assert device is not None
    assert not await async_remove_config_entry_device(hass, config_entry, device)


async def test_a_departed_valves_device_can_be_deleted(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, VID)})
    assert device is not None
    set_valves(mock_client, make_valve("93DBB1"))
    await config_entry.runtime_data.async_refresh()
    assert await async_remove_config_entry_device(hass, config_entry, device)
