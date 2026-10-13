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

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity
from .vendor.pyflologic import ControlMode, FloLogicError, Valve

PARALLEL_UPDATES = 0
"""Unlimited: reads come from the coordinator's snapshot, and FloLogic, not
Home Assistant, is the place to serialize writes to one valve."""

OPEN_MODE = ControlMode.HOME
"""The mode "open" maps to.

FloLogic has no plain open/closed axis -- an open valve is in one of several
modes that differ in how aggressively they cut the water off. Home is the
least restrictive, so opening from Home Assistant lands there. Anyone who
normally runs in Away should use the mode select, or opening will quietly
relax their flow limit.
"""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one valve entity per valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicValve(coordinator, valve) for valve in coordinator.data.values()
    )


async def async_command(entity: FloLogicValveEntity, mode: ControlMode) -> None:
    """Put an entity's valve into ``mode``, surfacing failures to the caller."""
    coordinator = entity.coordinator
    try:
        await coordinator.client.async_set_mode(entity.vid, mode)
    except FloLogicError as err:
        raise HomeAssistantError(
            translation_domain=coordinator.config_entry.domain,
            translation_key="command_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    # The command returns only once the valve reports the new mode, so the
    # client already holds the fresh state; this publishes it.
    coordinator.async_set_updated_data(
        {**coordinator.data, **coordinator.client.valves}
    )


class FloLogicValve(FloLogicValveEntity, ValveEntity):
    """The main water shutoff for one valve."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _attr_name = None

    def __init__(self, coordinator: FloLogicCoordinator, valve: Valve) -> None:
        """Initialize the valve entity."""
        super().__init__(coordinator, valve, "valve")

    @property
    def is_closed(self) -> bool | None:
        """Return whether the water is off.

        True for every condition that closes the valve, not just a person's
        shutoff: a leak, an exceeded flow limit or a freeze trip all mean the
        water is off, and reporting "open" through any of them would be
        actively misleading.
        """
        valve = self.valve
        if valve is None:
            return None
        return valve.is_water_off

    async def async_open_valve(self, **kwargs: Any) -> None:
        """Open the water by returning the valve to Home."""
        del kwargs
        await async_command(self, OPEN_MODE)

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Shut the water off."""
        del kwargs
        await async_command(self, ControlMode.SHUTOFF)
