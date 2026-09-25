"""Reads metadata about *already installed* distributions.

We use the standard library's ``importlib.metadata`` for discovery and
parsing - it already implements the dist-info/egg-info spec correctly, so
there's no reason to hand-roll it. TAQ still owns writing/removing
dist-info directories itself (see wheel_installer.py).
"""

from __future__ import annotations

import csv
import importlib.metadata as importlib_metadata
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


@dataclass
class InstalledDistribution:
    name: str
    version: str
    location: Path  # the .dist-info directory
    summary: str | None
    requires: list[str]
    installer: str | None

    @property
    def canonical_name(self) -> str:
        return canonicalize_name(self.name)

    def record_files(self) -> list[Path]:
        """Files listed in RECORD, resolved to absolute paths."""
        record = self.location / "RECORD"
        if not record.exists():
            return []
        base = self.location.parent
        files = []
        with record.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                rel = row[0]
                files.append((base / rel).resolve())
        return files


def _to_distribution(dist: importlib_metadata.Distribution) -> InstalledDistribution | None:
    meta = dist.metadata
    name = meta.get("Name")
    if not name:
        return None
    installer = None
    try:
        installer_file = dist.read_text("INSTALLER")
        if installer_file:
            installer = installer_file.strip()
    except Exception:
        installer = None

    requires = list(dist.requires or [])
    location = getattr(dist, "_path", None)
    if location is None:
        location = Path(str(dist.locate_file("")))
    else:
        location = Path(str(location))

    return InstalledDistribution(
        name=name,
        version=meta.get("Version", "0"),
        location=location,
        summary=meta.get("Summary"),
        requires=requires,
        installer=installer,
    )


def iter_installed(search_path: list[str] | None = None) -> list[InstalledDistribution]:
    """List every distribution visible on the given (or current) path."""
    result = []
    seen = set()
    kwargs = {"path": search_path} if search_path is not None else {}
    for dist in importlib_metadata.distributions(**kwargs):
        parsed = _to_distribution(dist)
        if parsed is None:
            continue
        key = parsed.canonical_name
        if key in seen:
            continue
        seen.add(key)
        result.append(parsed)
    return sorted(result, key=lambda d: d.canonical_name)


def find_installed(name: str, search_path: list[str] | None = None) -> InstalledDistribution | None:
    """Find one installed distribution by (case/format-insensitive) name."""
    target = canonicalize_name(name)
    for dist in iter_installed(search_path=search_path):
        if dist.canonical_name == target:
            return dist
    return None


def installed_index(search_path: list[str] | None = None) -> dict:
    """Build a canonical-name -> InstalledDistribution map in one scan.

    The resolver needs to check "is this already installed?" for every
    package it looks at; scanning site-packages fresh for each one (like
    find_installed does) would mean re-walking the directory over and over.
    """
    return {dist.canonical_name: dist for dist in iter_installed(search_path=search_path)}


def parse_requires(dist: InstalledDistribution) -> list[Requirement]:
    """Parsed Requirement objects for a distribution's dependencies."""
    parsed = []
    for raw in dist.requires:
        try:
            parsed.append(Requirement(raw))
        except Exception:
            continue
    return parsed
