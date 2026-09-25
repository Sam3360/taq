import sys
import zipfile

import pytest

from taq.commands import deps
from taq.environment import Environment
from taq.exceptions import DistributionNotFoundError
from taq.wheel_installer import install_wheel


def _make_fake_wheel(directory, name="examplepkg", version="1.0.0"):
    wheel_path = directory / f"{name}-{version}-py3-none-any.whl"
    dist_info_dir = f"{name}-{version}.dist-info"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr(f"{name}/__init__.py", "")
        zf.writestr(
            f"{dist_info_dir}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nSummary: A fake leaf package\n",
        )
        zf.writestr(
            f"{dist_info_dir}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: taq-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr(f"{dist_info_dir}/RECORD", "")
    return wheel_path


@pytest.fixture
def env(tmp_path):
    site_packages = tmp_path / "site-packages"
    scripts = tmp_path / "scripts"
    site_packages.mkdir()
    scripts.mkdir()
    return Environment(
        python_executable=sys.executable,
        purelib=site_packages,
        platlib=site_packages,
        scripts=scripts,
        is_virtualenv=True,
        version_info=tuple(sys.version_info[:3]),
    )


class _Args:
    def __init__(self, package, flat=False):
        self.package = package
        self.flat = flat


def test_deps_raises_for_uninstalled_package(env):
    with pytest.raises(DistributionNotFoundError):
        deps.run(_Args("nope"), env)


def test_deps_prints_no_dependencies_message(tmp_path, env, capsys):
    wheel_path = _make_fake_wheel(tmp_path, name="leafpkg")
    install_wheel(wheel_path, env)

    deps.run(_Args("leafpkg"), env)
    out = capsys.readouterr().out
    assert "leafpkg 1.0.0" in out
    assert "no dependencies" in out
