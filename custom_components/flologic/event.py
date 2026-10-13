"""Event entity carrying FloLogic's typed callback events.

Created only when callbacks are enabled, since without them nothing would
ever fire. Each event carries FloLogic's stable reason code, which is the
most useful thing the Web API offers over reading mode bits: an automatic
shutoff arrives as ``auto_shutoff`` with ``flow_time_exceeded`` or
``pinpoint_leak``, while a person closing the valve arrives as
``mode_changed`` -- never as ``auto_shutoff``.
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_USE_CALLBACKS, SIGNAL_CALLBACK
from .coordinator import (
    FloLogicConfigEntry,
    FloLogicCoordinator,
    callback_event_data,
    snake,
)
from .entity import FloLogicValveEntity
from .vendor.pyflologic import CallbackEvent, CallbackEventType, Valve

PARALLEL_UPDATES = 0
"""Unlimited: events arrive from the coordinator, not from polling."""

OTHER = "other"
"""For an event type FloLogic adds after this integration was written."""

EVENT_TYPES = [snake(event.value) for event in CallbackEventType] + [OTHER]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one callback event entity per valve, if callbacks are on.

    With callbacks off, any event entities left from when they were on are
    removed rather than left behind as permanently unavailable.
    """
    if not entry.options.get(CONF_USE_CALLBACKS):
        registry = er.async_get(hass)
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
            if registered.domain == "event":
                registry.async_remove(registered.entity_id)
        return
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicCallbackEvent(coordinator, valve) for valve in coordinator.data.values()
    )


class FloLogicCallbackEvent(FloLogicValveEntity, EventEntity):
    """Fires when FloLogic reports an event for this valve."""

    _attr_translation_key = "callback"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: FloLogicCoordinator, valve: Valve) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, valve, "callback")

    @property
    def available(self) -> bool:
        """Stay available while the valve is offline.

        Offline is itself one of the events, and an entity that went
        unavailable to announce it would announce nothing.
        """
        return self.coordinator.last_update_success and self.valve is not None

    async def async_added_to_hass(self) -> None:
        """Subscribe to this entry's verified callbacks."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CALLBACK.format(entry_id=self.coordinator.config_entry.entry_id),
                self._handle_callback,
            )
        )

    @callback
    def _handle_callback(self, event: CallbackEvent) -> None:
        """Fire for a callback about this valve."""
        if event.vid != self.vid:
            return
        event_type = snake(event.event_type.value) if event.event_type else OTHER
        data = callback_event_data(event)
        data.pop("vid", None)
        # The entity's own event_type attribute must not be overwritten; an
        # unrecognized type is kept under another name instead.
        raw_type = data.pop("event_type", None)
        if event_type == OTHER:
            data["raw_event_type"] = raw_type
        self._trigger_event(
            event_type, {key: value for key, value in data.items() if value is not None}
        )
        self.async_write_ha_state()
