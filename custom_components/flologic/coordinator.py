"""Coordinator holding every valve one set of credentials can see.

One coordinator per config entry. A single refresh reads every valve -- the
VID list, then their status ten at a time -- so a coordinator per valve would
multiply requests against an API with an undocumented rate limit.

Polling is the baseline, because the Web API has no push channel of its own.
When callbacks are enabled, a verified callback updates the affected valve at
once from what the callback carried, and then asks for a confirming refresh.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, EVENT_CALLBACK, SIGNAL_CALLBACK
from .vendor.pyflologic import (
    CallbackEvent,
    CallbackEventType,
    FloLogicAuthError,
    FloLogicClient,
    FloLogicError,
    Valve,
)

_LOGGER = logging.getLogger(__name__)

type FloLogicConfigEntry = ConfigEntry[FloLogicCoordinator]


def snake(name: str) -> str:
    """Convert FloLogic's PascalCase names to Home Assistant's snake_case."""
    out = ""
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out += "_"
        out += char.lower()
    return out


class FloLogicCoordinator(DataUpdateCoordinator[dict[str, Valve]]):
    """Keeps every valve on the account up to date."""

    config_entry: FloLogicConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FloLogicConfigEntry,
        client: FloLogicClient,
        poll_interval: float,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=poll_interval),
        )
        self.client = client
        self.last_callback: dict[str, CallbackEvent] = {}

    async def _async_update_data(self) -> dict[str, Valve]:
        """Re-read every valve."""
        try:
            return await self.client.async_refresh()
        except FloLogicAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FloLogicError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def async_handle_callback(self, event: CallbackEvent) -> None:
        """Act on one verified callback.

        The callback's own fields are applied to the cached valve straight
        away -- that is the whole point of having callbacks -- and a refresh
        follows to replace the estimate with what FloLogic reports. A mode
        carrying a flag name this library cannot map is not applied, since a
        partial mode could read as a different state; the refresh covers it.
        """
        if event.vid:
            self.last_callback[event.vid] = event
        self.hass.bus.async_fire(EVENT_CALLBACK, callback_event_data(event))
        async_dispatcher_send(
            self.hass,
            SIGNAL_CALLBACK.format(entry_id=self.config_entry.entry_id),
            event,
        )

        valve = self.data.get(event.vid or "") if self.data else None
        if valve is not None:
            patched = dict(valve.raw)
            if event.current_mode is not None and not event.unknown_mode_names:
                patched["Mode"] = int(event.current_mode)
            if event.event_type is CallbackEventType.ONLINE:
                patched["Online"] = True
            elif event.event_type is CallbackEventType.OFFLINE:
                patched["Online"] = False
            if patched != valve.raw:
                self.async_set_updated_data({**self.data, valve.vid: Valve(patched)})

        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), "flologic callback refresh"
        )

    async def async_shutdown(self) -> None:
        """Close the HTTP session if the client owns one."""
        await super().async_shutdown()
        await self.client.async_close()

    # --- helpers for entities -------------------------------------------

    def valve(self, vid: str) -> Valve | None:
        """Return one valve from the latest snapshot, if it is still present."""
        return self.data.get(vid) if self.data else None


def callback_event_data(event: CallbackEvent) -> dict[str, Any]:
    """Return a callback as plain data, for the bus and for entity attributes."""
    return {
        "vid": event.vid,
        "event_type": (
            snake(event.event_type.value) if event.event_type else event.event_type_raw
        ),
        "reason": snake(event.reason.value) if event.reason else event.reason_raw,
        "previous_mode": (
            [name.lower() for name in event.previous_mode.flag_names]
            if event.previous_mode is not None
            else None
        ),
        "current_mode": (
            [name.lower() for name in event.current_mode.flag_names]
            if event.current_mode is not None
            else None
        ),
        "unknown_mode_names": event.unknown_mode_names or None,
        "source_vid": event.source_vid,
        "temperature": event.temperature,
        "temperature_threshold": event.temperature_threshold,
        "interval_seconds": event.interval_seconds,
        "update_target": (
            snake(event.update_target.value) if event.update_target else None
        ),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
    }
