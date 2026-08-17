"""Coordinator behavior: pushes, polling, and failure handling."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.flologic.const import CONF_POLL_INTERVAL
from custom_components.flologic.vendor.pyflologic import (
    DEFAULT_POLL_INTERVAL,
    FloLogicAuthError,
    FloLogicConnectionError,
    ValveMode,
)

from .conftest import make_account, make_valve, setup_integration

VALVE_ENTITY = "valve.34_sample_road"
STATUS_ENTITY = "sensor.34_sample_road_status"


def push(mock_client: MagicMock, *valves: object) -> None:
    """Invoke the listener the coordinator registered, as the library does."""
    account = make_account(*valves)  # type: ignore[arg-type]
    mock_client.account = account
    mock_client.valves = dict(account.valves)
    listener = mock_client.add_listener.call_args[0][0]
    listener(account)


class TestPushUpdates:
    """The primary update path: the cloud tells us, we do not ask."""

    async def test_a_push_reaches_the_entities(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        assert hass.states.get(STATUS_ENTITY).state == "home"

        push(mock_client, make_valve(mode=40))
        await hass.async_block_till_done()

        assert hass.states.get(STATUS_ENTITY).state == "flow_time_exceeded"
        assert hass.states.get(VALVE_ENTITY).state == "closed"

    async def test_a_listener_is_registered_exactly_once(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """A listener added per refresh would multiply updates on every poll."""
        await setup_integration(hass, config_entry)
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert mock_client.add_listener.call_count == 1

    async def test_a_push_arrives_without_polling(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        polls_before = mock_client.async_refresh.call_count
        push(mock_client, make_valve(mode=int(ValveMode.BYPASS)))
        await hass.async_block_till_done()

        assert hass.states.get(STATUS_ENTITY).state == "bypass"
        assert mock_client.async_refresh.call_count == polls_before


class TestPolling:
    """The fallback path."""

    async def test_the_default_interval_comes_from_the_library(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """The floor is advice about the cloud, so it belongs with the client."""
        await setup_integration(hass, config_entry)
        assert config_entry.runtime_data.update_interval == timedelta(
            seconds=DEFAULT_POLL_INTERVAL
        )

    async def test_the_option_overrides_it(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            config_entry, options={CONF_POLL_INTERVAL: 120}
        )
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert config_entry.runtime_data.update_interval == timedelta(seconds=120)

    async def test_polling_happens_on_schedule(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
        freezer: FrozenDateTimeFactory,
    ) -> None:
        await setup_integration(hass, config_entry)
        before = mock_client.async_refresh.call_count

        freezer.tick(timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert mock_client.async_refresh.call_count > before


class TestFailureHandling:
    """What entities do when the cloud stops answering."""

    async def test_a_failed_poll_makes_entities_unavailable(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
        freezer: FrozenDateTimeFactory,
    ) -> None:
        await setup_integration(hass, config_entry)
        mock_client.async_refresh.side_effect = FloLogicConnectionError("down")

        freezer.tick(timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert hass.states.get(VALVE_ENTITY).state == STATE_UNAVAILABLE

    async def test_entities_recover_when_the_cloud_does(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
        freezer: FrozenDateTimeFactory,
    ) -> None:
        await setup_integration(hass, config_entry)
        mock_client.async_refresh.side_effect = FloLogicConnectionError("down")
        freezer.tick(timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert hass.states.get(VALVE_ENTITY).state == STATE_UNAVAILABLE

        mock_client.async_refresh.side_effect = None
        freezer.tick(timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert hass.states.get(VALVE_ENTITY).state == "open"

    async def test_a_mid_run_auth_failure_starts_reauth(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
        freezer: FrozenDateTimeFactory,
    ) -> None:
        """A password changed elsewhere must prompt, not fail forever."""
        await setup_integration(hass, config_entry)
        mock_client.async_refresh.side_effect = FloLogicAuthError("rejected")

        freezer.tick(timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        flows = hass.config_entries.flow.async_progress()
        assert [flow["context"]["source"] for flow in flows] == ["reauth"]

    @pytest.mark.parametrize("failures", [1, 3])
    async def test_notification_failures_do_not_fail_the_update(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
        freezer: FrozenDateTimeFactory,
        failures: int,
    ) -> None:
        """Valve state matters far more than the log; they must not share fate."""
        await setup_integration(hass, config_entry)
        mock_client.async_fetch_notifications.side_effect = FloLogicConnectionError(
            "no log"
        )
        for _ in range(failures):
            freezer.tick(timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

        assert config_entry.state is ConfigEntryState.LOADED
        assert hass.states.get(VALVE_ENTITY).state == "open"
