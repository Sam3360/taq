"""Detects the Python environment TAQ is about to modify.

TAQ always operates on the interpreter it is currently running under -
exactly like ``python -m pip`` does. This keeps environment handling simple
and predictable: activate a venv, run ``taq``, and it installs into that
venv. There's no separate "target" concept to get wrong.
"""

from __future__ import annotations

import site
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

from packaging.tags import Tag, sys_tags


@dataclass(frozen=True)
class Environment:
    """Describes where TAQ will read/write packages."""

    python_executable: str
    purelib: Path
    platlib: Path
    scripts: Path
    is_virtualenv: bool
    version_info: tuple

    @property
    def site_packages(self) -> Path:
        # purelib and platlib are usually identical on CPython; purelib is
        # the right home for the vast majority of (pure-Python) packages.
        return self.purelib

    def compatible_tags(self) -> list[Tag]:
        """Wheel tags compatible with this interpreter/platform, best first."""
        return list(sys_tags())

    def describe(self) -> str:
        kind = "virtual environment" if self.is_virtualenv else "system/base Python"
        return f"{self.python_executable} ({kind})"


def current_environment() -> Environment:
    """Build an Environment describing the currently running interpreter."""
    paths = sysconfig.get_paths()
    is_venv = sys.prefix != sys.base_prefix or hasattr(sys, "real_prefix")

    return Environment(
        python_executable=sys.executable,
        purelib=Path(paths["purelib"]),
        platlib=Path(paths["platlib"]),
        scripts=Path(paths["scripts"]),
        is_virtualenv=is_venv,
        version_info=tuple(sys.version_info[:3]),
    )


def user_site_available() -> bool:
    """Whether the (non-venv) user site-packages location is usable."""
    return not current_environment().is_virtualenv and site.ENABLE_USER_SITE
