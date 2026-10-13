"""Receiving FloLogic callbacks through a Home Assistant webhook.

FloLogic's callbacks belong to the *company*, not to a user, and the API-key
flow makes the key holder that company. So a self-hosted install can register
its own callback -- something the per-client model rules out for OAuth -- as
long as FloLogic can reach it. That means a Home Assistant Cloud cloudhook,
which needs no open port, or failing that the instance's external URL.

The company's callback list is shared with every other consumer of the key
(FloLogic seeds test entries of its own), so this only ever adds and removes
its own URL, never the list as a whole.

FloLogic calls the URL with GET and signs ``<timestamp>.<exact URL>``. The
cloud relay delivers it from a different host, so verification rebuilds the
signed URL from the registered template and the raw query string, which the
relay passes through untouched.
"""

from __future__ import annotations

import logging
import time
from contextlib import suppress

from aiohttp import web
from aiohttp.hdrs import METH_GET
from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError

from .const import CONF_CALLBACK_URL, CONF_CLOUDHOOK, CONF_WEBHOOK_SECRET, DOMAIN
from .coordinator import FloLogicConfigEntry
from .vendor.pyflologic import (
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    CallbackDefinition,
    FloLogicClient,
    FloLogicError,
    FloLogicSignatureError,
    build_callback_url,
    callback_url_candidates,
    verify_callback,
)

_LOGGER = logging.getLogger(__name__)

_WARN_INTERVAL = 300.0
"""Seconds between repeated warnings about rejected callbacks."""


class CallbackUnavailableError(HomeAssistantError):
    """There is no URL FloLogic could reach this instance on."""


# Home Assistant Cloud is imported only when it is loaded: it is an optional
# after-dependency, and importing it pulls in Alexa, Google Assistant and the
# camera stack along with it.


def _cloud_active(hass: HomeAssistant) -> bool:
    """Return whether a Home Assistant Cloud subscription is active."""
    if "cloud" not in hass.config.components:
        return False
    from homeassistant.components import cloud  # noqa: PLC0415

    return cloud.async_active_subscription(hass)


async def _async_cloudhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """Return the cloudhook URL for ``webhook_id``, creating it if needed."""
    from homeassistant.components import cloud  # noqa: PLC0415

    try:
        return await cloud.async_get_or_create_cloudhook(hass, webhook_id)
    except cloud.CloudNotConnected as err:
        raise CallbackUnavailableError("Home Assistant Cloud is not connected") from err


async def _async_delete_cloudhook(hass: HomeAssistant, webhook_id: str) -> None:
    """Delete the cloudhook for ``webhook_id``, if Cloud is still around."""
    if "cloud" not in hass.config.components:
        return
    from homeassistant.components import cloud  # noqa: PLC0415

    with suppress(cloud.CloudNotAvailable):
        await cloud.async_delete_cloudhook(hass, webhook_id)


def can_receive_callbacks(hass: HomeAssistant) -> bool:
    """Return whether FloLogic could reach this instance at all."""
    if _cloud_active(hass):
        return True
    try:
        webhook.async_generate_url(
            hass, "probe", allow_internal=False, allow_ip=False, prefer_external=True
        )
    except NoURLAvailableError:
        return False
    return True


async def _async_public_url(hass: HomeAssistant, webhook_id: str) -> tuple[str, bool]:
    """Return a URL FloLogic can call, and whether it is a cloudhook."""
    if _cloud_active(hass):
        return await _async_cloudhook_url(hass, webhook_id), True
    try:
        url = webhook.async_generate_url(
            hass, webhook_id, allow_internal=False, allow_ip=False, prefer_external=True
        )
    except NoURLAvailableError as err:
        raise CallbackUnavailableError(
            "no external URL is configured and Home Assistant Cloud is not active"
        ) from err
    return url, False


async def async_start_callbacks(
    hass: HomeAssistant, entry: FloLogicConfigEntry, client: FloLogicClient
) -> None:
    """Expose the webhook and make sure FloLogic will call it.

    Writes to FloLogic only when the registered URL is missing or has
    changed, so an ordinary restart costs one read of the callback list.
    """
    webhook_id = entry.data.get(CONF_WEBHOOK_ID) or webhook.async_generate_id()
    url, is_cloudhook = await _async_public_url(hass, webhook_id)
    registered = build_callback_url(url)

    previous = entry.data.get(CONF_CALLBACK_URL)
    if previous and previous != registered:
        await client.async_remove_callbacks(previous)
    await client.async_add_callback(CallbackDefinition(registered))

    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_WEBHOOK_ID: webhook_id,
            CONF_CALLBACK_URL: registered,
            CONF_CLOUDHOOK: is_cloudhook,
        },
    )
    receiver = _Receiver(entry, registered)
    webhook.async_register(
        hass,
        DOMAIN,
        entry.title,
        webhook_id,
        receiver.async_handle,
        allowed_methods=[METH_GET],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))


async def async_stop_callbacks(
    hass: HomeAssistant, entry: FloLogicConfigEntry, client: FloLogicClient
) -> None:
    """Withdraw this entry's callback from FloLogic and drop the cloudhook.

    Best effort: the entry is going away or callbacks are being switched off,
    and neither should be blocked by FloLogic being unreachable. A callback
    left behind only produces requests to a webhook nobody is listening on.
    """
    registered = entry.data.get(CONF_CALLBACK_URL)
    if registered:
        try:
            await client.async_remove_callbacks(registered)
        except FloLogicError as err:
            _LOGGER.warning("Could not remove the FloLogic callback: %s", err)
    if entry.data.get(CONF_CLOUDHOOK) and entry.data.get(CONF_WEBHOOK_ID):
        await _async_delete_cloudhook(hass, entry.data[CONF_WEBHOOK_ID])


class _Receiver:
    """Verifies callback deliveries and hands them to the coordinator."""

    def __init__(self, entry: FloLogicConfigEntry, registered_url: str) -> None:
        """Bind to one entry and the URL it registered."""
        self._entry = entry
        self._registered_url = registered_url
        self._last_warning = 0.0

    async def async_handle(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Verify one delivery and act on it.

        Answers 200 whether or not the delivery verifies, as Home Assistant's
        own webhook handling does for unknown hooks: a sender learns nothing
        about which of its guesses are close.
        """
        del hass, webhook_id
        secret = self._entry.data.get(CONF_WEBHOOK_SECRET)
        if not secret:
            self._warn("a callback arrived but no signing secret is configured")
            return web.Response(status=200)
        try:
            event = verify_callback(
                secret, self._registered_url, request.query_string, request.headers
            )
        except FloLogicSignatureError as err:
            self._warn(f"rejected a callback: {err}")
            # None of this is secret, and it is the only way to tell which
            # URL FloLogic actually signed if verification ever disagrees.
            _LOGGER.debug(
                "Rejected callback: timestamp=%s signature=%s candidates=%s",
                request.headers.get(HEADER_TIMESTAMP),
                request.headers.get(HEADER_SIGNATURE),
                callback_url_candidates(self._registered_url, request.query_string),
            )
            return web.Response(status=200)

        _LOGGER.debug("FloLogic callback: %s", event)
        coordinator = getattr(self._entry, "runtime_data", None)
        if coordinator is not None:
            coordinator.async_handle_callback(event)
        return web.Response(status=200)

    def _warn(self, message: str) -> None:
        """Log a rejected delivery, without letting a flood fill the log."""
        now = time.monotonic()
        if now - self._last_warning >= _WARN_INTERVAL:
            self._last_warning = now
            _LOGGER.warning("FloLogic %s", message)
        else:
            _LOGGER.debug("FloLogic %s", message)
