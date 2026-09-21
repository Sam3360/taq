"""Shared logic for removing an installed distribution's files.

Used both by ``taq uninstall`` and internally by ``taq install --upgrade``
(which uninstalls the old version before installing the new one).
"""

from __future__ import annotations

import configparser

from .dist_info import InstalledDistribution
from .environment import Environment
from .scripts import remove_console_script


def remove_distribution(dist: InstalledDistribution, env: Environment, quiet: bool = False) -> list:
    """Delete every file RECORD knows about, plus generated script launchers."""
    removed = []

    entry_points_file = dist.location / "entry_points.txt"
    if entry_points_file.exists():
        parser = configparser.ConfigParser(delimiters=("=",), strict=False)
        parser.optionxform = str
        parser.read(entry_points_file, encoding="utf-8")
        if "console_scripts" in parser:
            for script_name in parser["console_scripts"]:
                removed.extend(remove_console_script(script_name.strip(), env.scripts))

    for path in dist.record_files():
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(path)
            if path.suffix == ".py":
                removed.extend(_remove_pycache_for(path))

    # Clean up now-empty directories left behind (e.g. a package's
    # subpackage folder), but never remove site-packages/scripts themselves.
    boundaries = {env.site_packages.resolve(), env.scripts.resolve()}
    parents = sorted({p.parent for p in removed}, key=lambda p: len(p.parts), reverse=True)
    for directory in parents:
        _remove_if_empty(directory, boundaries)

    if not quiet:
        print(f"Removed {dist.name} {dist.version} ({len(removed)} files)")
    return removed


def _remove_pycache_for(py_file) -> list:
    """Delete compiled bytecode caches for a removed .py file.

    These are generated lazily on import and never appear in RECORD, so
    they'd otherwise survive uninstall and leave a stray (namespace-package)
    directory behind. Matches every optimization level (.pyc, opt-1, opt-2).
    """
    removed = []
    cache_dir = py_file.parent / "__pycache__"
    if not cache_dir.is_dir():
        return removed
    for candidate in cache_dir.glob(f"{py_file.stem}.cpython-*.pyc"):
        candidate.unlink(missing_ok=True)
        removed.append(candidate)
    return removed


def _remove_if_empty(directory, boundaries) -> None:
    try:
        while directory.exists() and directory.resolve() not in boundaries and not any(directory.iterdir()):
            next_dir = directory.parent
            directory.rmdir()
            directory = next_dir
    except OSError:
        pass
