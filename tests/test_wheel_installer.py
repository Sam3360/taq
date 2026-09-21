import sys
import zipfile
from pathlib import Path

import pytest

from taq import dist_info
from taq.environment import Environment
from taq.exceptions import InstallError
from taq.uninstall_support import remove_distribution
from taq.wheel_installer import install_wheel


def _make_fake_wheel(directory: Path, name="examplepkg", version="1.0.0", with_script=True) -> Path:
    wheel_path = directory / f"{name}-{version}-py3-none-any.whl"
    dist_info_dir = f"{name}-{version}.dist-info"

    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr(f"{name}/__init__.py", 'def main():\n    print("hello from examplepkg")\n')
        zf.writestr(f"{name}/mod.py", "VALUE = 42\n")
        zf.writestr(
            f"{dist_info_dir}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nSummary: A fake test package\n",
        )
        zf.writestr(
            f"{dist_info_dir}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: taq-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        if with_script:
            zf.writestr(f"{dist_info_dir}/entry_points.txt", f"[console_scripts]\n{name}-cli = {name}:main\n")
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


def test_install_wheel_lays_out_files(tmp_path, env):
    wheel_path = _make_fake_wheel(tmp_path)
    result = install_wheel(wheel_path, env)

    assert result.name == "examplepkg"
    assert result.version == "1.0.0"
    assert (env.site_packages / "examplepkg" / "__init__.py").exists()
    assert (env.site_packages / "examplepkg" / "mod.py").exists()
    assert (env.site_packages / "examplepkg-1.0.0.dist-info" / "METADATA").exists()
    assert (env.site_packages / "examplepkg-1.0.0.dist-info" / "INSTALLER").read_text().strip() == "taq"
    assert (env.site_packages / "examplepkg-1.0.0.dist-info" / "RECORD").exists()


def test_install_wheel_generates_console_script(tmp_path, env):
    wheel_path = _make_fake_wheel(tmp_path)
    install_wheel(wheel_path, env)

    if sys.platform == "win32":
        assert (env.scripts / "examplepkg-cli.cmd").exists()
        assert (env.scripts / "examplepkg-cli-script.py").exists()
    else:
        script = env.scripts / "examplepkg-cli"
        assert script.exists()
        assert script.stat().st_mode & 0o111  # executable bits set
        assert "examplepkg" in script.read_text()


def test_installed_package_is_discoverable(tmp_path, env):
    wheel_path = _make_fake_wheel(tmp_path)
    install_wheel(wheel_path, env)

    dist = dist_info.find_installed("examplepkg", search_path=[str(env.site_packages)])
    assert dist is not None
    assert dist.version == "1.0.0"
    assert dist.summary == "A fake test package"


def test_record_contains_correct_hashes(tmp_path, env):
    wheel_path = _make_fake_wheel(tmp_path)
    install_wheel(wheel_path, env)

    record = (env.site_packages / "examplepkg-1.0.0.dist-info" / "RECORD").read_text()
    assert "examplepkg/__init__.py,sha256=" in record
    assert "examplepkg/mod.py,sha256=" in record


def test_uninstall_removes_pycache_too(tmp_path, env):
    """Regression test: leftover __pycache__/*.pyc must not survive
    uninstall, or the package dir becomes an accidental namespace package."""
    wheel_path = _make_fake_wheel(tmp_path)
    install_wheel(wheel_path, env)

    # Simulate what happens after `import examplepkg`: bytecode caches
    # appear that were never part of the wheel or RECORD.
    pycache_dir = env.site_packages / "examplepkg" / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "__init__.cpython-312.pyc").write_bytes(b"fake bytecode")
    (pycache_dir / "mod.cpython-312.pyc").write_bytes(b"fake bytecode")

    dist = dist_info.find_installed("examplepkg", search_path=[str(env.site_packages)])
    remove_distribution(dist, env, quiet=True)

    assert not (env.site_packages / "examplepkg").exists()


def test_uninstall_removes_all_files(tmp_path, env):
    wheel_path = _make_fake_wheel(tmp_path)
    install_wheel(wheel_path, env)

    dist = dist_info.find_installed("examplepkg", search_path=[str(env.site_packages)])
    removed = remove_distribution(dist, env, quiet=True)

    assert len(removed) > 0
    assert not (env.site_packages / "examplepkg" / "__init__.py").exists()
    assert not (env.site_packages / "examplepkg-1.0.0.dist-info").exists()
    if sys.platform == "win32":
        assert not (env.scripts / "examplepkg-cli.cmd").exists()
    else:
        assert not (env.scripts / "examplepkg-cli").exists()
    assert dist_info.find_installed("examplepkg", search_path=[str(env.site_packages)]) is None


def test_install_rejects_zip_slip(tmp_path, env):
    wheel_path = tmp_path / "evil-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("evil-1.0.0.dist-info/METADATA", "Name: evil\nVersion: 1.0.0\n")
        zf.writestr("evil-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n")
        zf.writestr("evil-1.0.0.dist-info/RECORD", "")
        zf.writestr("../../etc/evil.py", "print('pwned')\n")

    with pytest.raises(InstallError):
        install_wheel(wheel_path, env)


def test_install_rejects_bad_zip(tmp_path, env):
    bad = tmp_path / "broken-1.0.0-py3-none-any.whl"
    bad.write_text("not a zip file")
    with pytest.raises(InstallError):
        install_wheel(bad, env)


def test_install_rejects_missing_dist_info(tmp_path, env):
    wheel_path = tmp_path / "nodist-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("nodist/__init__.py", "")
    with pytest.raises(InstallError):
        install_wheel(wheel_path, env)
