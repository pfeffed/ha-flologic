"""The one writable setting the Web API offers: flow sensitivity.

Every other setting the app exposes -- flow limits, Auto Away, temperature
thresholds and the rest -- is readable here but not writable, so those are
sensors rather than numbers.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity
from .vendor.pyflologic import FloLogicError, Valve

PARALLEL_UPDATES = 0
"""Unlimited: reads come from the coordinator's snapshot."""

OUNCES_PER_MINUTE = "oz/min"
"""FloLogic's own unit, kept rather than converted.

Home Assistant has no ounces-per-minute member of its volume-flow-rate class,
and converting would put a number on screen that does not match the one in
the FloLogic app.
"""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one flow sensitivity number per valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicFlowSensitivity(coordinator, valve)
        for valve in coordinator.data.values()
    )


class FloLogicFlowSensitivity(FloLogicValveEntity, NumberEntity):
    """The drip rate below which the valve ignores flow."""

    _attr_translation_key = "flow_sensitivity"
    _attr_native_unit_of_measurement = OUNCES_PER_MINUTE
    _attr_native_min_value = 0.1
    _attr_native_max_value = 200
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: FloLogicCoordinator, valve: Valve) -> None:
        """Initialize the number."""
        super().__init__(coordinator, valve, "flow_sensitivity")

    @property
    def native_value(self) -> float | None:
        """Return the current flow sensitivity."""
        valve = self.valve
        return valve.flow_sensitivity_oz_per_min if valve else None

    async def async_set_native_value(self, value: float) -> None:
        """Change the flow sensitivity.

        FloLogic silently discards a value below the valve's winter flow
        sensitivity, which the Web API cannot read. The library reports that
        as a command that was accepted and never applied, and its message
        says so.
        """
        coordinator = self.coordinator
        try:
            await coordinator.client.async_set_flow_sensitivity(self.vid, value)
        except FloLogicError as err:
            raise HomeAssistantError(
                translation_domain=coordinator.config_entry.domain,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        coordinator.async_set_updated_data(
            {**coordinator.data, **coordinator.client.valves}
        )
