"""Base entity for FloLogic valves."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import FloLogicCoordinator
from .vendor.pyflologic import Valve


class FloLogicValveEntity(CoordinatorEntity[FloLogicCoordinator]):
    """An entity belonging to one valve on the account."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FloLogicCoordinator, valve: Valve, key: str
    ) -> None:
        """Initialize the entity against a valve."""
        super().__init__(coordinator)
        self._valve_id = valve.valve_id
        # Keyed on the hardware UUID, not the cloud's valve ID and certainly
        # not the name: the same valve is named differently to its owner and
        # to a shared user, so a name-derived ID would change identity with
        # the configured account.
        self._attr_unique_id = f"{valve.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, valve.unique_id)},
            manufacturer=MANUFACTURER,
            model=valve.model,
            name=valve.name,
            sw_version=valve.firmware_version,
            serial_number=valve.uuid,
            suggested_area=valve.network_name,
        )

    @property
    def valve(self) -> Valve | None:
        """Return this entity's valve from the latest snapshot."""
        return self.coordinator.valve(self._valve_id)

    @property
    def available(self) -> bool:
        """Return whether the cloud and the valve are both reachable.

        A valve dropping off the account entirely also counts: an entity for a
        valve that is no longer in the payload has nothing to report.
        """
        valve = self.valve
        return super().available and valve is not None and valve.is_online
