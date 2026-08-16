"""Entity behavior, especially where it encodes a hard-won protocol fact."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.valve import ValveState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pyflologic import (
    ControlMode,
    FloLogicCommandError,
    ToggledSettingName,
    ValveMode,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import make_account, make_valve, setup_integration

VALVE_ENTITY = "valve.34_sample_road"
STATUS_ENTITY = "sensor.34_sample_road_status"
MODE_ENTITY = "select.34_sample_road_mode"
WATER_OFF_ENTITY = "binary_sensor.34_sample_road_water_off"
ONLINE_ENTITY = "binary_sensor.34_sample_road_connectivity"


async def set_account(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_client: MagicMock,
    *valves: object,
) -> None:
    """Publish a new account snapshot, the way a cloud push does."""
    account = make_account(*valves)  # type: ignore[arg-type]
    mock_client.account = account
    mock_client.valves = dict(account.valves)
    entry.runtime_data.async_set_updated_data(account)
    await hass.async_block_till_done()


class TestValveEntity:
    """The shutoff itself."""

    async def test_open_when_in_home(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        assert hass.states.get(VALVE_ENTITY).state == ValveState.OPEN

    @pytest.mark.parametrize(
        "mode",
        [
            int(ValveMode.SHUTOFF),
            # A leak, an exceeded flow limit and a freeze trip all mean the
            # water is off. Reporting "open" through any of them would be a
            # lie of exactly the kind this device exists to prevent.
            int(ValveMode.SENSOR_LEAK),
            40,  # SHUTOFF | FLOW_TIME_EXCEEDED, captured from real hardware
            int(ValveMode.LOW_TEMP_SHUTOFF),
        ],
    )
    async def test_closed_for_every_water_off_condition(
        self,
        hass: HomeAssistant,
        config_entry: MockConfigEntry,
        mock_client: MagicMock,
        mode: int,
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(mode=mode))
        assert hass.states.get(VALVE_ENTITY).state == ValveState.CLOSED

    async def test_closing_sends_shutoff(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await hass.services.async_call(
            "valve", "close_valve", {ATTR_ENTITY_ID: VALVE_ENTITY}, blocking=True
        )
        mock_client.async_set_mode.assert_awaited_once_with(
            "106193", ControlMode.SHUTOFF
        )

    async def test_opening_returns_to_home(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await hass.services.async_call(
            "valve", "open_valve", {ATTR_ENTITY_ID: VALVE_ENTITY}, blocking=True
        )
        mock_client.async_set_mode.assert_awaited_once_with("106193", ControlMode.HOME)

    async def test_a_rejected_command_surfaces(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        mock_client.async_set_mode.side_effect = FloLogicCommandError("nope")
        with pytest.raises(HomeAssistantError, match="did not accept"):
            await hass.services.async_call(
                "valve", "close_valve", {ATTR_ENTITY_ID: VALVE_ENTITY}, blocking=True
            )

    async def test_commands_name_the_right_valve(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """Two valves, one command, and it must reach only the one addressed."""
        account = make_account(
            make_valve("106193", "34 Sample Road"),
            make_valve("4613", "Riverside Main House"),
        )
        mock_client.account = account
        mock_client.valves = dict(account.valves)
        await setup_integration(hass, config_entry)

        await hass.services.async_call(
            "valve",
            "close_valve",
            {ATTR_ENTITY_ID: "valve.riverside_main_house"},
            blocking=True,
        )
        mock_client.async_set_mode.assert_awaited_once_with("4613", ControlMode.SHUTOFF)


class TestModeSelect:
    """The five selectable modes."""

    async def test_reports_the_current_mode(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        assert hass.states.get(MODE_ENTITY).state == "home"

    async def test_override_has_no_selectable_mode(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """An irrigation controller holding the valve is not a user choice."""
        await setup_integration(hass, config_entry)
        await set_account(
            hass, config_entry, mock_client, make_valve(mode=int(ValveMode.OVERRIDE))
        )
        assert hass.states.get(MODE_ENTITY).state == "unknown"

    async def test_selecting_sends_the_mode(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: MODE_ENTITY, "option": "away"},
            blocking=True,
        )
        mock_client.async_set_mode.assert_awaited_once_with("106193", "away")


class TestSensors:
    """Readings, and the ones deliberately not created."""

    async def test_status_reports_the_headline_state(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(mode=40))
        state = hass.states.get(STATUS_ENTITY)
        assert state.state == "flow_time_exceeded"
        assert state.attributes["raw_mode"] == 40
        assert set(state.attributes["active_flags"]) == {
            "shutoff",
            "flow_time_exceeded",
        }

    async def test_no_battery_sensor_for_an_implausible_reading(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """The stock fixture reports 134217728, which is not a percentage."""
        await setup_integration(hass, config_entry)
        assert hass.states.get("sensor.34_sample_road_battery") is None

    async def test_battery_sensor_when_the_reading_is_plausible(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        account = make_account(make_valve(batteryLevel=50))
        mock_client.account = account
        mock_client.valves = dict(account.valves)
        await setup_integration(hass, config_entry)
        assert hass.states.get("sensor.34_sample_road_battery").state == "50.0"


class TestBinarySensors:
    """Grouped conditions and availability."""

    async def test_water_off_lists_the_flags_that_caused_it(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        assert hass.states.get(WATER_OFF_ENTITY).state == STATE_OFF
        await set_account(hass, config_entry, mock_client, make_valve(mode=40))
        state = hass.states.get(WATER_OFF_ENTITY)
        assert state.state == STATE_ON
        assert set(state.attributes["active_flags"]) == {
            "flow_time_exceeded",
            "shutoff",
        }

    async def test_connectivity_still_reports_when_the_valve_is_offline(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """The one sensor that must not go unavailable when the valve does."""
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(online=False))

        assert hass.states.get(ONLINE_ENTITY).state == STATE_OFF
        # Everything else correctly reports that it cannot know.
        assert hass.states.get(WATER_OFF_ENTITY).state == STATE_UNAVAILABLE
        assert hass.states.get(VALVE_ENTITY).state == STATE_UNAVAILABLE


class TestNumbers:
    """Writable settings."""

    async def test_home_limit_is_written_back(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        entity = "number.34_sample_road_home_flow_limit"
        assert hass.states.get(entity).state == "99.0"
        await hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: entity, "value": 45},
            blocking=True,
        )
        mock_client.async_update_settings.assert_awaited_once_with(
            "106193", home_limit_minutes=45.0
        )

    async def test_a_sub_minute_away_limit_is_representable(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """A real valve runs 0.5 minutes; a whole-minute step would forbid it."""
        await setup_integration(hass, config_entry)
        state = hass.states.get("number.34_sample_road_away_flow_limit")
        assert state.state == "0.5"
        assert float(state.attributes["min"]) <= 0.5


class TestRegistry:
    """Entity identity."""

    async def test_unique_ids_are_hardware_scoped(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        registry = er.async_get(hass)
        entry = registry.async_get(VALVE_ENTITY)
        assert entry is not None
        assert entry.unique_id == "hw-106193_valve"


class TestToggledSettings:
    """The switch-and-number pairs for sign-encoded settings."""

    async def test_the_switch_reflects_the_sign(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        # The fixture valve carries autoAwayTime 96: positive, so switched on.
        await setup_integration(hass, config_entry)
        state = hass.states.get("switch.34_sample_road_auto_away")
        assert state.state == STATE_ON
        assert state.attributes["configured_value"] == 96.0

    async def test_a_disabled_setting_keeps_its_value_visible(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """Off with 18 hours showing is exactly how the app renders it."""
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(autoAwayTime=-18))

        assert hass.states.get("switch.34_sample_road_auto_away").state == STATE_OFF
        assert hass.states.get("number.34_sample_road_auto_away_delay").state == "18.0"

    async def test_switching_off_preserves_the_magnitude(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await hass.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: "switch.34_sample_road_auto_away"},
            blocking=True,
        )
        mock_client.async_set_toggled_setting.assert_awaited_once_with(
            "106193", ToggledSettingName.AUTO_AWAY, enabled=False
        )

    async def test_setting_the_value_does_not_touch_the_switch(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """Raising a threshold must not silently enable a disabled setting.

        Run in US customary units so the number is entered in the same scale
        FloLogic uses; Home Assistant converts for metric users, which is why
        the same value expressed in Celsius would be out of range.
        """
        hass.config.units = US_CUSTOMARY_SYSTEM
        await setup_integration(hass, config_entry)
        await hass.services.async_call(
            "number",
            "set_value",
            {
                ATTR_ENTITY_ID: "number.34_sample_road_low_temperature_shutoff",
                "value": 40,
            },
            blocking=True,
        )
        mock_client.async_set_toggled_setting.assert_awaited_once_with(
            "106193", ToggledSettingName.LOW_TEMP_SHUTOFF, value=40.0
        )

    async def test_a_temperature_threshold_converts_for_metric_users(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """FloLogic speaks Fahrenheit; the entity speaks the user's units."""
        hass.config.units = METRIC_SYSTEM
        await setup_integration(hass, config_entry)
        entity = "number.34_sample_road_low_temperature_shutoff"
        # 36 F is the fixture's threshold, which is a little over 2 C.
        assert float(hass.states.get(entity).state) == pytest.approx(2.2, abs=0.1)

        await hass.services.async_call(
            "number", "set_value", {ATTR_ENTITY_ID: entity, "value": 5}, blocking=True
        )
        _, kwargs = mock_client.async_set_toggled_setting.call_args
        assert kwargs["value"] == pytest.approx(41.0, abs=0.1)

    async def test_a_rejected_toggle_surfaces(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        mock_client.async_set_toggled_setting.side_effect = FloLogicCommandError("no")
        with pytest.raises(HomeAssistantError, match="did not accept"):
            await hass.services.async_call(
                "switch",
                "turn_on",
                {ATTR_ENTITY_ID: "switch.34_sample_road_winter_mode"},
                blocking=True,
            )
