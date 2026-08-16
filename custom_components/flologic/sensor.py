"""Sensors for FloLogic valves."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyflologic import ControlMode, Valve, ValveMode

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity

OUNCES_PER_MINUTE = "oz/min"
"""FloLogic's own unit, kept rather than converted.

Home Assistant has no ounces-per-minute member of its volume-flow-rate class,
and converting to gallons would put a number on screen that does not match the
one in the FloLogic app for the same reading.
"""


@dataclass(frozen=True, kw_only=True)
class FloLogicSensorDescription(SensorEntityDescription):
    """Describes a FloLogic sensor."""

    value_fn: Callable[[Valve], Any]
    exists_fn: Callable[[Valve], bool] = lambda _valve: True


SENSORS: tuple[FloLogicSensorDescription, ...] = (
    FloLogicSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(
            {flag.name.lower() for flag in ValveMode if flag.name} | {"unknown"}
        ),
        value_fn=lambda valve: valve.status,
    ),
    FloLogicSensorDescription(
        key="current_flow",
        translation_key="current_flow",
        native_unit_of_measurement=OUNCES_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda valve: valve.current_flow_oz_per_min,
    ),
    FloLogicSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda valve: valve.temperature_f,
    ),
    FloLogicSensorDescription(
        key="shutoff_countdown",
        translation_key="shutoff_countdown",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda valve: valve.shutoff_countdown_seconds(),
    ),
    FloLogicSensorDescription(
        key="flow_elapsed",
        translation_key="flow_elapsed",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_registry_enabled_default=False,
        value_fn=lambda valve: valve.flow_elapsed_seconds(),
    ),
    FloLogicSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda valve: valve.battery_percent,
        # Two of three real valves report a power of two here rather than a
        # percentage, and the app shows no battery for them at all. Creating
        # the entity only where the value is plausible avoids a permanently
        # unknown battery sensor on hardware that has no such reading.
        exists_fn=lambda valve: valve.battery_percent is not None,
    ),
    FloLogicSensorDescription(
        key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda valve: valve.signal_strength_dbm,
    ),
    FloLogicSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda valve: valve.last_seen,
    ),
    FloLogicSensorDescription(
        key="flow_sensitivity",
        translation_key="flow_sensitivity",
        native_unit_of_measurement=OUNCES_PER_MINUTE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda valve: valve.flow_sensitivity_oz_per_min,
    ),
    FloLogicSensorDescription(
        key="current_flow_limit",
        translation_key="current_flow_limit",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda valve: valve.current_flow_limit_minutes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for every controllable valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicSensor(coordinator, valve, description)
        for valve in coordinator.data.controllable_valves.values()
        for description in SENSORS
        if description.exists_fn(valve)
    )


class FloLogicSensor(FloLogicValveEntity, SensorEntity):
    """A single readable value from a valve."""

    entity_description: FloLogicSensorDescription

    def __init__(
        self,
        coordinator: FloLogicCoordinator,
        valve: Valve,
        description: FloLogicSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, valve, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        valve = self.valve
        if valve is None:
            return None
        return self.entity_description.value_fn(valve)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the decoded mode bits alongside the headline status."""
        if self.entity_description.key != "status":
            return None
        valve = self.valve
        if valve is None:
            return None
        return {
            "raw_mode": int(valve.mode),
            "active_flags": [name.lower() for name in valve.mode.flag_names],
            "control_mode": (
                valve.control_mode.value
                if isinstance(valve.control_mode, ControlMode)
                else None
            ),
        }
