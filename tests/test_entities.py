"""Entity states and commands."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.number import (
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.components.valve import SERVICE_CLOSE_VALVE, SERVICE_OPEN_VALVE
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.const import DOMAIN
from custom_components.flologic.vendor.pyflologic import (
    ControlMode,
    FloLogicCommandError,
    ValveMode,
)

from .conftest import DEVICE, VID, make_valve, set_valves, setup_integration

VALVE = f"valve.{DEVICE}"
MODE = f"select.{DEVICE}_mode"
SENSITIVITY = f"number.{DEVICE}_flow_sensitivity"


@pytest.fixture(autouse=True)
def fahrenheit(hass: HomeAssistant) -> None:
    """Show temperatures in FloLogic's own unit, so values read as in the app."""
    hass.config.units = US_CUSTOMARY_SYSTEM


def state(hass: HomeAssistant, entity_id: str) -> str:
    """Return an entity's state, failing clearly if it does not exist."""
    current = hass.states.get(entity_id)
    assert current is not None, entity_id
    return current.state


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


class TestDevice:
    async def test_named_by_vid_with_the_model(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, VID)})
        assert device is not None
        assert device.name == f"FloLogic {VID}"
        assert device.model == "WiFi Connect"
        assert device.serial_number == VID
        assert device.manufacturer == "FloLogic"

    async def test_every_valve_gets_a_device(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        set_valves(mock_client, make_valve(), make_valve("93DBB1", Type="GConnect"))
        await setup_integration(hass, config_entry)
        devices = dr.async_entries_for_config_entry(
            dr.async_get(hass), config_entry.entry_id
        )
        assert {device.serial_number for device in devices} == {VID, "93DBB1"}
        assert hass.states.get("valve.flologic_93dbb1") is not None

    async def test_unique_ids_use_the_vid(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        entry = er.async_get(hass).async_get(VALVE)
        assert entry is not None
        assert entry.unique_id == f"{VID}_valve"


class TestValve:
    async def test_open_while_home(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        assert state(hass, VALVE) == "open"

    @pytest.mark.parametrize(
        "mode",
        [
            ValveMode.SHUTOFF,
            ValveMode.SHUTOFF | ValveMode.FLOW_TIME_EXCEEDED,
            ValveMode.HOME | ValveMode.LOW_TEMP_SHUTOFF,
        ],
    )
    async def test_closed_for_any_water_off_condition(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
        mode: ValveMode,
    ):
        set_valves(mock_client, make_valve(Mode=int(mode)))
        await setup_integration(hass, config_entry)
        assert state(hass, VALVE) == "closed"

    async def test_close_shuts_off_and_open_returns_home(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        await hass.services.async_call(
            "valve", SERVICE_CLOSE_VALVE, {ATTR_ENTITY_ID: VALVE}, blocking=True
        )
        mock_client.async_set_mode.assert_awaited_with(VID, ControlMode.SHUTOFF)
        await hass.services.async_call(
            "valve", SERVICE_OPEN_VALVE, {ATTR_ENTITY_ID: VALVE}, blocking=True
        )
        mock_client.async_set_mode.assert_awaited_with(VID, ControlMode.HOME)

    async def test_the_confirmed_state_is_published_at_once(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)

        async def apply(vid: str, mode: ControlMode) -> None:
            set_valves(mock_client, make_valve(vid, Mode=int(mode.flag)))

        mock_client.async_set_mode.side_effect = apply
        await hass.services.async_call(
            "valve", SERVICE_CLOSE_VALVE, {ATTR_ENTITY_ID: VALVE}, blocking=True
        )
        assert state(hass, VALVE) == "closed"

    async def test_a_failed_command_is_raised(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        mock_client.async_set_mode.side_effect = FloLogicCommandError("no answer")
        with pytest.raises(HomeAssistantError, match="no answer"):
            await hass.services.async_call(
                "valve", SERVICE_CLOSE_VALVE, {ATTR_ENTITY_ID: VALVE}, blocking=True
            )

    async def test_unavailable_while_offline(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        set_valves(mock_client, make_valve(Online=False))
        await setup_integration(hass, config_entry)
        assert state(hass, VALVE) == STATE_UNAVAILABLE


class TestModeSelect:
    async def test_offers_only_what_the_api_accepts(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        state = hass.states.get(MODE)
        assert state.state == "home"
        assert state.attributes["options"] == ["home", "away", "bypass", "shutoff"]

    async def test_disabled_reads_as_no_selection(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        set_valves(mock_client, make_valve(Mode=16))
        await setup_integration(hass, config_entry)
        assert state(hass, MODE) == STATE_UNKNOWN

    async def test_selecting_sets_the_mode(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        await hass.services.async_call(
            "select",
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: MODE, ATTR_OPTION: "away"},
            blocking=True,
        )
        mock_client.async_set_mode.assert_awaited_with(VID, ControlMode.AWAY)


class TestFlowSensitivity:
    async def test_reads_and_writes(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        assert state(hass, SENSITIVITY) == "6.0"
        await hass.services.async_call(
            "number",
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: SENSITIVITY, ATTR_VALUE: 2.5},
            blocking=True,
        )
        mock_client.async_set_flow_sensitivity.assert_awaited_with(VID, 2.5)

    async def test_an_ignored_write_explains_itself(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        mock_client.async_set_flow_sensitivity.side_effect = FloLogicCommandError(
            "FloLogic accepted flow sensitivity 1, but 414B91 did not report it"
        )
        with pytest.raises(HomeAssistantError, match="accepted flow sensitivity"):
            await hass.services.async_call(
                "number",
                SERVICE_SET_VALUE,
                {ATTR_ENTITY_ID: SENSITIVITY, ATTR_VALUE: 1},
                blocking=True,
            )


class TestSensors:
    async def test_live_state(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        assert state(hass, f"sensor.{DEVICE}_status") == "home"
        assert state(hass, f"sensor.{DEVICE}_shutoff_reason") == "none"
        assert state(hass, f"sensor.{DEVICE}_problem") == "none"
        assert state(hass, f"sensor.{DEVICE}_flow_state") == "no_flow"
        assert state(hass, f"sensor.{DEVICE}_temperature") == "70.0"
        assert (
            state(hass, f"sensor.{DEVICE}_last_flow_change")
            == "2026-10-13T15:40:10+00:00"
        )

    async def test_read_only_settings(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        assert state(hass, f"sensor.{DEVICE}_home_flow_limit") == "60.0"
        assert state(hass, f"sensor.{DEVICE}_away_flow_limit") == "0.1"
        assert state(hass, f"sensor.{DEVICE}_bypass_duration") == "241.0"
        assert state(hass, f"sensor.{DEVICE}_pre_alert_notice") == "5.0"
        assert state(hass, f"sensor.{DEVICE}_low_temperature_alert_threshold") == "38.0"
        assert (
            state(hass, f"sensor.{DEVICE}_low_temperature_shutoff_threshold") == "36.0"
        )

    async def test_an_automatic_shutoff_names_its_cause(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        mode = ValveMode.AWAY | ValveMode.SHUTOFF | ValveMode.FLOW_TIME_EXCEEDED
        set_valves(mock_client, make_valve(Mode=int(mode)))
        await setup_integration(hass, config_entry)
        assert state(hass, f"sensor.{DEVICE}_shutoff_reason") == "flow_time_exceeded"
        status = hass.states.get(f"sensor.{DEVICE}_status")
        assert status.state == "flow_time_exceeded"
        assert status.attributes["active_flags"] == [
            "away",
            "shutoff",
            "flow_time_exceeded",
        ]

    async def test_a_disabled_bypass_timer_reads_unknown_duration(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        set_valves(mock_client, make_valve(BypassTimeEnabled=False, BypassTime=None))
        await setup_integration(hass, config_entry)
        assert (
            hass.states.get(f"sensor.{DEVICE}_bypass_duration").state == STATE_UNKNOWN
        )
        assert state(hass, f"binary_sensor.{DEVICE}_bypass_timer") == "off"

    async def test_the_active_limit_is_disabled_by_default(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        entry = er.async_get(hass).async_get(f"sensor.{DEVICE}_active_flow_limit")
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


class TestBinarySensors:
    async def test_states(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        set_valves(mock_client, make_valve(FlowState=4, AwayTime=0))
        await setup_integration(hass, config_entry)
        assert (
            hass.states.get(f"binary_sensor.{DEVICE}_water_flow_detected").state == "on"
        )
        assert state(hass, f"binary_sensor.{DEVICE}_away_turns_water_off") == "on"
        assert state(hass, f"binary_sensor.{DEVICE}_low_temperature_alert") == "on"

    async def test_connectivity_survives_the_valve_going_offline(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        set_valves(mock_client, make_valve(Online=False))
        await refresh(hass, config_entry)
        assert state(hass, f"binary_sensor.{DEVICE}_connectivity") == "off"
        assert (
            state(hass, f"binary_sensor.{DEVICE}_water_flow_detected")
            == STATE_UNAVAILABLE
        )

    async def test_a_departed_valve_goes_unavailable(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ):
        await setup_integration(hass, config_entry)
        set_valves(mock_client, make_valve("93DBB1"))
        await refresh(hass, config_entry)
        assert state(hass, VALVE) == STATE_UNAVAILABLE
        assert state(hass, f"binary_sensor.{DEVICE}_connectivity") == STATE_UNAVAILABLE
