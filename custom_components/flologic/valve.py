"""Valve entity: the water shutoff itself."""

from __future__ import annotations

from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyflologic import ControlMode, FloLogicError

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity

PARALLEL_UPDATES = 0
"""Unlimited: every read comes from the coordinator's single snapshot, and the
library serializes writes onto one connection regardless of what is asked for
here."""

OPEN_MODE = ControlMode.HOME
"""The mode "open" maps to.

FloLogic has no plain open/closed axis -- an open valve is in one of several
modes that differ in how aggressively they cut the water off. Home is the
least restrictive, so opening from Home Assistant lands there. Anyone who
normally runs in Away should use the mode select rather than this entity, or
opening will quietly relax their flow limit.
"""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one valve entity per controllable valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicValve(coordinator, valve)
        for valve in coordinator.data.controllable_valves.values()
    )


class FloLogicValve(FloLogicValveEntity, ValveEntity):
    """The main water shutoff for one valve."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _attr_name = None

    def __init__(self, coordinator: FloLogicCoordinator, valve: Any) -> None:
        """Initialize the valve entity."""
        super().__init__(coordinator, valve, "valve")

    @property
    def is_closed(self) -> bool | None:
        """Return whether the water is off.

        True for every condition that closes the valve, not just a user
        shutoff: a leak, an exceeded flow limit or a low-temperature trip all
        mean the water is off, and reporting "open" through any of them would
        be actively misleading.

        Note this reflects the *valve*, not the taps. Downstream pipes were
        observed draining for tens of seconds after a close, longer on a hot
        line where a water heater sits below the valve.
        """
        valve = self.valve
        if valve is None:
            return None
        return bool(valve.active_water_off_flags)

    async def async_open_valve(self, **kwargs: Any) -> None:
        """Open the water by returning the valve to Home."""
        del kwargs
        await self._async_set_mode(OPEN_MODE)

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Shut the water off."""
        del kwargs
        await self._async_set_mode(ControlMode.SHUTOFF)

    async def _async_set_mode(self, mode: ControlMode) -> None:
        """Command the valve, surfacing failures to the caller."""
        try:
            await self.coordinator.client.async_set_mode(self._valve_id, mode)
        except FloLogicError as err:
            raise HomeAssistantError(
                translation_domain=self.coordinator.config_entry.domain,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # The command only returns once the valve reports the new state, so
        # the cache is already current; this just publishes it to the entities.
        self.coordinator.async_set_updated_data(self.coordinator.client.account)
