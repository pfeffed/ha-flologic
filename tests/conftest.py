"""Fixtures for the FloLogic integration tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.const import (
    CONF_COMPANY_ID,
    CONF_WEBHOOK_SECRET,
    CONFIG_VERSION,
    DOMAIN,
)
from custom_components.flologic.vendor.pyflologic import CallbackDefinition, Valve

pytest_plugins = "pytest_homeassistant_custom_component"

VID = "414B91"
DEVICE = "flologic_414b91"
"""The entity-ID prefix Home Assistant derives from the device name."""

SECRET = "whsec-MUST-NOT-LEAK"
API_KEY = "key-MUST-NOT-LEAK"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""
    del enable_custom_integrations


def make_valve(vid: str = VID, **overrides: Any) -> Valve:
    """Build a valve from a payload shaped like a live status object."""
    raw: dict[str, Any] = {
        "VID": vid,
        "Type": "WiFiConnect",
        "Online": True,
        "Address": "1 Example Lane, Springfield",
        "Mode": 1,
        "FlowState": 1,
        "DripRate": 6,
        "Temperature": 70,
        "LastFlowDateTime": "2026-10-13T15:40:10",
        "HomeTime": 60,
        "AwayTime": 0.1,
        "BypassTimeEnabled": True,
        "BypassTime": 241,
        "LowTemperatureAlertEnabled": True,
        "LowTemperatureAlertThreshold": 38,
        "LowTemperatureShutoffEnabled": True,
        "LowTemperatureShutoffThreshold": 36,
        "PreAlertNoticeTime": 5,
    }
    raw.update(overrides)
    return Valve({key: value for key, value in raw.items() if value is not None})


def valves_of(*valves: Valve) -> dict[str, Valve]:
    """Key valves by VID, defaulting to a single one."""
    return {valve.vid: valve for valve in (valves or (make_valve(),))}


def make_entry(options: dict[str, Any] | None = None) -> MockConfigEntry:
    """Return a config entry for one company, with a signing secret."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="FloLogic company 102",
        unique_id="102",
        version=CONFIG_VERSION,
        data={CONF_API_KEY: API_KEY, CONF_COMPANY_ID: 102, CONF_WEBHOOK_SECRET: SECRET},
        options=options or {},
    )


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for one company, polling only."""
    return make_entry()


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Patch the FloLogic client the integration builds."""
    valves = valves_of()
    with patch(
        "custom_components.flologic.FloLogicClient", autospec=True
    ) as client_class:
        client = client_class.return_value
        client.async_refresh = AsyncMock(side_effect=lambda **_: dict(client.valves))
        client.async_close = AsyncMock()
        client.async_set_mode = AsyncMock()
        client.async_set_flow_sensitivity = AsyncMock()
        client.async_add_callback = AsyncMock(
            side_effect=lambda definition: [definition]
        )
        client.async_remove_callbacks = AsyncMock(return_value=[])
        client.async_get_callbacks = AsyncMock(
            return_value=[CallbackDefinition("https://test.api-callback.com/x")]
        )
        client.valves = valves
        yield client


def set_valves(client: MagicMock, *valves: Valve) -> None:
    """Change what the mocked client returns on its next refresh."""
    client.valves = valves_of(*valves)


def get_device(hass: HomeAssistant, entry: ConfigEntry, vid: str = VID) -> DeviceEntry:
    """Return the device for a valve.

    Looked up through the entry rather than ``async_get_device``, which newer
    Home Assistant refuses because identifiers are no longer unique across
    config entries.
    """
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    for device in devices:
        if (DOMAIN, vid) in device.identifiers:
            return device
    raise AssertionError(f"no device for {vid}")


async def setup_integration(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Add and set up the config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
