"""The notification event entity."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.event import (
    EVENT_MODE_CHANGE,
    EVENT_NOTICE,
    EVENT_SHUTOFF,
    classify,
)
from custom_components.flologic.vendor.pyflologic import FloLogicConnectionError

from .conftest import make_notification, setup_integration

EVENT_ENTITY = "event.34_sample_road_notification"

SHUTOFF_TEXT = (
    "WATER SHUTOFF: Away flow limit of 30 seconds exceeded. "
    "Water has been shut off for 34 Sample Road."
)
MODE_TEXT = (
    "NOTICE: Away Mode activated by sampleuser to Local Controls. "
    "Flow limit of 30 seconds is now active."
)


class TestClassification:
    """Bucketing a notification by what it tells the user."""

    def test_a_shutoff_is_not_just_a_mode_change(self) -> None:
        # FloLogic titles an automatic shutoff "Mode Change", the same as an
        # ordinary one, so the title alone cannot distinguish an emergency.
        row = make_notification(1, SHUTOFF_TEXT)
        assert row.title == "Mode Change"
        assert classify(row) == EVENT_SHUTOFF

    def test_an_ordinary_mode_change(self) -> None:
        assert classify(make_notification(2, MODE_TEXT)) == EVENT_MODE_CHANGE

    def test_anything_else_is_a_notice(self) -> None:
        row = make_notification(3, "Water has been turned ON.")
        object.__setattr__(row, "raw", {**row.raw, "title": "Something"})
        assert classify(row) == EVENT_NOTICE


class TestEventEntity:
    """Firing, and deliberately not firing."""

    async def test_history_is_not_replayed_on_startup(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        """A restart must not re-announce an old shutoff as if it just happened."""
        mock_client.async_fetch_notifications.return_value = [
            make_notification(52495530, SHUTOFF_TEXT)
        ]
        await setup_integration(hass, config_entry)

        state = hass.states.get(EVENT_ENTITY)
        assert state is not None
        assert state.state in ("unknown", "unavailable")

    async def test_a_new_notification_fires(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        mock_client.async_fetch_notifications.return_value = [
            make_notification(1, MODE_TEXT)
        ]
        await setup_integration(hass, config_entry)

        mock_client.async_fetch_notifications.return_value = [
            make_notification(2, SHUTOFF_TEXT, created="2026-08-16T19:00:00"),
            make_notification(1, MODE_TEXT),
        ]
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        state = hass.states.get(EVENT_ENTITY)
        assert state.attributes["event_type"] == EVENT_SHUTOFF
        assert "Away flow limit" in state.attributes["message"]

    async def test_the_same_notification_does_not_refire(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        mock_client.async_fetch_notifications.return_value = [
            make_notification(1, MODE_TEXT)
        ]
        await setup_integration(hass, config_entry)
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        first = hass.states.get(EVENT_ENTITY).state

        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(EVENT_ENTITY).state == first

    async def test_setup_survives_a_notification_failure(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
    ) -> None:
        """Losing the log must not take the safety entities down with it.

        Valve state and the notification log come from different requests, and
        the log is the less important of the two by a wide margin.
        """
        mock_client.async_fetch_notifications.side_effect = FloLogicConnectionError(
            "no log"
        )
        await setup_integration(hass, config_entry)
        assert hass.states.get("valve.34_sample_road").state == "open"
        assert hass.states.get(EVENT_ENTITY) is not None
