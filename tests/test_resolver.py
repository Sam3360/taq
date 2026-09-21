import pytest

from taq.environment import current_environment
from taq.exceptions import NoCompatibleWheelError, ResolutionError, VersionNotFoundError
from taq.pypi import PackageInfo, ReleaseFile, ReleaseInfo
from taq.resolver import Resolver


class FakeIndex:
    """A tiny in-memory stand-in for PyPIClient, keyed by lowercase name."""

    def __init__(self):
        self.packages = {}  # name -> {version: {"requires": [...], "has_wheel": bool}}

    def add(self, name, version, requires=None, has_wheel=True):
        self.packages.setdefault(name, {})[version] = {
            "requires": requires or [],
            "has_wheel": has_wheel,
        }

    def _files(self, name, version, has_wheel):
        if not has_wheel:
            return [ReleaseFile(f"{name}-{version}.tar.gz", f"http://x/{name}-{version}.tar.gz", 1, "sdist", "source", None)]
        # Wheel filenames must escape runs of non-alphanumeric chars in the
        # name as a single underscore (PEP 427) - real builders do this too.
        safe_name = name.replace("-", "_")
        filename = f"{safe_name}-{version}-py3-none-any.whl"
        return [ReleaseFile(filename, f"http://x/{filename}", 1, "bdist_wheel", "py3", None, {"sha256": "0" * 64})]

    def get_package_info(self, name):
        versions = self.packages.get(name)
        if not versions:
            from taq.exceptions import PackageNotFoundError

            raise PackageNotFoundError(name)
        releases = {v: self._files(name, v, data["has_wheel"]) for v, data in versions.items()}
        latest = sorted(versions, key=lambda v: tuple(int(p) for p in v.split(".")))[-1]
        return PackageInfo(name, None, None, None, None, None, latest, releases)

    def get_release(self, name, version):
        data = self.packages[name][version]
        return ReleaseInfo(name, version, data["requires"], None, self._files(name, version, data["has_wheel"]))


@pytest.fixture
def env():
    return current_environment()


def test_resolves_single_package(env):
    index = FakeIndex()
    index.add("requests", "2.31.0")
    resolver = Resolver(env, index=index)

    result = resolver.resolve(["requests"])
    assert len(result) == 1
    assert result[0].name == "requests"
    assert result[0].version == "2.31.0"


def test_picks_latest_matching_specifier(env):
    index = FakeIndex()
    for v in ["1.0.0", "1.5.0", "2.0.0"]:
        index.add("foo", v)
    resolver = Resolver(env, index=index)

    result = resolver.resolve(["foo<2.0.0"])
    assert result[0].version == "1.5.0"


def test_resolves_transitive_dependencies(env):
    index = FakeIndex()
    index.add("app", "1.0.0", requires=["lib>=1.0"])
    index.add("lib", "1.0.0")
    index.add("lib", "1.2.0")
    resolver = Resolver(env, index=index)

    result = {c.name: c.version for c in resolver.resolve(["app"])}
    assert result == {"app": "1.0.0", "lib": "1.2.0"}


def test_intersects_specifiers_from_multiple_requirers(env):
    index = FakeIndex()
    index.add("app", "1.0.0", requires=["lib<1.5"])
    index.add("lib", "1.0.0")
    index.add("lib", "1.2.0")
    index.add("lib", "2.0.0")
    resolver = Resolver(env, index=index)

    result = {c.name: c.version for c in resolver.resolve(["app", "lib>=1.0"])}
    assert result == {"app": "1.0.0", "lib": "1.2.0"}


def test_conflicting_requirements_raise(env):
    index = FakeIndex()
    index.add("app", "1.0.0", requires=["lib==1.0.0"])
    index.add("lib", "1.0.0")
    index.add("lib", "2.0.0")
    resolver = Resolver(env, index=index)

    with pytest.raises(ResolutionError):
        resolver.resolve(["app", "lib==2.0.0"])


def test_no_matching_version_raises(env):
    index = FakeIndex()
    index.add("foo", "1.0.0")
    resolver = Resolver(env, index=index)

    with pytest.raises(VersionNotFoundError):
        resolver.resolve(["foo>=2.0.0"])


def test_no_wheel_available_raises(env):
    index = FakeIndex()
    index.add("foo", "1.0.0", has_wheel=False)
    resolver = Resolver(env, index=index)

    with pytest.raises(NoCompatibleWheelError):
        resolver.resolve(["foo"])


def test_environment_marker_excludes_dependency(env):
    index = FakeIndex()
    index.add("app", "1.0.0", requires=['colorama>=0.4 ; platform_system == "NoSuchOS"'])
    resolver = Resolver(env, index=index)

    result = {c.name for c in resolver.resolve(["app"])}
    assert result == {"app"}


def test_extras_pull_in_conditional_dependency(env):
    index = FakeIndex()
    index.add("app", "1.0.0", requires=['extra-lib>=1.0 ; extra == "fancy"'])
    index.add("extra-lib", "1.0.0")
    resolver = Resolver(env, index=index)

    result = {c.name for c in resolver.resolve(["app[fancy]"])}
    assert result == {"app", "extra-lib"}


def test_extras_not_requested_are_skipped(env):
    index = FakeIndex()
    index.add("app", "1.0.0", requires=['extra-lib>=1.0 ; extra == "fancy"'])
    index.add("extra-lib", "1.0.0")
    resolver = Resolver(env, index=index)

    result = {c.name for c in resolver.resolve(["app"])}
    assert result == {"app"}
