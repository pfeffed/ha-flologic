"""Base entity for FloLogic valves."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import FloLogicCoordinator
from .vendor.pyflologic import DeviceType, Valve

MODEL_NAMES = {
    DeviceType.WIFI_CONNECT: "WiFi Connect",
    DeviceType.G_CONNECT: "G-Connect",
}


class FloLogicValveEntity(CoordinatorEntity[FloLogicCoordinator]):
    """An entity belonging to one valve."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FloLogicCoordinator, valve: Valve, key: str
    ) -> None:
        """Initialize the entity against a valve."""
        super().__init__(coordinator)
        self._vid = valve.vid
        # The VID is the hardware identity -- the same value the app protocol
        # calls uuid -- so it survives a change of credentials.
        self._attr_unique_id = f"{valve.vid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, valve.vid)},
            manufacturer=MANUFACTURER,
            model=(
                MODEL_NAMES.get(valve.device_type)
                if valve.device_type
                else valve.device_type_raw
            ),
            # The Web API does not return the name the owner gave the valve,
            # and the address is shared by every valve in a house. The VID is
            # unique and printed on the device; rename it here.
            name=f"FloLogic {valve.vid}",
            serial_number=valve.vid,
        )

    @property
    def vid(self) -> str:
        """Return the VID of this entity's valve."""
        return self._vid

    @property
    def valve(self) -> Valve | None:
        """Return this entity's valve from the latest snapshot."""
        return self.coordinator.valve(self._vid)

    @property
    def available(self) -> bool:
        """Return whether the cloud and the valve are both reachable."""
        valve = self.valve
        return super().available and valve is not None and valve.is_online
