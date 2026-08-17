"""The FloLogic integration.

One config entry is one FloLogic *account*, and every valve on it becomes a
device. Accounts routinely hold several valves -- and a G-Connect gateway
alongside them -- so anything that picks a single valve per entry leaves the
rest unreachable.
"""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_DEVICE_CODE,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TOKEN,
    CONF_ENABLED_DEFAULTS_VERSION,
    CONF_POLL_INTERVAL,
    DOMAIN,
    ENABLED_DEFAULTS_VERSION,
    PLATFORMS,
)
from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .vendor.pyflologic import DEFAULT_POLL_INTERVAL, DeviceIdentity, FloLogicClient


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
    _async_apply_enabled_defaults(hass, entry)
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


@callback
def _async_apply_enabled_defaults(
    hass: HomeAssistant, entry: FloLogicConfigEntry
) -> None:
    """Re-enable entities that have since become enabled by default.

    Only those this integration disabled are touched. A user who switched
    something off deliberately is recorded as `disabled_by == USER`, and
    overriding that would be taking a decision back off them.
    """
    if entry.data.get(CONF_ENABLED_DEFAULTS_VERSION) == ENABLED_DEFAULTS_VERSION:
        return

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.disabled_by is not er.RegistryEntryDisabler.INTEGRATION:
            continue
        if entity.entity_id.endswith("_signal_strength"):
            registry.async_update_entity(entity.entity_id, disabled_by=None)

    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_ENABLED_DEFAULTS_VERSION: ENABLED_DEFAULTS_VERSION},
    )


async def _async_reload_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    device: DeviceEntry,
) -> bool:
    """Allow deleting a device only once its valve has left the account.

    Valves get sold, replaced and un-shared, and the stale device would
    otherwise sit in the registry forever. Refusing while the valve is still
    present matters just as much: deleting a live valve's device removes the
    only control for a water shutoff, and it would silently come back on the
    next reload anyway.
    """
    del hass
    known = {valve.unique_id for valve in entry.runtime_data.data.valves.values()}
    return not any(
        identifier[1] in known
        for identifier in device.identifiers
        if identifier[0] == DOMAIN
    )
