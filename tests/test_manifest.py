"""Manifest and vendoring checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.const import Platform

from custom_components.flologic import const
from custom_components.flologic.vendor import pyflologic

COMPONENT = Path(const.__file__).parent
MANIFEST = json.loads((COMPONENT / "manifest.json").read_text())


def test_there_are_no_install_time_requirements() -> None:
    """Nothing may be fetched at setup, which is why the library is vendored.

    Home Assistant can never consider a direct-URL requirement satisfied, so
    it would be re-downloaded on every start and fail setup whenever GitHub
    was unreachable at boot. An integration that shuts off water at an empty
    house must not lose that to a slow ISP.
    """
    assert MANIFEST["requirements"] == []


def test_the_vendored_version_is_recorded() -> None:
    recorded = (COMPONENT / "vendor" / "VERSION").read_text().strip()
    assert recorded == pyflologic.__version__


def test_the_vendored_library_is_the_one_being_imported() -> None:
    """Guard against the tests exercising an installed copy by accident."""
    assert "custom_components/flologic/vendor" in pyflologic.__file__


def test_every_api_the_integration_uses_exists_in_the_library() -> None:
    for name in (
        "async_refresh",
        "async_list_vids",
        "async_set_mode",
        "async_set_flow_sensitivity",
        "async_add_callback",
        "async_remove_callbacks",
        "async_close",
    ):
        assert hasattr(pyflologic.FloLogicClient, name), name


@pytest.mark.parametrize(
    "key",
    [
        "domain",
        "name",
        "codeowners",
        "config_flow",
        "documentation",
        "integration_type",
        "iot_class",
        "issue_tracker",
        "version",
    ],
)
def test_required_manifest_keys(key: str) -> None:
    """A custom integration needs all of these; hassfest rejects it otherwise."""
    assert MANIFEST.get(key) not in (None, "", [])


def test_the_domain_matches_the_folder() -> None:
    assert MANIFEST["domain"] == COMPONENT.name == const.DOMAIN


def test_webhook_is_a_dependency_and_cloud_is_optional() -> None:
    """Callbacks need the webhook component; Cloud only if the user has it."""
    assert MANIFEST["dependencies"] == ["webhook"]
    assert MANIFEST["after_dependencies"] == ["cloud"]


def test_the_iot_class_matches_how_it_actually_updates() -> None:
    """Polling is the baseline; callbacks are opt-in and need setup."""
    assert MANIFEST["iot_class"] == "cloud_polling"


def test_every_declared_platform_has_a_module() -> None:
    for platform in const.PLATFORMS:
        assert isinstance(platform, Platform)
        assert (COMPONENT / f"{platform.value}.py").is_file(), platform


def test_every_platform_module_is_declared() -> None:
    known = {
        "__init__",
        "callbacks",
        "config_flow",
        "const",
        "coordinator",
        "diagnostics",
        "entity",
    }
    declared = {platform.value for platform in const.PLATFORMS}
    modules = {path.stem for path in COMPONENT.glob("*.py")} - known
    assert modules == declared
