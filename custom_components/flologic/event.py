"""Event entity carrying FloLogic's own notification log.

This is the only place a flow event is reliably recorded. The cloud's live
telemetry misses short flows entirely -- a valve that shut itself off after 30
seconds never reported the flow that tripped it -- but the log always has the
event, with the threshold that was crossed and who or what caused it.

It is deliberately not the primary alarm path: the mode bitfield arrives by
push within about a second, while the log is fetched on the polling cycle. Use
this for context and history, and the water-off binary sensor for urgency.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyflologic import Notification, Valve

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity

EVENT_SHUTOFF = "water_shutoff"
EVENT_MODE_CHANGE = "mode_change"
EVENT_NOTICE = "notice"

EVENT_TYPES = [EVENT_SHUTOFF, EVENT_MODE_CHANGE, EVENT_NOTICE]


def classify(notification: Notification) -> str:
    """Bucket a notification by what it tells the user.

    FloLogic's own ``title`` is too coarse to be useful on its own -- an
    automatic shutoff and an ordinary mode change both arrive as "Mode Change"
    -- so the shutoff case is picked out of the text, which states it plainly.
    """
    text = (notification.message or "").upper()
    if "SHUTOFF" in text or "SHUT OFF" in text:
        return EVENT_SHUTOFF
    if (notification.title or "").lower() == "mode change":
        return EVENT_MODE_CHANGE
    return EVENT_NOTICE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one notification event entity per controllable valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicNotificationEvent(coordinator, valve)
        for valve in coordinator.data.controllable_valves.values()
    )


class FloLogicNotificationEvent(FloLogicValveEntity, EventEntity):
    """Fires when FloLogic records something about this valve."""

    _attr_translation_key = "notification"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: FloLogicCoordinator, valve: Valve) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, valve, "notification")
        self._last_id: int | None = None

    async def async_added_to_hass(self) -> None:
        """Start from the newest existing row without replaying history.

        Every notification the account already holds would otherwise fire on
        the first update after a restart, which for a shutoff event means a
        false alarm on every reload.
        """
        await super().async_added_to_hass()
        newest = self._newest()
        if newest is not None:
            self._last_id = newest.notification_id

    def _newest(self) -> Notification | None:
        """Return the most recent notification for this valve."""
        rows = self.coordinator.notifications.get(self._valve_id) or []
        return rows[0] if rows else None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire for a notification that has not been seen before."""
        newest = self._newest()
        if newest is None or newest.notification_id is None:
            return
        if newest.notification_id == self._last_id:
            super()._handle_coordinator_update()
            return

        self._last_id = newest.notification_id
        self._trigger_event(
            classify(newest),
            {
                "message": newest.message,
                "title": newest.title,
                "created": (
                    newest.created_at.isoformat() if newest.created_at else None
                ),
            },
        )
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the most recent message alongside the event."""
        newest = self._newest()
        if newest is None:
            return None
        return {"message": newest.message}
