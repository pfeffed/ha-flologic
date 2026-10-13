"""Diagnostics: useful for a bug report, and safe to attach to a public one."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.const import CONF_CALLBACK_URL, CONF_USE_CALLBACKS
from custom_components.flologic.diagnostics import async_get_config_entry_diagnostics

from .conftest import API_KEY, SECRET, VID, make_entry, setup_integration


async def test_the_raw_payload_is_included(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await setup_integration(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    valve = result["valves"][VID]
    assert valve["raw"]["Mode"] == 1
    assert valve["decoded"]["status"] == "home"
    assert valve["last_callback"] is None


async def test_secrets_and_the_address_are_redacted(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    await async_process_ha_core_config(hass, {"external_url": "https://ha.example"})
    entry = make_entry({CONF_USE_CALLBACKS: True})
    await setup_integration(hass, entry)
    registered = entry.data[CONF_CALLBACK_URL]
    document = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    for secret in (API_KEY, SECRET, registered, "Example Lane"):
        assert secret not in document
    webhook_id = registered.split("/api/webhook/")[1].split("?")[0]
    assert webhook_id not in document
