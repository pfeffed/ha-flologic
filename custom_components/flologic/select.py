"""Select entity for the valve's mode."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity
from .valve import async_command
from .vendor.pyflologic import SETTABLE_MODES, ControlMode, Valve

PARALLEL_UPDATES = 0
"""Unlimited: reads come from the coordinator's snapshot."""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one mode select per valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicModeSelect(coordinator, valve) for valve in coordinator.data.values()
    )


class FloLogicModeSelect(FloLogicValveEntity, SelectEntity):
    """The modes the Web API lets a valve be put into.

    Disabled is not among them: the valve can be in it, but the Web API does
    not accept it as a command.
    """

    _attr_translation_key = "valve_mode"
    _attr_options: ClassVar[list[str]] = [mode.value for mode in SETTABLE_MODES]

    def __init__(self, coordinator: FloLogicCoordinator, valve: Valve) -> None:
        """Initialize the select."""
        super().__init__(coordinator, valve, "valve_mode")

    @property
    def current_option(self) -> str | None:
        """Return the current mode, or None for one that cannot be chosen.

        Disabled, or an irrigation controller holding the valve in Override,
        reads as no selection rather than as an option the valve is not in.
        """
        valve = self.valve
        if valve is None or valve.control_mode is None:
            return None
        if valve.control_mode not in SETTABLE_MODES:
            return None
        return valve.control_mode.value

    async def async_select_option(self, option: str) -> None:
        """Put the valve into the chosen mode."""
        await async_command(self, ControlMode(option))
