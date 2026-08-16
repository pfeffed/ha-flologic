"""Diagnostics for the FloLogic integration.

The raw valve payload is the useful part of a bug report: this protocol was
reverse-engineered, so a field behaving unexpectedly is best diagnosed by
seeing exactly what the cloud sent.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_CODE, CONF_DEVICE_TOKEN
from .coordinator import FloLogicConfigEntry

REDACT_CONFIG = {CONF_PASSWORD, CONF_EMAIL, CONF_DEVICE_CODE, CONF_DEVICE_TOKEN}

REDACT_PAYLOAD = {
    # Not protocol signal, and a diagnostics file gets attached to public
    # issues: the street address, the insurance policy and the account
    # holder's name have no business in one.
    "location",
    "valveAddress",
    "insuranceCompanyId",
    "insurancePolicy",
    "policyLastName",
    "combinedName",
    "combinedNameWithoutAddress",
    "valveFriendlyName",
    "networkName",
    "email",
    "relogToken",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FloLogicConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    del hass
    coordinator = entry.runtime_data
    account = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": dict(entry.options),
        },
        "connection": {
            "connected": coordinator.client.connected,
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "valves": {
            valve_id: {
                "decoded": {
                    "name_present": bool(valve.name),
                    "model": valve.model,
                    "firmware_version": valve.firmware_version,
                    "device_kind": valve.device_kind,
                    "is_controllable": valve.is_controllable,
                    "is_online": valve.is_online,
                    "raw_mode": int(valve.mode),
                    "mode_flags": valve.mode.flag_names,
                    # The single most useful field in a bug report about a
                    # state this integration does not recognize.
                    "mode_unknown_bits": valve.mode.unknown_bits,
                    "status": valve.status,
                    "control_mode": (
                        valve.control_mode.value if valve.control_mode else None
                    ),
                    "flow_state": (valve.flow_state.name if valve.flow_state else None),
                    "is_water_flowing": valve.is_water_flowing,
                    "shutoff_countdown_seconds": valve.shutoff_countdown_seconds(),
                    "battery_percent": valve.battery_percent,
                    "battery_level_raw": valve.battery_level_raw,
                },
                "raw": async_redact_data(dict(valve.raw), REDACT_PAYLOAD),
            }
            for valve_id, valve in account.valves.items()
        },
        "accesses": {
            valve_id: {
                "privilege": access.privilege,
                "notifications": int(access.notifications),
                "notification_flags": access.notifications.flag_names,
                "notification_unknown_bits": access.notifications.unknown_bits,
            }
            for valve_id, access in account.accesses.items()
        },
    }
