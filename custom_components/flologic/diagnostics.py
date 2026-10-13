"""Diagnostics for the FloLogic integration.

The raw status payload is the useful part of a bug report: it shows exactly
what FloLogic sent, including fields this integration does not model.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant

from .const import CONF_CALLBACK_URL, CONF_WEBHOOK_SECRET
from .coordinator import FloLogicConfigEntry, callback_event_data

REDACT_CONFIG = {CONF_API_KEY, CONF_WEBHOOK_SECRET, CONF_WEBHOOK_ID, CONF_CALLBACK_URL}
"""The webhook ID and callback URL are as good as a password: anyone holding
either can deliver callbacks, and only the signature stands in the way."""

REDACT_PAYLOAD = {"Address"}
"""A diagnostics file gets attached to public issues, and a street address has
no business in one."""


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FloLogicConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    del hass
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "valves": {
            vid: {
                "decoded": {
                    "device_type": valve.device_type_raw,
                    "is_online": valve.is_online,
                    "raw_mode": int(valve.mode),
                    "mode_flags": valve.mode.flag_names,
                    # The most useful field in a report about a state this
                    # integration does not recognize.
                    "mode_unknown_bits": valve.mode.unknown_bits,
                    "status": valve.status,
                    "shutoff_reason": valve.shutoff_reason,
                    "flow_state": valve.flow_state.name if valve.flow_state else None,
                },
                "raw": async_redact_data(dict(valve.raw), REDACT_PAYLOAD),
                "last_callback": (
                    callback_event_data(coordinator.last_callback[vid])
                    if vid in coordinator.last_callback
                    else None
                ),
            }
            for vid, valve in (coordinator.data or {}).items()
        },
    }
