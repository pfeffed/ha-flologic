"""Binary sensors for FloLogic valves.

Only two things about a valve are genuinely yes-or-no. Whether the water is
off is the valve entity's job, and *why* it is off -- or what else is wrong --
belongs to the shutoff-reason and problem sensors, which name the specific
condition instead of flattening every cause into one "Problem".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyflologic import Valve

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity

PARALLEL_UPDATES = 0
"""Unlimited: every read comes from the coordinator's single snapshot."""


@dataclass(frozen=True, kw_only=True)
class FloLogicBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a FloLogic binary sensor."""

    value_fn: Callable[[Valve], bool | None]
    # True for sensors that must keep reporting while the valve is unreachable,
    # which is precisely when a connectivity sensor is worth having.
    survives_offline: bool = False


BINARY_SENSORS: tuple[FloLogicBinarySensorDescription, ...] = (
    FloLogicBinarySensorDescription(
        key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda valve: valve.is_online,
        survives_offline=True,
    ),
    FloLogicBinarySensorDescription(
        key="water_flowing",
        translation_key="water_flowing",
        value_fn=lambda valve: valve.is_water_flowing,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors for every controllable valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicBinarySensor(coordinator, valve, description)
        for valve in coordinator.data.controllable_valves.values()
        for description in BINARY_SENSORS
    )


class FloLogicBinarySensor(FloLogicValveEntity, BinarySensorEntity):
    """A single yes-or-no condition of a valve."""

    entity_description: FloLogicBinarySensorDescription

    def __init__(
        self,
        coordinator: FloLogicCoordinator,
        valve: Valve,
        description: FloLogicBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, valve, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return whether the sensor can report.

        The connectivity sensor deliberately ignores the valve's own
        reachability. Inheriting the usual rule would take it unavailable at
        exactly the moment it has something to say.
        """
        if self.entity_description.survives_offline:
            return self.coordinator.last_update_success and self.valve is not None
        return super().available

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        valve = self.valve
        if valve is None:
            return None
        return self.entity_description.value_fn(valve)
