#!/usr/bin/env python3
"""Copy pyflologic into the integration.

The library is not on PyPI, and a manifest requirement pointing at a release
URL turned out to be unusable: Home Assistant's ``is_installed`` can never
consider a direct URL satisfied, so it re-downloads the wheel on *every*
startup and fails setup outright if GitHub is unreachable at boot. For an
integration whose job is shutting off water at an empty house, "no internet
during boot" must not mean "no leak protection".

So the integration ships its own copy and declares no requirement at all.
The library keeps its own repository, tests and releases; this script is the
seam between them, run at release time.

    uv run python scripts/vendor.py                 # from ../pyflologic
    uv run python scripts/vendor.py --source PATH
    uv run python scripts/vendor.py --check         # verify, change nothing
"""

from __future__ import annotations

import argparse
import filecmp
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR_ROOT = REPO / "custom_components" / "flologic" / "vendor"
TARGET = VENDOR_ROOT / "pyflologic"
DEFAULT_SOURCE = REPO.parent / "pyflologic"

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".*")

HEADER = '''"""Vendored third-party code.

Everything under this directory is a verbatim copy of another project, kept
here so the integration has no install-time dependencies. Do not edit it: run
``scripts/vendor.py`` against the upstream checkout instead, or the next sync
will silently discard the change.
"""
'''


def source_version(source: Path) -> str:
    """Read the library's version from its pyproject."""
    text = (source / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"', text, re.M)
    if not match:
        raise SystemExit(f"no version found in {source / 'pyproject.toml'}")
    return match.group(1)


def differences(source: Path) -> list[str]:
    """Return the paths that differ between upstream and the vendored copy."""
    if not TARGET.is_dir():
        return ["<not vendored>"]

    found: list[str] = []

    def walk(comparison: filecmp.dircmp, prefix: str = "") -> None:
        for name in (
            *comparison.left_only,
            *comparison.right_only,
            *comparison.diff_files,
        ):
            if name == "__pycache__":
                continue
            found.append(f"{prefix}{name}")
        for name, sub in comparison.subdirs.items():
            if name != "__pycache__":
                walk(sub, f"{prefix}{name}/")

    walk(filecmp.dircmp(source / "src" / "pyflologic", TARGET, ignore=["__pycache__"]))
    return found


def vendor(source: Path) -> str:
    """Replace the vendored copy with the upstream source."""
    library = source / "src" / "pyflologic"
    if not library.is_dir():
        raise SystemExit(f"no pyflologic source at {library}")

    version = source_version(source)
    if TARGET.exists():
        shutil.rmtree(TARGET)
    VENDOR_ROOT.mkdir(parents=True, exist_ok=True)
    (VENDOR_ROOT / "__init__.py").write_text(HEADER)
    shutil.copytree(library, TARGET, ignore=IGNORE)
    (VENDOR_ROOT / "VERSION").write_text(f"{version}\n")
    return version


def main() -> int:
    """Vendor the library, or check that the copy is current."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the copy is current without changing anything",
    )
    args = parser.parse_args()
    source = args.source.resolve()

    if args.check:
        if not source.is_dir():
            print(f"upstream not present at {source}; nothing to compare")
            return 0
        drift = differences(source)
        recorded = (VENDOR_ROOT / "VERSION").read_text().strip()
        upstream = source_version(source)
        if drift or recorded != upstream:
            print(f"vendored {recorded}, upstream {upstream}")
            for path in drift:
                print(f"  differs: {path}")
            print("\nrun: uv run python scripts/vendor.py")
            return 1
        print(f"vendored copy is current ({recorded})")
        return 0

    version = vendor(source)
    print(f"vendored pyflologic {version} from {source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
