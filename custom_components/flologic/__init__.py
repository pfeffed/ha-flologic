"""The FloLogic integration.

One config entry is one FloLogic *account*, and every valve on it becomes a
device. Accounts routinely hold several valves -- and a G-Connect gateway
alongside them -- so anything that picks a single valve per entry leaves the
rest unreachable.
"""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyflologic import DEFAULT_POLL_INTERVAL, DeviceIdentity, FloLogicClient

from .const import (
    CONF_DEVICE_CODE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TOKEN,
    CONF_POLL_INTERVAL,
    PLATFORMS,
)
from .coordinator import FloLogicConfigEntry, FloLogicCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> bool:
    """Set up FloLogic from a config entry."""
    client = FloLogicClient(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        device=DeviceIdentity(
            name=entry.data[CONF_DEVICE_NAME],
            code=entry.data[CONF_DEVICE_CODE],
            token=entry.data[CONF_DEVICE_TOKEN],
        ),
        # Home Assistant's shared session, so the client never owns or closes
        # it; the library only closes a session it created itself.
        session=async_get_clientsession(hass),
    )

    coordinator = FloLogicCoordinator(
        hass,
        entry,
        client,
        entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> bool:
    """Unload a config entry.

    The cloud session is closed by the coordinator's own shutdown, which
    Home Assistant registers via ``async_on_unload`` when the entry is passed
    to ``DataUpdateCoordinator``. Closing it here as well disconnects twice
    per reload.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
