"""Binary sensors for FloLogic valves.

Whether the water is off is the valve entity's job, and *why* belongs to the
shutoff-reason and problem sensors. What remains here are the genuinely
yes-or-no facts the Web API reports.
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

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity
from .vendor.pyflologic import Valve

PARALLEL_UPDATES = 0
"""Unlimited: reads come from the coordinator's snapshot."""


@dataclass(frozen=True, kw_only=True)
class FloLogicBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a FloLogic binary sensor."""

    value_fn: Callable[[Valve], bool | None]
    # True for sensors that must keep reporting while the valve is offline,
    # which is precisely when a connectivity sensor is worth having.
    survives_offline: bool = False


def _setting(key: str, fn: Callable[[Valve], bool]) -> FloLogicBinarySensorDescription:
    """Describe a read-only on/off setting."""
    return FloLogicBinarySensorDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=fn,
    )


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
    _setting("bypass_timer", lambda valve: valve.bypass_enabled),
    _setting("low_temp_alert_enabled", lambda valve: valve.low_temp_alert_enabled),
    _setting("low_temp_shutoff_enabled", lambda valve: valve.low_temp_shutoff_enabled),
    _setting("away_water_off", lambda valve: valve.away_turns_water_off),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors for every valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicBinarySensor(coordinator, valve, description)
        for valve in coordinator.data.values()
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

        The connectivity sensor ignores the valve's own reachability;
        inheriting the usual rule would take it unavailable at exactly the
        moment it has something to say.
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
