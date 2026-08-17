"""Translation completeness checks.

These exist because of a specific, shipped failure: an earlier FloLogic
integration had a full strings.json and a translations/en.json containing only
entity names. Home Assistant reads the latter at runtime for custom
components, so its config flow rendered raw keys instead of labels, and
nothing caught it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.flologic import const
from custom_components.flologic.binary_sensor import BINARY_SENSORS
from custom_components.flologic.sensor import SENSORS
from custom_components.flologic.vendor.pyflologic import ValveMode

COMPONENT = Path(const.__file__).parent
STRINGS = COMPONENT / "strings.json"
EN = COMPONENT / "translations" / "en.json"


def load(path: Path) -> dict[str, Any]:
    """Return a parsed JSON file."""
    return json.loads(path.read_text())


def flatten(data: Any, prefix: str = "") -> set[str]:
    """Return every leaf key path in a nested mapping."""
    if not isinstance(data, dict):
        return {prefix}
    keys: set[str] = set()
    for key, value in data.items():
        keys |= flatten(value, f"{prefix}.{key}" if prefix else key)
    return keys


def test_english_translations_match_strings() -> None:
    """en.json must carry everything strings.json does, config flow included."""
    assert flatten(load(STRINGS)) == flatten(load(EN))


@pytest.mark.parametrize("section", ["config", "options", "entity", "exceptions"])
def test_required_sections_are_present(section: str) -> None:
    """A missing section renders as raw keys in the UI."""
    assert section in load(EN)


def test_config_flow_steps_are_translated() -> None:
    """Both flow steps need titles and field labels."""
    config = load(EN)["config"]
    assert set(config["step"]) == {"user", "reauth_confirm"}
    for step in config["step"].values():
        assert step.get("title")
        assert step.get("data")


def test_every_status_value_has_a_state_name() -> None:
    """The status sensor's enum options must all be translatable.

    A mode bit added to the library without a matching string here would show
    up in the UI as a bare identifier.
    """
    status = next(item for item in SENSORS if item.key == "status")
    translated = set(load(EN)["entity"]["sensor"]["status"]["state"])
    assert status.options is not None
    assert set(status.options) <= translated
    assert {flag.name.lower() for flag in ValveMode if flag.name} <= translated


def test_every_translation_key_used_by_an_entity_exists() -> None:
    """Every translation_key referenced in code must resolve."""
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
