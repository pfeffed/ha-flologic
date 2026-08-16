"""Diagnostics, with the emphasis on what must not appear in them."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import make_account, make_valve, setup_integration

SECRETS = [
    "pw-MUST-NOT-LEAK",  # the password
    "tok-MUST-NOT-LEAK",  # the device token
    "AND-test",  # the device code
    "34 Sample Road",  # the street address
    "Doe",  # the policy holder
    "Riverside",  # the site name
]


async def test_nothing_sensitive_survives_redaction(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """A diagnostics file gets attached to public issues.

    Checked against the whole serialized document rather than field by field,
    because the leak that matters is the one in a field nobody thought about.
    """
    account = make_account(
        make_valve(
            insurancePolicy="Example Insurance",
            policyLastName="Doe",
            location='{"a":"34 Sample Road","c":"Springfield","s":"CA"}',
        )
    )
    mock_client.account = account
    mock_client.valves = dict(account.valves)
    await setup_integration(hass, config_entry)

    document = json.dumps(
        await async_get_config_entry_diagnostics(hass, config_entry), default=str
    )
    for secret in SECRETS:
        assert secret not in document, secret


async def test_the_useful_protocol_detail_is_kept(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Redaction must not gut the reason for having diagnostics at all."""
    account = make_account(make_valve(mode=40))
    mock_client.account = account
    mock_client.valves = dict(account.valves)
    await setup_integration(hass, config_entry)

    result = await async_get_config_entry_diagnostics(hass, config_entry)
    valve = result["valves"]["106193"]

    assert valve["decoded"]["raw_mode"] == 40
    assert set(valve["decoded"]["mode_flags"]) == {"SHUTOFF", "FLOW_TIME_EXCEEDED"}
    assert valve["decoded"]["status"] == "flow_time_exceeded"
    # The battery quirk is exactly the sort of thing a report needs to show.
    assert valve["decoded"]["battery_percent"] is None
    assert valve["decoded"]["battery_level_raw"] == 134217728
    # Raw fields survive so an unrecognized state can be diagnosed.
    assert valve["raw"]["mode"] == 40
    assert valve["raw"]["homeIntervalTime"] == 99.0


async def test_unknown_mode_bits_are_reported(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """The first question about an unrecognized state is which bit it was."""
    account = make_account(make_valve(mode=1 | (1 << 27)))
    mock_client.account = account
    mock_client.valves = dict(account.valves)
    await setup_integration(hass, config_entry)

    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["valves"]["106193"]["decoded"]["mode_unknown_bits"] == 1 << 27
