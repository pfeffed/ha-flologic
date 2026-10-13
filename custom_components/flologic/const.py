"""Constants for the FloLogic integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "flologic"

PLATFORMS: list[Platform] = [
    Platform.VALVE,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

MANUFACTURER = "FloLogic"

CONFIG_VERSION = 2
UNOFFICIAL_CONFIG_VERSION = 1
"""Entries the app-protocol integration created while it owned this domain.

Until 0.5.0 that integration was ``flologic``; it is now
``flologic_unofficial``. Its entries hold an email and password, which this
integration cannot use, so they are refused at migration with a repair issue.
"""

# --- config entry data -------------------------------------------------------

CONF_COMPANY_ID = "company_id"
CONF_WEBHOOK_SECRET = "webhook_secret"
"""The signing secret from FloLogic's Dashboard > API Manager.

Optional at setup, required for callbacks: an unsigned callback could be sent
by anyone who learned the URL, and these ones announce shutoffs.
"""

CONF_CALLBACK_URL = "callback_url"
"""The callback URL as registered with FloLogic, placeholders and all.

Stored because it is half of what signature verification needs: FloLogic
signs the URL it requested, and the relay that delivers it here changes the
host, so the registered template is the only record of what was signed.
"""

CONF_CLOUDHOOK = "cloudhook"
"""Whether the webhook was exposed through a Home Assistant Cloud cloudhook."""

# --- options -----------------------------------------------------------------

CONF_POLL_INTERVAL = "poll_interval"
CONF_USE_CALLBACKS = "use_callbacks"

# --- events ------------------------------------------------------------------

EVENT_CALLBACK = f"{DOMAIN}_event"
"""Fired on the bus for every verified callback, for automations."""

SIGNAL_CALLBACK = f"{DOMAIN}_callback_{{entry_id}}"
"""Dispatcher signal carrying a verified callback to the event entities."""
