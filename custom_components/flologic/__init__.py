"""The FloLogic integration, built on FloLogic's official Web API.

One config entry is one set of API credentials -- with an API key, the whole
company -- and every valve it can see becomes a device.
"""

from __future__ import annotations

import logging

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .callbacks import (
    CallbackUnavailableError,
    async_start_callbacks,
    async_stop_callbacks,
)
from .const import (
    CONF_CALLBACK_URL,
    CONF_CLOUDHOOK,
    CONF_COMPANY_ID,
    CONF_POLL_INTERVAL,
    CONF_USE_CALLBACKS,
    DOMAIN,
    PLATFORMS,
    UNOFFICIAL_CONFIG_VERSION,
)
from .coordinator import FloLogicConfigEntry, FloLogicCoordinator
from .vendor.pyflologic import (
    DEFAULT_POLL_INTERVAL,
    ApiKeyAuth,
    FloLogicClient,
    FloLogicError,
)

_LOGGER = logging.getLogger(__name__)


def build_client(hass: HomeAssistant, entry: FloLogicConfigEntry) -> FloLogicClient:
    """Return a client for an entry's credentials."""
    return FloLogicClient(
        ApiKeyAuth(entry.data[CONF_API_KEY], int(entry.data[CONF_COMPANY_ID])),
        # Home Assistant's shared session, which the client never closes.
        session=async_get_clientsession(hass),
    )


async def async_setup_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> bool:
    """Set up FloLogic from a config entry."""
    client = build_client(hass, entry)
    coordinator = FloLogicCoordinator(
        hass,
        entry,
        client,
        entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Callbacks change entry data, so this runs before the update listener
    # is registered; otherwise every start would reload itself.
    if entry.options.get(CONF_USE_CALLBACKS):
        try:
            await async_start_callbacks(hass, entry, client)
        except (CallbackUnavailableError, FloLogicError) as err:
            # Polling still protects the house; losing callbacks only makes
            # updates slower, so this must not fail the whole entry.
            _LOGGER.warning("FloLogic callbacks unavailable, polling only: %s", err)
    elif entry.data.get(CONF_CALLBACK_URL):
        await async_stop_callbacks(hass, entry, client)
        hass.config_entries.async_update_entry(
            entry,
            data={
                key: value
                for key, value in entry.data.items()
                if key not in {CONF_CALLBACK_URL, CONF_CLOUDHOOK}
            },
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> bool:
    """Unload a config entry.

    The callback stays registered with FloLogic across a reload or restart;
    deliveries in between reach a webhook nobody is listening on, which Home
    Assistant answers and ignores. It is withdrawn when the entry is removed.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> None:
    """Withdraw this entry's callback from FloLogic when the entry is deleted."""
    if CONF_API_KEY in entry.data and entry.data.get(CONF_CALLBACK_URL):
        client = build_client(hass, entry)
        await async_stop_callbacks(hass, entry, client)


async def _async_reload_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: FloLogicConfigEntry) -> bool:
    """Refuse entries left behind by the unofficial integration.

    Until 0.5.0 the app-protocol integration used this domain, with an email
    and password where this one needs an API key. Nothing can be carried
    over, so instead of failing obscurely the entry is refused with a repair
    issue explaining what to do.
    """
    if entry.version == UNOFFICIAL_CONFIG_VERSION:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"unofficial_entry_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="unofficial_entry",
            translation_placeholders={"title": entry.title},
        )
        _LOGGER.error(
            "Config entry %r was created by the unofficial FloLogic integration, "
            "which now uses the flologic_unofficial domain. Remove it and add "
            "FloLogic (Unofficial) or FloLogic again",
            entry.title,
        )
        return False
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: FloLogicConfigEntry,
    device: DeviceEntry,
) -> bool:
    """Allow deleting a device only once its valve has left the account.

    Refusing while the valve is still present matters: deleting a live
    valve's device removes the only control for a water shutoff, and it would
    come back on the next reload anyway.
    """
    del hass
    known = set(entry.runtime_data.data or {})
    return not any(
        identifier[1] in known
        for identifier in device.identifiers
        if identifier[0] == DOMAIN
    )
