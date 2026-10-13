"""Sensors for FloLogic valves.

Besides live state, the settings the Web API reports but cannot change --
flow limits, bypass duration, temperature thresholds, pre-alert notice -- are
sensors, under the diagnostic category: they are worth seeing, but there is
nothing here to set them with.
"""

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
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity
from .vendor.pyflologic import (
    PROBLEM_PRIORITY,
    FlowState,
    ShutoffReason,
    Valve,
    ValveMode,
)

PARALLEL_UPDATES = 0
"""Unlimited: reads come from the coordinator's snapshot."""

NONE = "none"
"""Explicit "nothing wrong" rather than an empty state.

An enum sensor that goes unknown when healthy cannot be told apart from one
that is broken, and "no shutoff reason" is a fact worth stating.
"""


@dataclass(frozen=True, kw_only=True)
class FloLogicSensorDescription(SensorEntityDescription):
    """Describes a FloLogic sensor."""

    value_fn: Callable[[Valve], Any]


def _limit(
    description_key: str, translation_key: str, fn: Callable[[Valve], Any]
) -> FloLogicSensorDescription:
    """Describe a read-only setting measured in minutes."""
    return FloLogicSensorDescription(
        key=description_key,
        translation_key=translation_key,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=fn,
    )


def _threshold(
    description_key: str, fn: Callable[[Valve], Any]
) -> FloLogicSensorDescription:
    """Describe a read-only temperature threshold."""
    return FloLogicSensorDescription(
        key=description_key,
        translation_key=description_key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=fn,
    )


SENSORS: tuple[FloLogicSensorDescription, ...] = (
    FloLogicSensorDescription(
        key="shutoff_reason",
        translation_key="shutoff_reason",
        device_class=SensorDeviceClass.ENUM,
        options=[NONE, *(reason.value for reason in ShutoffReason)],
        value_fn=lambda valve: (
            valve.shutoff_reason.value if valve.shutoff_reason else NONE
        ),
    ),
    FloLogicSensorDescription(
        key="problem",
        translation_key="problem",
        device_class=SensorDeviceClass.ENUM,
        options=[NONE, *(flag.name.lower() for flag in PROBLEM_PRIORITY if flag.name)],
        value_fn=lambda valve: (
            valve.problem.name.lower() if valve.problem and valve.problem.name else NONE
        ),
    ),
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
        key="flow_state",
        translation_key="flow_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.name.lower() for state in FlowState],
        value_fn=lambda valve: (
            valve.flow_state.name.lower() if valve.flow_state else None
        ),
    ),
    FloLogicSensorDescription(
        key="last_flow_change",
        translation_key="last_flow_change",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda valve: valve.last_flow_change,
    ),
    FloLogicSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda valve: valve.temperature_f,
    ),
    _limit("home_limit", "home_limit", lambda valve: valve.home_limit_minutes),
    # Zero is documented as "water off": Away allows no flow at all.
    _limit("away_limit", "away_limit", lambda valve: valve.away_limit_minutes),
    # Unknown while the bypass timer is off, which the binary sensor states.
    _limit("bypass_duration", "bypass_duration", lambda valve: valve.bypass_minutes),
    _limit("pre_alert", "pre_alert", lambda valve: valve.pre_alert_minutes),
    # FloLogic documents both thresholds as including the device's
    # temperature offset, which the Web API does not report separately.
    _threshold("low_temp_alert", lambda valve: valve.low_temp_alert_f),
    _threshold("low_temp_shutoff", lambda valve: valve.low_temp_shutoff_f),
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
    """Set up sensors for every valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicSensor(coordinator, valve, description)
        for valve in coordinator.data.values()
        for description in SENSORS
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
            "unknown_bits": valve.mode.unknown_bits or None,
            "control_mode": valve.control_mode.value if valve.control_mode else None,
        }
