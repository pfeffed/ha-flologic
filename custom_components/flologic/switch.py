"""Switches for the valve settings FloLogic toggles by negating.

Each of these is half of a pair: the switch carries the sign of a single wire
field and the matching number carries its magnitude. They are separate
entities because that is how the app presents them -- an off toggle beside the
value it would use if switched back on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from pyflologic import FloLogicError, ToggledSetting, ToggledSettingName, Valve

from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .entity import FloLogicValveEntity

PARALLEL_UPDATES = 0
"""Unlimited: every read comes from the coordinator's single snapshot, and the
library serializes writes onto one connection regardless of what is asked for
here."""


@dataclass(frozen=True, kw_only=True)
class FloLogicSwitchDescription(SwitchEntityDescription):
    """Describes one sign-encoded valve setting."""

    setting: ToggledSettingName
    value_fn: Callable[[Valve], ToggledSetting]


SWITCHES: tuple[FloLogicSwitchDescription, ...] = (
    FloLogicSwitchDescription(
        key="auto_away",
        translation_key="auto_away",
        entity_category=EntityCategory.CONFIG,
        setting=ToggledSettingName.AUTO_AWAY,
        value_fn=lambda valve: valve.auto_away,
    ),
    FloLogicSwitchDescription(
        key="delay_away",
        translation_key="delay_away",
        entity_category=EntityCategory.CONFIG,
        setting=ToggledSettingName.DELAY_AWAY,
        value_fn=lambda valve: valve.delay_away,
    ),
    FloLogicSwitchDescription(
        key="winter_mode",
        translation_key="winter_mode",
        entity_category=EntityCategory.CONFIG,
        setting=ToggledSettingName.WINTER_FLOW_SENSITIVITY,
        value_fn=lambda valve: valve.winter_flow_sensitivity,
    ),
    FloLogicSwitchDescription(
        key="low_temp_alert",
        translation_key="low_temp_alert",
        entity_category=EntityCategory.CONFIG,
        setting=ToggledSettingName.LOW_TEMP_ALERT,
        value_fn=lambda valve: valve.low_temp_alert,
    ),
    FloLogicSwitchDescription(
        key="low_temp_shutoff",
        translation_key="low_temp_shutoff",
        entity_category=EntityCategory.CONFIG,
        setting=ToggledSettingName.LOW_TEMP_SHUTOFF,
        value_fn=lambda valve: valve.low_temp_shutoff,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up setting switches for every controllable valve."""
    del hass
    coordinator = entry.runtime_data
    async_add_entities(
        FloLogicSettingSwitch(coordinator, valve, description)
        for valve in coordinator.data.controllable_valves.values()
        for description in SWITCHES
    )


class FloLogicSettingSwitch(FloLogicValveEntity, SwitchEntity):
    """Turns one sign-encoded setting on or off."""

    entity_description: FloLogicSwitchDescription

    def __init__(
        self,
        coordinator: FloLogicCoordinator,
        valve: Valve,
        description: FloLogicSwitchDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, valve, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the setting is switched on."""
        valve = self.valve
        if valve is None:
            return None
        return self.entity_description.value_fn(valve).enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the value the setting would use when on.

        Kept visible while off, because that is the value the user configured
        and it survives being switched off.
        """
        valve = self.valve
        if valve is None:
            return None
        return {"configured_value": self.entity_description.value_fn(valve).configured}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the setting on, keeping its configured value."""
        del kwargs
        await self._async_set(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the setting off, keeping its configured value."""
        del kwargs
        await self._async_set(enabled=False)

    async def _async_set(self, *, enabled: bool) -> None:
        """Write the new sign, leaving the magnitude alone."""
        try:
            await self.coordinator.client.async_set_toggled_setting(
                self._valve_id, self.entity_description.setting, enabled=enabled
            )
        except FloLogicError as err:
            raise HomeAssistantError(
                translation_domain=self.coordinator.config_entry.domain,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.coordinator.async_set_updated_data(self.coordinator.client.account)
