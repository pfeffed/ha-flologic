"""Writable valve settings.

Two kinds live here. Plain settings are a single positive number on the wire.
Sign-encoded ones -- Auto Away, Delay Away, Winter Mode and the temperature
thresholds -- pack a switch into the sign, so each is a pair: the number here
carries the magnitude and the matching switch carries the sign.

The magnitude stays visible and writable while the setting is switched off,
because FloLogic keeps it and the app shows it. Writing one does not turn the
setting on.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity
from .sensor import OUNCES_PER_MINUTE
from .vendor.pyflologic import (
    FloLogicClient,
    FloLogicError,
    FloLogicValidationError,
    ToggledSettingName,
    Valve,
)

PARALLEL_UPDATES = 0
"""Unlimited: every read comes from the coordinator's single snapshot, and the
library serializes writes onto one connection regardless of what is asked for
here."""


type Setter = Callable[[FloLogicClient, str, float], Coroutine[Any, Any, None]]


@dataclass(frozen=True, kw_only=True)
class FloLogicNumberDescription(NumberEntityDescription):
    """Describes a writable FloLogic setting."""

    value_fn: Callable[[Valve], float | None]
    set_fn: Setter


def _toggled_setter(setting: ToggledSettingName) -> Setter:
    """Return a setter that changes a sign-encoded setting's magnitude only."""

    def _set(client: FloLogicClient, valve_id: str, value: float) -> Any:
        return client.async_set_toggled_setting(valve_id, setting, value=value)

    return _set


NUMBERS: tuple[FloLogicNumberDescription, ...] = (
    FloLogicNumberDescription(
        key="home_limit",
        translation_key="home_limit",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=1,
        native_max_value=1440,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.home_limit_minutes,
        set_fn=lambda client, valve_id, value: client.async_update_settings(
            valve_id, home_limit_minutes=value
        ),
    ),
    FloLogicNumberDescription(
        key="away_limit",
        translation_key="away_limit",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        # Sub-minute limits are normal here: a real valve runs 0.5, which the
        # app displays as "6 seconds"... at 0.1. Minutes is the wire unit.
        native_min_value=0.1,
        native_max_value=1440,
        native_step=0.1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.away_limit_minutes,
        set_fn=lambda client, valve_id, value: client.async_update_settings(
            valve_id, away_limit_minutes=value
        ),
    ),
    FloLogicNumberDescription(
        key="bypass_time",
        translation_key="bypass_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=1,
        native_max_value=1440,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.bypass_minutes,
        set_fn=lambda client, valve_id, value: client.async_update_settings(
            valve_id, bypass_minutes=value
        ),
    ),
    FloLogicNumberDescription(
        key="flow_sensitivity",
        translation_key="flow_sensitivity",
        native_unit_of_measurement=OUNCES_PER_MINUTE,
        native_min_value=0.1,
        native_max_value=200,
        native_step=0.1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.flow_sensitivity_oz_per_min,
        set_fn=lambda client, valve_id, value: client.async_update_settings(
            valve_id, flow_sensitivity_oz_per_min=value
        ),
    ),
    FloLogicNumberDescription(
        key="pre_alert",
        translation_key="pre_alert",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=0,
        native_max_value=60,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.pre_alert_minutes,
        set_fn=lambda client, valve_id, value: client.async_update_settings(
            valve_id, pre_alert_minutes=value
        ),
    ),
    FloLogicNumberDescription(
        key="no_flow_notice",
        translation_key="no_flow_notice",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=0,
        native_max_value=86400,
        native_step=60,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.no_flow_notice_seconds,
        set_fn=lambda client, valve_id, value: client.async_update_settings(
            valve_id, no_flow_notice_seconds=value
        ),
    ),
    FloLogicNumberDescription(
        key="temperature_offset",
        translation_key="temperature_offset",
        # Deliberately no temperature device class. Home Assistant would
        # convert this the way it converts a temperature -- 5 F becoming
        # -15 C -- but an offset is a *difference*, which converts by ratio
        # alone. There is no device class for a temperature difference, so
        # the value is shown in FloLogic's own units and left uncoverted,
        # which is at least never wrong.
        native_unit_of_measurement="°F",
        native_min_value=-20,
        native_max_value=20,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.temperature_offset_f,
        set_fn=lambda client, valve_id, value: client.async_update_settings(
            valve_id, temperature_offset_f=value
        ),
    ),
    FloLogicNumberDescription(
        key="guest_flow_limit",
        translation_key="guest_flow_limit",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=0.1,
        native_max_value=1440,
        native_step=0.1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.guest_flow_limit.configured,
        set_fn=_toggled_setter(ToggledSettingName.GUEST_FLOW_LIMIT),
    ),
    FloLogicNumberDescription(
        key="auto_away_hours",
        translation_key="auto_away_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        native_min_value=1,
        native_max_value=336,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.auto_away.configured,
        set_fn=_toggled_setter(ToggledSettingName.AUTO_AWAY),
    ),
    FloLogicNumberDescription(
        key="delay_away_minutes",
        translation_key="delay_away_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=1,
        native_max_value=1440,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.delay_away.configured,
        set_fn=_toggled_setter(ToggledSettingName.DELAY_AWAY),
    ),
    FloLogicNumberDescription(
        key="winter_flow_sensitivity",
        translation_key="winter_flow_sensitivity",
        native_unit_of_measurement=OUNCES_PER_MINUTE,
        native_min_value=0.1,
        native_max_value=200,
        native_step=0.1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.winter_flow_sensitivity.configured,
        set_fn=_toggled_setter(ToggledSettingName.WINTER_FLOW_SENSITIVITY),
    ),
    FloLogicNumberDescription(
        key="low_temp_alert_f",
        translation_key="low_temp_alert_f",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.low_temp_alert.configured,
        set_fn=_toggled_setter(ToggledSettingName.LOW_TEMP_ALERT),
    ),
    FloLogicNumberDescription(
        key="low_temp_shutoff_f",
        translation_key="low_temp_shutoff_f",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda valve: valve.low_temp_shutoff.configured,
        set_fn=_toggled_setter(ToggledSettingName.LOW_TEMP_SHUTOFF),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up settings numbers for every controllable valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicNumber(coordinator, valve, description)
        for valve in coordinator.data.controllable_valves.values()
        for description in NUMBERS
    )


class FloLogicNumber(FloLogicValveEntity, NumberEntity):
    """One writable valve setting."""

    entity_description: FloLogicNumberDescription

    def __init__(
        self,
        coordinator: FloLogicCoordinator,
        valve: Valve,
        description: FloLogicNumberDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, valve, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the current setting."""
        valve = self.valve
        if valve is None:
            return None
        return self.entity_description.value_fn(valve)

    async def async_set_native_value(self, value: float) -> None:
        """Write the setting back to FloLogic."""
        try:
            await self.entity_description.set_fn(
                self.coordinator.client, self._valve_id, value
            )
        except FloLogicValidationError as err:
            # A value FloLogic would accept and then silently discard. Saying
            # exactly why beats a generic failure the user cannot act on.
            raise ServiceValidationError(
                translation_domain=self.coordinator.config_entry.domain,
                translation_key="invalid_setting",
                translation_placeholders={"error": str(err)},
            ) from err
        except FloLogicError as err:
            raise HomeAssistantError(
                translation_domain=self.coordinator.config_entry.domain,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.coordinator.async_set_updated_data(self.coordinator.client.account)
