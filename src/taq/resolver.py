"""Dependency resolution.

This is intentionally a *simple* resolver, not a full SAT-style backtracker
like modern pip: for each package we pick a version that satisfies every
specifier seen so far - preferring an already-installed compatible version
over hitting the network at all, and otherwise the newest version PyPI
offers. If a later requirement can't be satisfied by a version already
picked, we retry with the narrowed constraint; if that also fails, we raise
a clear conflict error rather than backtracking through the whole graph.

In practice this handles the large majority of real dependency trees fine.
Genuinely conflicting/diamond-dependency situations that need backtracking
are a known limitation (see README).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .dist_info import InstalledDistribution
from .environment import Environment
from .exceptions import (
    InvalidRequirementError,
    NoCompatibleWheelError,
    PackageNotFoundError,
    ResolutionError,
    TaqError,
    VersionNotFoundError,
)
from .pypi import PyPIClient, ReleaseFile

# Defensive cap on how many requirements we'll process in one resolve() call.
# Real dependency graphs are nowhere near this size; this only exists so a
# pathological/self-referential metadata graph fails loudly instead of
# hanging forever.
MAX_QUEUE_ITERATIONS = 20_000


@dataclass
class Candidate:
    """A package version chosen by the resolver, ready to install."""

    name: str
    version: str
    wheel: ReleaseFile | None = None
    installed: bool = False  # True if we're reusing an already-installed copy
    requested_directly: bool = False
    specifier: SpecifierSet = field(default_factory=SpecifierSet)
    requires_dist: list = field(default_factory=list)

    @property
    def canonical_name(self) -> str:
        return canonicalize_name(self.name)


@dataclass
class _PackageState:
    specifier: SpecifierSet = field(default_factory=SpecifierSet)
    extras: set = field(default_factory=set)
    requested_directly: bool = False


def parse_requirement(text: str) -> Requirement:
    try:
        return Requirement(text.strip())
    except Exception as exc:
        raise InvalidRequirementError(f"Invalid requirement '{text}': {exc}") from exc


def best_wheel(files: list[ReleaseFile], tags: list[Tag]) -> ReleaseFile | None:
    """Pick the best-matching wheel for this interpreter/platform, if any."""
    wheels = [f for f in files if f.is_wheel]
    if not wheels:
        return None

    tag_rank = {tag: i for i, tag in enumerate(tags)}
    best = None
    best_rank = None
    for wheel in wheels:
        for wheel_tag in _tags_from_filename(wheel.filename):
            rank = tag_rank.get(wheel_tag)
            if rank is None:
                continue
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best = wheel
    return best


def _tags_from_filename(filename: str):
    from packaging.utils import parse_wheel_filename

    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except Exception:
        return []
    return tags


class Resolver:
    def __init__(
        self,
        environment: Environment,
        index: PyPIClient | None = None,
        installed_index: dict[str, InstalledDistribution] | None = None,
    ) -> None:
        self.env = environment
        self.index = index or PyPIClient()
        self._tags = environment.compatible_tags()
        self._marker_env = default_environment()
        self._package_info_cache: dict = {}
        self._installed = installed_index or {}
        # Set for the duration of a resolve() call:
        self._prefer_installed = True
        self._force_latest: frozenset = frozenset()

    def resolve(
        self,
        requirement_strings: list[str],
        prefer_installed: bool = True,
        force_latest=frozenset(),
    ) -> list[Candidate]:
        """Resolve a list of requirement strings into installable candidates.

        prefer_installed: if True (the default), a package that's already
            installed and satisfies the accumulated specifier is reused
            as-is instead of fetching/selecting a version from the index -
            this is what makes `install` skip redundant downloads and
            `upgrade` leave unrelated dependencies alone.
        force_latest: canonical package names that should always be
            re-resolved against the index even if an installed copy would
            satisfy the specifier (used for the packages explicitly named
            in an --upgrade / `taq upgrade` request).
        """
        self._prefer_installed = prefer_installed
        self._force_latest = frozenset(canonicalize_name(n) for n in force_latest)

        states: dict[str, _PackageState] = {}
        chosen: dict[str, Candidate] = {}
        queue: list[tuple[Requirement, bool]] = []

        for text in requirement_strings:
            queue.append((parse_requirement(text), True))

        iterations = 0
        while queue:
            iterations += 1
            if iterations > MAX_QUEUE_ITERATIONS:
                raise ResolutionError(
                    "Dependency resolution didn't converge (too many requirements "
                    "processed) - this usually means a package's metadata has a "
                    "self-referential dependency loop that keeps growing"
                )

            req, is_direct = queue.pop(0)
            key = canonicalize_name(req.name)

            if req.marker is not None and not self._marker_matches(req):
                continue

            state = states.setdefault(key, _PackageState())
            state.specifier &= req.specifier
            state.extras |= set(req.extras)
            state.requested_directly = state.requested_directly or is_direct

            already = chosen.get(key)
            if already is not None and req.specifier.contains(already.version, prereleases=True):
                # Existing choice still satisfies the new constraint - this
                # is also how a dependency cycle terminates: the second time
                # around, the package is already chosen and compatible, so
                # we just stop instead of re-expanding its dependencies.
                if is_direct:
                    already.requested_directly = True
                continue

            if already is not None:
                # The new constraint narrows things past our previous pick
                # (this can happen when a package is requested both
                # directly and transitively, and they're processed in an
                # order that reveals the tighter constraint second). Try
                # re-selecting under the combined, narrower specifier rather
                # than failing outright - only a genuine conflict between
                # two irreconcilable constraints is a hard error.
                try:
                    candidate = self._select_version(key, req.name, state.specifier)
                except TaqError as exc:
                    raise ResolutionError(
                        f"Version conflict for '{req.name}': already resolved to "
                        f"{already.version}, but '{req}' requires {req.specifier} ({exc})"
                    ) from exc
                candidate.requested_directly = state.requested_directly
                chosen[key] = candidate
                if candidate.version != already.version:
                    self._queue_dependencies(candidate.requires_dist, state, queue)
                continue

            candidate = self._select_version(key, req.name, state.specifier)
            candidate.requested_directly = state.requested_directly
            chosen[key] = candidate
            self._queue_dependencies(candidate.requires_dist, state, queue)

        for key, candidate in chosen.items():
            candidate.specifier = states[key].specifier
        return list(chosen.values())

    def _queue_dependencies(self, requires_dist: list[str], state: "_PackageState", queue: list) -> None:
        for dep_text in requires_dist:
            dep_req = parse_requirement(dep_text)
            if dep_req.marker is not None:
                if not self._marker_matches(dep_req, extras=state.extras):
                    continue
                # Already evaluated with the right extras context - clear it
                # so the top-of-loop check doesn't re-evaluate it later
                # without that context and wrongly filter it out.
                dep_req.marker = None
            queue.append((dep_req, False))

    def _marker_matches(self, req: Requirement, extras: set | None = None) -> bool:
        if req.marker is None:
            return True
        extras = extras or {""}
        for extra in extras or {""}:
            env = dict(self._marker_env)
            env["extra"] = extra
            if req.marker.evaluate(environment=env):
                return True
        return False

    def _select_version(self, key: str, name: str, specifier: SpecifierSet) -> Candidate:
        # Reuse an already-installed, compatible copy instead of touching
        # the network at all - both for speed and so `install`/`upgrade`
        # don't churn packages that don't need to change.
        if self._prefer_installed and key not in self._force_latest:
            local = self._installed.get(key)
            if local is not None and specifier.contains(local.version, prereleases=True):
                return Candidate(
                    name=local.name,
                    version=local.version,
                    wheel=None,
                    installed=True,
                    requires_dist=list(local.requires),
                )

        info = self._get_package_info(name)
        all_versions = list(info.releases.keys())

        # SpecifierSet.filter() implements the official PEP 440 prerelease
        # rule: prereleases are excluded unless nothing else matches.
        matching = list(specifier.filter(all_versions, prereleases=None))

        def _sort_key(version_str: str) -> Version:
            try:
                return Version(version_str)
            except InvalidVersion:
                return Version("0")

        matching.sort(key=_sort_key, reverse=True)

        if not matching:
            raise VersionNotFoundError(
                f"No version of '{name}' matches '{specifier or 'any'}'"
            )

        for version_str in matching:
            files = info.files_for(version_str)
            wheel = best_wheel(files, self._tags)
            if wheel is not None:
                release = self.index.get_release(info.name, version_str)
                return Candidate(
                    name=info.name,
                    version=version_str,
                    wheel=wheel,
                    requires_dist=list(release.requires_dist),
                )

        raise NoCompatibleWheelError(
            f"'{name}' has matching releases ({', '.join(matching[:5])}) but none ship "
            f"a wheel compatible with this interpreter/platform "
            f"(Python {'.'.join(str(p) for p in self.env.version_info)}, "
            f"{self.env.python_executable})"
        )

    def _get_package_info(self, name: str):
        key = canonicalize_name(name)
        if key not in self._package_info_cache:
            try:
                self._package_info_cache[key] = self.index.get_package_info(name)
            except PackageNotFoundError:
                raise
        return self._package_info_cache[key]
