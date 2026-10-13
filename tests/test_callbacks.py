"""Callbacks end to end: registration, signed delivery, and what it updates."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.flologic.const import (
    CONF_CALLBACK_URL,
    CONF_CLOUDHOOK,
    CONF_USE_CALLBACKS,
    CONF_WEBHOOK_SECRET,
    EVENT_CALLBACK,
)
from custom_components.flologic.vendor.pyflologic import (
    CALLBACK_VARIABLES,
    CallbackDefinition,
    FloLogicConnectionError,
    compute_signature,
)

from .conftest import (
    DEVICE,
    SECRET,
    VID,
    make_entry,
    make_valve,
    set_valves,
    setup_integration,
)

VALVE = f"valve.{DEVICE}"
EVENT = f"event.{DEVICE}_event"
EXTERNAL = "https://ha.example.com"

ClientFactory = Callable[[], Awaitable[TestClient]]

AUTO_SHUTOFF = {
    "vid": VID,
    "event_type": "AutoShutoff",
    "reason": "FlowTimeExceeded",
    "previous_mode": "Away",
    "current_mode": "Away,ShutOff,FlowTimeExceeded",
    "device_type": "WifiConnect",
    "occurred_at": "2026-10-13T16:01:02Z",
}


@pytest.fixture
async def callbacks_entry(hass: HomeAssistant) -> MockConfigEntry:
    """An entry with callbacks on, on an instance with an external URL."""
    await async_process_ha_core_config(hass, {"external_url": EXTERNAL})
    return make_entry({CONF_USE_CALLBACKS: True})


async def deliver(  # noqa: PLR0913 -- a test helper mirroring one delivery
    hass: HomeAssistant,
    hass_client_no_auth: ClientFactory,
    entry: MockConfigEntry,
    values: dict[str, str],
    *,
    secret: str = SECRET,
    timestamp: int | None = None,
    settle: bool = True,
) -> int:
    """Deliver a callback the way FloLogic does, and return the HTTP status.

    ``settle=False`` skips waiting for Home Assistant to go idle, for tests
    that hold the follow-up refresh open on purpose.
    """
    registered = entry.data[CONF_CALLBACK_URL]
    final = registered
    for name in CALLBACK_VARIABLES:
        final = final.replace(f"{{{name}}}", quote(values.get(name, ""), safe=""))
    stamp = int(time.time()) if timestamp is None else timestamp
    headers = {
        "X-FloLogic-Timestamp": str(stamp),
        "X-FloLogic-Signature": compute_signature(secret, stamp, final),
    }
    raw_query = final.split("?", 1)[1]
    client = await hass_client_no_auth()
    response = await client.get(
        f"/api/webhook/{entry.data[CONF_WEBHOOK_ID]}?{raw_query}", headers=headers
    )
    if settle:
        await hass.async_block_till_done()
    else:
        await asyncio.sleep(0)
    return response.status


class TestRegistration:
    async def test_registers_with_flologic_using_the_external_url(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
    ):
        await setup_integration(hass, callbacks_entry)
        registered = callbacks_entry.data[CONF_CALLBACK_URL]
        webhook_id = callbacks_entry.data[CONF_WEBHOOK_ID]
        assert registered.startswith(f"{EXTERNAL}/api/webhook/{webhook_id}?vid={{vid}}")
        assert callbacks_entry.data[CONF_CLOUDHOOK] is False
        mock_client.async_add_callback.assert_awaited_once_with(
            CallbackDefinition(registered)
        )
        mock_client.async_remove_callbacks.assert_not_awaited()

    async def test_a_restart_keeps_the_same_url(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
    ):
        await setup_integration(hass, callbacks_entry)
        first = callbacks_entry.data[CONF_CALLBACK_URL]
        await hass.config_entries.async_reload(callbacks_entry.entry_id)
        await hass.async_block_till_done()
        assert callbacks_entry.data[CONF_CALLBACK_URL] == first
        mock_client.async_remove_callbacks.assert_not_awaited()

    async def test_a_changed_url_replaces_the_old_registration(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
    ):
        await setup_integration(hass, callbacks_entry)
        first = callbacks_entry.data[CONF_CALLBACK_URL]
        await async_process_ha_core_config(
            hass, {"external_url": "https://new.example"}
        )
        await hass.config_entries.async_reload(callbacks_entry.entry_id)
        await hass.async_block_till_done()
        mock_client.async_remove_callbacks.assert_awaited_once_with(first)
        assert callbacks_entry.data[CONF_CALLBACK_URL].startswith(
            "https://new.example/"
        )

    async def test_switching_callbacks_off_withdraws_the_registration(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
    ):
        await setup_integration(hass, callbacks_entry)
        registered = callbacks_entry.data[CONF_CALLBACK_URL]
        hass.config_entries.async_update_entry(
            callbacks_entry, options={CONF_USE_CALLBACKS: False}
        )
        await hass.async_block_till_done()
        mock_client.async_remove_callbacks.assert_awaited_once_with(registered)
        assert CONF_CALLBACK_URL not in callbacks_entry.data
        assert hass.states.get(EVENT) is None

    async def test_removing_the_entry_withdraws_the_registration(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
    ):
        await setup_integration(hass, callbacks_entry)
        registered = callbacks_entry.data[CONF_CALLBACK_URL]
        await hass.config_entries.async_remove(callbacks_entry.entry_id)
        await hass.async_block_till_done()
        mock_client.async_remove_callbacks.assert_awaited_once_with(registered)

    async def test_no_reachable_url_falls_back_to_polling(
        self, hass: HomeAssistant, mock_client: MagicMock
    ):
        config_entry = make_entry({CONF_USE_CALLBACKS: True})
        await setup_integration(hass, config_entry)
        assert hass.states.get(VALVE).state == "open"
        assert CONF_CALLBACK_URL not in config_entry.data
        mock_client.async_add_callback.assert_not_awaited()

    async def test_flologic_failing_to_register_falls_back_to_polling(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
    ):
        mock_client.async_add_callback.side_effect = FloLogicConnectionError("down")
        await setup_integration(hass, callbacks_entry)
        assert hass.states.get(VALVE).state == "open"


class TestDelivery:
    async def test_an_auto_shutoff_updates_state_before_the_refresh_returns(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        """The point of callbacks: state changes in seconds, not on the next poll."""
        await setup_integration(hass, callbacks_entry)
        release = asyncio.Event()
        refreshes = 0

        async def slow_refresh(**_: Any) -> dict[str, Any]:
            nonlocal refreshes
            refreshes += 1
            await release.wait()
            return dict(mock_client.valves)

        mock_client.async_refresh.side_effect = slow_refresh
        set_valves(mock_client, make_valve(Mode=2 | 8 | 32))
        client = await hass_client_no_auth()
        stamp = int(time.time())
        registered = callbacks_entry.data[CONF_CALLBACK_URL]
        final = registered
        for name in CALLBACK_VARIABLES:
            final = final.replace(
                f"{{{name}}}", quote(AUTO_SHUTOFF.get(name, ""), safe="")
            )
        webhook_id = callbacks_entry.data[CONF_WEBHOOK_ID]
        raw_query = final.split("?", 1)[1]
        response = await client.get(
            f"/api/webhook/{webhook_id}?{raw_query}",
            headers={
                "X-FloLogic-Timestamp": str(stamp),
                "X-FloLogic-Signature": compute_signature(SECRET, stamp, final),
            },
        )
        assert response.status == 200
        await asyncio.sleep(0)
        assert hass.states.get(VALVE).state == "closed"
        assert refreshes == 1  # asked for, still outstanding
        release.set()
        await hass.async_block_till_done()
        assert hass.states.get(VALVE).state == "closed"

    async def test_the_event_entity_fires_with_the_reason(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        await setup_integration(hass, callbacks_entry)
        assert (
            await deliver(hass, hass_client_no_auth, callbacks_entry, AUTO_SHUTOFF)
            == 200
        )
        state = hass.states.get(EVENT)
        assert state is not None
        assert state.attributes["event_type"] == "auto_shutoff"
        assert state.attributes["reason"] == "flow_time_exceeded"
        assert state.attributes["current_mode"] == [
            "away",
            "shutoff",
            "flow_time_exceeded",
        ]
        assert state.attributes["occurred_at"] == "2026-10-13T16:01:02+00:00"

    async def test_a_bus_event_carries_the_callback(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        events = async_capture_events(hass, EVENT_CALLBACK)
        await setup_integration(hass, callbacks_entry)
        await deliver(hass, hass_client_no_auth, callbacks_entry, AUTO_SHUTOFF)
        assert len(events) == 1
        assert events[0].data["vid"] == VID
        assert events[0].data["event_type"] == "auto_shutoff"

    async def test_offline_and_online_update_connectivity(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        await setup_integration(hass, callbacks_entry)
        release = asyncio.Event()

        async def held_refresh(**_: Any) -> dict[str, Any]:
            await release.wait()
            return dict(mock_client.valves)

        # Held, so the state seen is the callback's, not the refresh's.
        mock_client.async_refresh.side_effect = held_refresh
        await deliver(
            hass,
            hass_client_no_auth,
            callbacks_entry,
            {"vid": VID, "event_type": "Offline", "reason": "DeviceOffline"},
            settle=False,
        )
        assert hass.states.get(f"binary_sensor.{DEVICE}_connectivity").state == "off"
        assert hass.states.get(EVENT).attributes["event_type"] == "offline"
        release.set()
        await hass.async_block_till_done()

    async def test_an_unmapped_mode_is_not_applied_but_still_announced(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        await setup_integration(hass, callbacks_entry)
        await deliver(
            hass,
            hass_client_no_auth,
            callbacks_entry,
            {"vid": VID, "event_type": "ModeChanged", "current_mode": "ShutOff,Hover"},
        )
        assert hass.states.get(VALVE).state == "open"
        state = hass.states.get(EVENT)
        assert state.attributes["event_type"] == "mode_changed"
        assert state.attributes["unknown_mode_names"] == ["Hover"]

    async def test_an_unknown_event_type_fires_as_other(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        await setup_integration(hass, callbacks_entry)
        await deliver(
            hass,
            hass_client_no_auth,
            callbacks_entry,
            {"vid": VID, "event_type": "Novel"},
        )
        state = hass.states.get(EVENT)
        assert state.attributes["event_type"] == "other"
        assert state.attributes["raw_event_type"] == "Novel"

    async def test_a_callback_for_another_valve_is_not_this_ones(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        await setup_integration(hass, callbacks_entry)
        before = hass.states.get(EVENT).state
        await deliver(
            hass,
            hass_client_no_auth,
            callbacks_entry,
            {**AUTO_SHUTOFF, "vid": "OTHER1"},
        )
        assert hass.states.get(EVENT).state == before
        assert hass.states.get(VALVE).state == "open"


class TestRejection:
    async def test_a_wrong_signature_changes_nothing(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        events = async_capture_events(hass, EVENT_CALLBACK)
        await setup_integration(hass, callbacks_entry)
        status = await deliver(
            hass, hass_client_no_auth, callbacks_entry, AUTO_SHUTOFF, secret="guess"
        )
        assert status == 200  # nothing to learn from the response
        assert events == []
        assert hass.states.get(VALVE).state == "open"

    async def test_a_replayed_delivery_is_refused(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        events = async_capture_events(hass, EVENT_CALLBACK)
        await setup_integration(hass, callbacks_entry)
        await deliver(
            hass,
            hass_client_no_auth,
            callbacks_entry,
            AUTO_SHUTOFF,
            timestamp=int(time.time()) - 3600,
        )
        assert events == []

    async def test_without_a_secret_nothing_is_accepted(
        self,
        hass: HomeAssistant,
        callbacks_entry: MockConfigEntry,
        mock_client: MagicMock,
        hass_client_no_auth: ClientFactory,
    ):
        events = async_capture_events(hass, EVENT_CALLBACK)
        await setup_integration(hass, callbacks_entry)
        hass.config_entries.async_update_entry(
            callbacks_entry,
            data={
                key: value
                for key, value in callbacks_entry.data.items()
                if key != CONF_WEBHOOK_SECRET
            },
        )
        await hass.async_block_till_done()
        await deliver(hass, hass_client_no_auth, callbacks_entry, AUTO_SHUTOFF)
        assert events == []
