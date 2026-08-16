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
    Platform.SWITCH,
]

# --- config entry data -------------------------------------------------------

CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_CODE = "device_code"
CONF_DEVICE_TOKEN = "device_token"
"""The client-device identity FloLogic ties a session to.

Persisted in the config entry rather than regenerated per run: FloLogic
registers a device per code/token pair, so a fresh identity on every restart
fills the account's device list with single-use entries.
"""

# --- options -----------------------------------------------------------------

CONF_POLL_INTERVAL = "poll_interval"

MANUFACTURER = "FloLogic"
