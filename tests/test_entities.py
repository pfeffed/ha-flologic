"""Entity behavior, especially where it encodes a hard-won protocol fact."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from homeassistant.components.valve import ValveState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flologic.vendor.pyflologic import (
    ControlMode,
    FloLogicCommandError,
    FloLogicValidationError,
    ToggledSettingName,
    ValveMode,
)

from .conftest import make_account, make_valve, setup_integration

VALVE_ENTITY = "valve.34_sample_road"
STATUS_ENTITY = "sensor.34_sample_road_status"
MODE_ENTITY = "select.34_sample_road_mode"
SHUTOFF_REASON_ENTITY = "sensor.34_sample_road_shutoff_reason"
PROBLEM_ENTITY = "sensor.34_sample_road_problem"
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


class TestShutoffReasonAndProblem:
    """State and reason are separate entities, answering separate questions."""

    async def test_an_open_valve_has_no_reason_and_no_problem(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        assert hass.states.get(SHUTOFF_REASON_ENTITY).state == "none"
        assert hass.states.get(PROBLEM_ENTITY).state == "none"

    async def test_a_manual_shutoff_says_so(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(
            hass, config_entry, mock_client, make_valve(mode=int(ValveMode.SHUTOFF))
        )
        assert hass.states.get(VALVE_ENTITY).state == "closed"
        assert hass.states.get(SHUTOFF_REASON_ENTITY).state == "manual"
        # Being told to close is not a problem.
        assert hass.states.get(PROBLEM_ENTITY).state == "none"

    async def test_an_automatic_shutoff_names_the_cause(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(mode=40))
        assert hass.states.get(VALVE_ENTITY).state == "closed"
        assert hass.states.get(SHUTOFF_REASON_ENTITY).state == "flow_time_exceeded"

    async def test_a_problem_is_reported_without_closing_the_valve(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(
            hass,
            config_entry,
            mock_client,
            make_valve(mode=ValveMode.HOME | ValveMode.CHANGE_BATTERY),
        )
        assert hass.states.get(VALVE_ENTITY).state == "open"
        assert hass.states.get(SHUTOFF_REASON_ENTITY).state == "none"
        assert hass.states.get(PROBLEM_ENTITY).state == "change_battery"

    async def test_every_reported_value_is_a_declared_option(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """An enum sensor reporting an undeclared value logs an error in HA."""
        await setup_integration(hass, config_entry)
        for mode in (
            int(ValveMode.HOME),
            int(ValveMode.SHUTOFF),
            40,
            int(ValveMode.SENSOR_LEAK),
            int(ValveMode.VALVE_FAILURE),
        ):
            await set_account(hass, config_entry, mock_client, make_valve(mode=mode))
            for entity_id in (SHUTOFF_REASON_ENTITY, PROBLEM_ENTITY):
                state = hass.states.get(entity_id)
                assert state.state in state.attributes["options"], (entity_id, mode)


class TestConnectivity:
    """The one sensor that must survive the valve going away."""

    async def test_connectivity_still_reports_when_the_valve_is_offline(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(online=False))
        assert hass.states.get(ONLINE_ENTITY).state == STATE_OFF
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


class TestUnrecognisedState:
    """The integration must not present a guess as a fact."""

    async def test_an_unmapped_shutoff_cause_is_not_shown_as_manual(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(
            hass,
            config_entry,
            mock_client,
            make_valve(mode=int(ValveMode.SHUTOFF) | (1 << 27)),
        )
        state = hass.states.get(SHUTOFF_REASON_ENTITY)
        # Not the literal "unknown": Home Assistant reserves that for an
        # entity with no data, so it would look like a broken sensor.
        assert state.state == "unrecognized"
        assert state.state in state.attributes["options"]
        assert hass.states.get(VALVE_ENTITY).state == "closed"


class TestFlowTiming:
    """Timestamps rather than counters, so nothing is rewritten every second."""

    FLOWING: ClassVar[dict[str, object]] = {
        "flowState": 4,
        "mode": int(ValveMode.HOME),
        "homeIntervalTime": 30,
        "lastNewFlow": "2026-08-16T12:00:00Z",
    }

    async def test_both_timestamps_appear_while_flowing(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(**self.FLOWING))

        started = hass.states.get("sensor.34_sample_road_flow_started")
        due = hass.states.get("sensor.34_sample_road_shutoff_due")
        assert started.state == "2026-08-16T12:00:00+00:00"
        # Start plus the 30 minute Home limit.
        assert due.state == "2026-08-16T12:30:00+00:00"

    async def test_the_target_does_not_move_between_updates(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """The reason for a timestamp: repeated updates write no new state."""
        await setup_integration(hass, config_entry)
        await set_account(hass, config_entry, mock_client, make_valve(**self.FLOWING))
        first = hass.states.get("sensor.34_sample_road_shutoff_due").state
        await set_account(hass, config_entry, mock_client, make_valve(**self.FLOWING))
        assert hass.states.get("sensor.34_sample_road_shutoff_due").state == first

    async def test_no_timestamps_when_idle(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        await setup_integration(hass, config_entry)
        assert hass.states.get("sensor.34_sample_road_flow_started").state == "unknown"
        assert hass.states.get("sensor.34_sample_road_shutoff_due").state == "unknown"

    async def test_signal_strength_is_enabled_by_default(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """A valve on bad wifi is one you cannot command in an emergency."""
        await setup_integration(hass, config_entry)
        assert hass.states.get("sensor.34_sample_road_signal_strength").state == "-83.0"

    async def test_guest_mode_is_visible_but_not_commandable(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """Its duration units are unestablished, so it is read-only for now."""
        await setup_integration(hass, config_entry)
        assert hass.states.get("binary_sensor.34_sample_road_guest_mode") is not None
        assert hass.states.get("switch.34_sample_road_guest_mode") is None
        assert hass.states.get("number.34_sample_road_guest_mode") is None


class TestSilentlyIgnoredWrites:
    """A value FloLogic would discard should fail here, saying why."""

    async def test_a_flow_sensitivity_below_winter_is_refused_with_a_reason(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        mock_client.async_update_settings.side_effect = FloLogicValidationError(
            "flow sensitivity 1.0 is below the winter flow sensitivity 4.0; "
            "FloLogic ignores such a change without reporting it."
        )
        await setup_integration(hass, config_entry)
        with pytest.raises(ServiceValidationError, match="winter flow sensitivity"):
            await hass.services.async_call(
                "number",
                "set_value",
                {
                    ATTR_ENTITY_ID: "number.34_sample_road_flow_sensitivity",
                    "value": 1.0,
                },
                blocking=True,
            )

    async def test_a_genuine_failure_is_still_reported_as_one(
        self, hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
    ) -> None:
        """Only a knowingly-ignored write is a validation error."""
        mock_client.async_update_settings.side_effect = FloLogicCommandError("nope")
        await setup_integration(hass, config_entry)
        with pytest.raises(HomeAssistantError, match="did not accept"):
            await hass.services.async_call(
                "number",
                "set_value",
                {ATTR_ENTITY_ID: "number.34_sample_road_home_flow_limit", "value": 45},
                blocking=True,
            )
