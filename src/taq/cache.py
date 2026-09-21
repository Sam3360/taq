"""A small on-disk cache for downloaded wheels/sdists and index responses.

Nothing fancy: files are keyed by a hash of their download URL, so repeated
installs of the same release don't hit the network again.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def cache_dir() -> Path:
    """Return (and create) TAQ's cache directory, respecting the platform."""
    override = os.environ.get("TAQ_CACHE_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / "taq" / "Cache"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        path = Path(base) / "taq"
    path.mkdir(parents=True, exist_ok=True)
    return path


def wheel_cache_path(url: str, filename: str) -> Path:
    """Deterministic local path for a downloaded distribution file."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    directory = cache_dir() / "wheels" / digest
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename
