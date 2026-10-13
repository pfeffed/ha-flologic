"""Translation completeness checks.

Home Assistant reads translations/en.json at runtime for custom components,
so a string present only in strings.json renders as a raw key. These make
sure every key the code uses resolves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.flologic import const
from custom_components.flologic.binary_sensor import BINARY_SENSORS
from custom_components.flologic.event import EVENT_TYPES
from custom_components.flologic.sensor import SENSORS
from custom_components.flologic.vendor.pyflologic import SETTABLE_MODES, ValveMode

COMPONENT = Path(const.__file__).parent
STRINGS = COMPONENT / "strings.json"
EN = COMPONENT / "translations" / "en.json"


def load(path: Path) -> dict[str, Any]:
    """Return a parsed JSON file."""
    return json.loads(path.read_text())


def test_english_translations_match_strings() -> None:
    """en.json must carry everything strings.json does, config flow included."""
    assert load(STRINGS) == load(EN)


@pytest.mark.parametrize(
    "section", ["config", "options", "entity", "exceptions", "issues"]
)
def test_required_sections_are_present(section: str) -> None:
    """A missing section renders as raw keys in the UI."""
    assert section in load(EN)


def test_config_flow_steps_are_translated() -> None:
    config = load(EN)["config"]
    assert set(config["step"]) == {"user", "reauth_confirm", "reconfigure"}
    for step in config["step"].values():
        assert step.get("title")
        assert step.get("data")


def test_every_enum_sensor_option_has_a_state_name() -> None:
    """An option without a string shows in the UI as a bare identifier."""
    english = load(EN)["entity"]["sensor"]
    for description in SENSORS:
        if description.options:
            translated = set(english[description.translation_key]["state"])
            assert set(description.options) <= translated, description.key
    status = set(english["status"]["state"])
    assert {flag.name.lower() for flag in ValveMode if flag.name} <= status


def test_every_mode_option_has_a_state_name() -> None:
    states = load(EN)["entity"]["select"]["valve_mode"]["state"]
    assert {mode.value for mode in SETTABLE_MODES} == set(states)


def test_every_event_type_has_a_state_name() -> None:
    states = load(EN)["entity"]["event"]["callback"]["state_attributes"]["event_type"]
    assert set(EVENT_TYPES) == set(states["state"])


def test_every_translation_key_used_by_an_entity_exists() -> None:
    english = load(EN)["entity"]
    for platform, descriptions in (
        ("sensor", SENSORS),
        ("binary_sensor", BINARY_SENSORS),
    ):
        for description in descriptions:
            if description.translation_key:
                assert description.translation_key in english[platform], (
                    f"{platform}.{description.translation_key}"
                )
