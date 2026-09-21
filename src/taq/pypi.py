"""A thin client for the PyPI JSON API.

Deliberately uses only the standard library (``urllib``) so TAQ has no
bootstrap dependency on ``requests`` or on pip itself.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .exceptions import NetworkError, PackageNotFoundError

DEFAULT_INDEX_URL = "https://pypi.org/pypi"
USER_AGENT = f"taq/{__version__} (+https://example.com/taq)"
TIMEOUT_SECONDS = 20


@dataclass
class ReleaseFile:
    """A single downloadable file (wheel or sdist) for a release."""

    filename: str
    url: str
    size: int
    packagetype: str  # "bdist_wheel" or "sdist"
    python_version: str
    requires_python: str | None
    digests: dict = field(default_factory=dict)

    @property
    def is_wheel(self) -> bool:
        return self.packagetype == "bdist_wheel" or self.filename.endswith(".whl")

    @property
    def sha256(self) -> str | None:
        return self.digests.get("sha256")


@dataclass
class PackageInfo:
    """Project metadata plus every known release, as returned by PyPI."""

    name: str
    summary: str | None
    home_page: str | None
    author: str | None
    license: str | None
    requires_python: str | None
    latest_version: str
    releases: dict  # version string -> list[ReleaseFile]
    raw: dict = field(repr=False, default_factory=dict)

    def files_for(self, version: str) -> list[ReleaseFile]:
        return self.releases.get(version, [])


@dataclass
class ReleaseInfo:
    """Metadata for one specific version, including its dependencies."""

    name: str
    version: str
    requires_dist: list
    requires_python: str | None
    files: list


class PyPIClient:
    """Talks to the PyPI (or a compatible) JSON API index."""

    def __init__(self, index_url: str = DEFAULT_INDEX_URL) -> None:
        self.index_url = index_url.rstrip("/")

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise PackageNotFoundError(url) from exc
            raise NetworkError(f"HTTP {exc.code} while fetching {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise NetworkError(f"Could not reach {url}: {exc.reason}") from exc

    def get_package_info(self, name: str) -> PackageInfo:
        """Fetch metadata + all releases for a project."""
        url = f"{self.index_url}/{name}/json"
        try:
            data = self._get_json(url)
        except PackageNotFoundError:
            raise PackageNotFoundError(
                f"No package named '{name}' found on {self.index_url}"
            ) from None

        info = data.get("info", {})
        releases: dict[str, list[ReleaseFile]] = {}
        for version, files in data.get("releases", {}).items():
            if not files:
                continue
            releases[version] = [self._parse_file(f) for f in files]

        return PackageInfo(
            name=info.get("name", name),
            summary=info.get("summary"),
            home_page=info.get("home_page") or info.get("project_url"),
            author=info.get("author"),
            license=info.get("license"),
            requires_python=info.get("requires_python"),
            latest_version=info.get("version", ""),
            releases=releases,
            raw=data,
        )

    def get_release(self, name: str, version: str) -> "ReleaseInfo":
        """Fetch metadata scoped to one specific version (for requires_dist)."""
        url = f"{self.index_url}/{name}/{version}/json"
        try:
            data = self._get_json(url)
        except PackageNotFoundError:
            raise PackageNotFoundError(f"{name}=={version} not found on {self.index_url}") from None

        info = data.get("info", {})
        files = [self._parse_file(f) for f in data.get("urls", [])]
        return ReleaseInfo(
            name=info.get("name", name),
            version=info.get("version", version),
            requires_dist=info.get("requires_dist") or [],
            requires_python=info.get("requires_python"),
            files=files,
        )

    def _parse_file(self, data: dict) -> ReleaseFile:
        return ReleaseFile(
            filename=data["filename"],
            url=data["url"],
            size=data.get("size", 0),
            packagetype=data.get("packagetype", ""),
            python_version=data.get("python_version", ""),
            requires_python=data.get("requires_python"),
            digests=data.get("digests", {}),
        )
