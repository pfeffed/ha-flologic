"""Manifest checks, mostly about not shipping a lie.

The integration is developed against a sibling checkout of pyflologic while
the manifest pins a published version. Nothing notices when those diverge
until a user installs the pinned release and the integration calls a method
that does not exist in it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyflologic
import pytest
from homeassistant.const import Platform

from custom_components.flologic import const

COMPONENT = Path(const.__file__).parent
MANIFEST = json.loads((COMPONENT / "manifest.json").read_text())


def test_the_pinned_library_version_is_the_one_being_tested() -> None:
    """A pin behind the code under test ships a broken install."""
    requirement = next(
        item for item in MANIFEST["requirements"] if item.startswith("pyflologic")
    )
    assert requirement == f"pyflologic=={pyflologic.__version__}"


def test_every_api_the_integration_uses_exists_in_the_library() -> None:
    """Catch a call added here before the library grew the method."""
    for name in (
        "async_connect",
        "async_disconnect",
        "async_refresh",
        "async_set_mode",
        "async_update_settings",
        "async_set_toggled_setting",
        "async_fetch_notifications",
        "add_listener",
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
        "requirements",
        "version",
    ],
)
def test_required_manifest_keys(key: str) -> None:
    """A custom integration needs all of these; hassfest rejects it otherwise."""
    assert MANIFEST.get(key) not in (None, "", [])


def test_the_domain_matches_the_folder() -> None:
    assert MANIFEST["domain"] == COMPONENT.name == const.DOMAIN


def test_the_iot_class_matches_how_it_actually_updates() -> None:
    """Push with a polling backstop, confirmed against real hardware."""
    assert MANIFEST["iot_class"] == "cloud_push"


def test_every_declared_platform_has_a_module() -> None:
    """A platform listed without a module fails at setup, not at import."""
    for platform in const.PLATFORMS:
        assert isinstance(platform, Platform)
        assert (COMPONENT / f"{platform.value}.py").is_file(), platform


def test_every_platform_module_is_declared() -> None:
    """And the reverse: a module nobody loads is dead weight."""
    known = {
        "__init__",
        "config_flow",
        "const",
        "coordinator",
        "diagnostics",
        "entity",
    }
    declared = {platform.value for platform in const.PLATFORMS}
    modules = {path.stem for path in COMPONENT.glob("*.py")} - known
    assert modules == declared
