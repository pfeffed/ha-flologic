"""Setup, unload, and multi-valve behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pyflologic import FloLogicAuthError, FloLogicConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.const import DOMAIN

from .conftest import make_account, make_valve, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """The entry loads, then unloads and closes its session."""
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.async_disconnect.assert_awaited()


async def test_every_valve_becomes_a_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Three valves on one account produce three devices, not one.

    This is the failure that motivated the whole project: an integration that
    picks a single valve per entry leaves the rest of a multi-valve account
    unreachable.
    """
    account = make_account(
        make_valve("2245", "Riverside Whole House"),
        make_valve("4613", "Riverside Main House", mode=2),
        make_valve("106193", "34 Sample Road"),
    )
    mock_client.account = account
    mock_client.valves = dict(account.valves)

    await setup_integration(hass, config_entry)

    devices = dr.async_get(hass).devices.get_devices_for_config_entry_id(
        config_entry.entry_id
    )
    assert len(devices) == 3
    assert {device.name for device in devices} == {
        "Riverside Whole House",
        "Riverside Main House",
        "34 Sample Road",
    }


async def test_gateways_do_not_become_devices(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Non-valve devices share the array but have nothing to open or close."""
    account = make_account(
        make_valve("106193", "34 Sample Road"),
        make_valve("gw-1", "Gateway", isZGateway=True),
        make_valve("sensor-1", "Leak sensor", isSensor=True),
    )
    mock_client.account = account
    mock_client.valves = dict(account.valves)

    await setup_integration(hass, config_entry)

    devices = dr.async_get(hass).devices.get_devices_for_config_entry_id(
        config_entry.entry_id
    )
    assert {device.name for device in devices} == {"34 Sample Road"}


async def test_device_identity_survives_a_rename(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Entity IDs key on hardware UUID, not the account-scoped name.

    The same valve is named differently to its owner than to a shared user, so
    anything derived from the name would change identity with the account.
    """
    await setup_integration(hass, config_entry)
    registry = er.async_get(hass)
    before = {
        entry.unique_id
        for entry in registry.entities.values()
        if entry.config_entry_id == config_entry.entry_id
    }
    assert before
    assert all(unique_id.startswith("hw-106193") for unique_id in before)


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Rejected credentials ask the user to re-authenticate."""
    mock_client.async_connect.side_effect = FloLogicAuthError("nope")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_connection_failure_retries(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """An outage is retried rather than treated as a configuration error."""
    mock_client.async_connect.side_effect = FloLogicConnectionError("down")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize("reloads", [1, 3])
async def test_reloading_is_clean(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    reloads: int,
) -> None:
    """Repeated reloads must not accumulate devices or sessions."""
    await setup_integration(hass, config_entry)
    for _ in range(reloads):
        assert await hass.config_entries.async_reload(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    devices = dr.async_get(hass).devices.get_devices_for_config_entry_id(
        config_entry.entry_id
    )
    assert len(devices) == 1
    assert mock_client.async_disconnect.await_count == reloads


async def test_the_domain_is_registered(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Sanity check that the component loads under its own domain."""
    await setup_integration(hass, config_entry)
    assert config_entry.domain == DOMAIN
