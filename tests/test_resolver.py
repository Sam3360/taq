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


def test_multiple_extras_both_pull_in_dependencies(env):
    index = FakeIndex()
    index.add(
        "app",
        "1.0.0",
        requires=[
            'lib-a>=1.0 ; extra == "a"',
            'lib-b>=1.0 ; extra == "b"',
        ],
    )
    index.add("lib-a", "1.0.0")
    index.add("lib-b", "1.0.0")
    resolver = Resolver(env, index=index)

    result = {c.name for c in resolver.resolve(["app[a,b]"])}
    assert result == {"app", "lib-a", "lib-b"}


def test_circular_dependency_does_not_hang(env):
    index = FakeIndex()
    index.add("a", "1.0.0", requires=["b>=1.0"])
    index.add("b", "1.0.0", requires=["a>=1.0"])
    resolver = Resolver(env, index=index)

    result = {c.name: c.version for c in resolver.resolve(["a"])}
    assert result == {"a": "1.0.0", "b": "1.0.0"}


def test_invalid_requirement_string_raises():
    from taq.exceptions import InvalidRequirementError
    from taq.resolver import parse_requirement

    with pytest.raises(InvalidRequirementError):
        parse_requirement("this is not === a valid requirement !!!")


class _FakeInstalledDist:
    def __init__(self, name, version, requires=None):
        self.name = name
        self.version = version
        self.requires = requires or []

    @property
    def canonical_name(self):
        from packaging.utils import canonicalize_name

        return canonicalize_name(self.name)


def test_reuses_already_installed_compatible_package(env):
    """An installed package satisfying the specifier should be reused
    without ever touching the (fake) index for its own release info."""
    index = FakeIndex()
    index.add("foo", "9.9.9")  # if the resolver "cheats" and hits the index, it'd pick this
    installed = {"foo": _FakeInstalledDist("foo", "1.0.0")}
    resolver = Resolver(env, index=index, installed_index=installed)

    result = resolver.resolve(["foo>=1.0"])
    assert len(result) == 1
    assert result[0].version == "1.0.0"
    assert result[0].installed is True
    assert result[0].wheel is None


def test_does_not_reuse_installed_when_it_does_not_satisfy(env):
    index = FakeIndex()
    index.add("foo", "2.0.0")
    installed = {"foo": _FakeInstalledDist("foo", "1.0.0")}
    resolver = Resolver(env, index=index, installed_index=installed)

    result = resolver.resolve(["foo>=2.0"])
    assert result[0].version == "2.0.0"
    assert result[0].installed is False


def test_force_latest_bypasses_installed_reuse(env):
    index = FakeIndex()
    index.add("foo", "1.0.0")
    index.add("foo", "2.0.0")
    installed = {"foo": _FakeInstalledDist("foo", "1.0.0")}
    resolver = Resolver(env, index=index, installed_index=installed)

    # Without force_latest, the installed 1.0.0 satisfies "foo" and is reused.
    reused = resolver.resolve(["foo"])
    assert reused[0].version == "1.0.0"
    assert reused[0].installed is True

    # With force_latest, it must go to the index and pick the newest.
    upgraded = resolver.resolve(["foo"], force_latest={"foo"})
    assert upgraded[0].version == "2.0.0"
    assert upgraded[0].installed is False


def test_transitive_dependency_reused_from_installed(env):
    """A dependency pulled in transitively should also be reused - and its
    own sub-dependencies should come from local metadata, not the index."""
    index = FakeIndex()
    index.add("app", "1.0.0", requires=["lib>=1.0"])
    index.add("lib", "9.9.9")  # should never be picked
    installed = {
        "lib": _FakeInstalledDist("lib", "1.5.0", requires=["deep>=1.0"]),
        "deep": _FakeInstalledDist("deep", "1.0.0"),
    }
    resolver = Resolver(env, index=index, installed_index=installed)

    result = {c.name: c for c in resolver.resolve(["app"])}
    assert result["lib"].version == "1.5.0"
    assert result["lib"].installed is True
    # "deep" came from lib's *local* metadata even though "deep" was never
    # registered in the fake index at all - proving it wasn't fetched remotely.
    assert "deep" in result
