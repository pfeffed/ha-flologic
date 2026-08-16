"""Coordinator holding one FloLogic account.

One coordinator per config entry, covering every valve on the account. The
alternative -- a coordinator per valve -- would open a cloud session per valve
and multiply the login load for no benefit, since a single ``RefreshValveArray``
already returns them all.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pyflologic import (
    Account,
    DeviceIdentity,
    FloLogicAuthError,
    FloLogicClient,
    FloLogicError,
    Valve,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

type FloLogicConfigEntry = ConfigEntry[FloLogicCoordinator]


class FloLogicCoordinator(DataUpdateCoordinator[Account]):
    """Keeps one account's valves up to date."""

    config_entry: FloLogicConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FloLogicConfigEntry,
        client: FloLogicClient,
        poll_interval: float,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            # Polling is a backstop, not the primary path: the client holds a
            # websocket open and pushes changes within about a second. The
            # interval only has to be short enough to notice a silently dead
            # session, which the keepalive already guards against.
            update_interval=timedelta(seconds=poll_interval),
        )
        self.client = client

    async def _async_setup(self) -> None:
        """Connect and load the account once, before the first refresh."""
        try:
            await self.client.async_connect()
        except FloLogicAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FloLogicError as err:
            raise UpdateFailed(str(err)) from err
        self.client.add_listener(self._handle_push)

    async def _async_update_data(self) -> Account:
        """Re-read the account."""
        try:
            await self.client.async_refresh()
        except FloLogicAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FloLogicError as err:
            raise UpdateFailed(str(err)) from err
        return self.client.account

    @callback
    def _handle_push(self, account: Account) -> None:
        """Publish a pushed account snapshot to the entities."""
        self.async_set_updated_data(account)

    async def async_shutdown(self) -> None:
        """Close the cloud session."""
        await super().async_shutdown()
        await self.client.async_disconnect()

    # --- helpers for entities -------------------------------------------

    def valve(self, valve_id: str) -> Valve | None:
        """Return one valve from the latest snapshot, if it is still present."""
        return self.data.valves.get(valve_id)

    @property
    def controllable_valve_ids(self) -> list[str]:
        """Return the IDs of every valve that can be commanded."""
        return list(self.data.controllable_valves)


def build_device_identity(name: str) -> DeviceIdentity:
    """Create a client-device identity for a new config entry."""
    return DeviceIdentity.generate(name)
