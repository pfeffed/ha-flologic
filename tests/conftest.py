"""Fixtures for the FloLogic integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pyflologic import Account, Notification, User, Valve
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.const import (
    CONF_DEVICE_CODE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TOKEN,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Let Home Assistant load the integration from custom_components."""
    del enable_custom_integrations


def make_valve(
    valve_id: str = "106193",
    name: str = "34 Sample Road",
    *,
    mode: int = 1,
    flow_state: int = 1,
    online: bool = True,
    **extra: object,
) -> Valve:
    """Build a valve payload shaped like a real WiFi Connect one."""
    raw: dict[str, object] = {
        "id": valve_id,
        "uuid": f"hw-{valve_id}",
        "valveFriendlyName": name,
        "combinedName": name,
        "mode": mode,
        "flowState": flow_state,
        "online": online,
        "isZGateway": False,
        "isWifiConnectDevice": True,
        "deviceTypeName": "WiFi Connect",
        "softwareVersion": "4.1.5",
        "networkName": "Riverside",
        "valveAddress": "34 Sample Road",
        "currentFlow": 0.0,
        "temperature": 65.0,
        "batteryLevel": 134217728,  # the real "not a percentage" value
        "signalStrength": -83.0,
        "dripRate": 3.0,
        "homeIntervalTime": 99.0,
        "awayIntervalTime": 0.5,
        "bypassTime": 901.0,
        "autoAwayTime": 96.0,
        "lowTemperatureAlert": 38.0,
        "lowTemperatureLimit": 36.0,
        "preAlertNoticeInterval": 0.0,
        "lastSeen": "2026-08-16T18:00:00",
    }
    raw.update(extra)
    return Valve(raw)


def make_account(*valves: Valve) -> Account:
    """Build an account snapshot around the given valves."""
    if not valves:
        valves = (make_valve(),)
    return Account(
        user=User({"id": "4297", "email": "owner@example.com"}),
        valves={valve.valve_id: valve for valve in valves},
    )


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for one account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="owner@example.com",
        unique_id="4297",
        data={
            CONF_EMAIL: "owner@example.com",
            # Distinctive values: a redaction test that greps the serialized
            # document needs secrets that cannot appear as a substring of a
            # key name, or it passes for the wrong reason.
            CONF_PASSWORD: "pw-MUST-NOT-LEAK",
            CONF_DEVICE_NAME: "Home Assistant",
            CONF_DEVICE_CODE: "AND-test",
            CONF_DEVICE_TOKEN: "tok-MUST-NOT-LEAK",
        },
    )


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Patch the FloLogic client used by the integration."""
    account = make_account()
    with patch(
        "custom_components.flologic.FloLogicClient", autospec=True
    ) as client_class:
        client = client_class.return_value
        client.async_connect = AsyncMock()
        client.async_disconnect = AsyncMock()
        client.async_refresh = AsyncMock()
        client.async_set_mode = AsyncMock()
        client.async_update_settings = AsyncMock()
        client.async_fetch_notifications = AsyncMock(return_value=[])
        client.add_listener = MagicMock(return_value=lambda: None)
        client.connected = True
        client.account = account
        client.user = account.user
        client.valves = dict(account.valves)
        yield client


async def setup_integration(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Add and set up the config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def make_notification(
    notification_id: int, text: str, created: str = "2026-08-16T18:33:58.147"
) -> Notification:
    """Build a notification row shaped like a real one (no valveId)."""
    return Notification(
        {
            "id": notification_id,
            "created": created,
            "title": "Mode Change",
            "text": text,
            "delivered": False,
        }
    )
