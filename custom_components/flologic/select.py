"""Select entity for the valve's control mode."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyflologic import ControlMode, FloLogicError

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one mode select per controllable valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicModeSelect(coordinator, valve)
        for valve in coordinator.data.controllable_valves.values()
    )


class FloLogicModeSelect(FloLogicValveEntity, SelectEntity):
    """The five modes a user can put the valve into."""

    _attr_translation_key = "valve_mode"
    _attr_options: ClassVar[list[str]] = [mode.value for mode in ControlMode]

    def __init__(self, coordinator: FloLogicCoordinator, valve: Any) -> None:
        """Initialize the select."""
        super().__init__(coordinator, valve, "valve_mode")

    @property
    def current_option(self) -> str | None:
        """Return the current control mode.

        None whenever the valve is in a state the user cannot select -- an
        irrigation controller holding it in Override, for instance. Reporting
        one of the five options there would invent a mode the valve is not in.
        """
        valve = self.valve
        if valve is None or valve.control_mode is None:
            return None
        return valve.control_mode.value

    async def async_select_option(self, option: str) -> None:
        """Put the valve into the chosen mode."""
        try:
            await self.coordinator.client.async_set_mode(self._valve_id, option)
        except FloLogicError as err:
            raise HomeAssistantError(
                translation_domain=self.coordinator.config_entry.domain,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.coordinator.async_set_updated_data(self.coordinator.client.account)
