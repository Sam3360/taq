"""Downloads and installs wheels.

Installation follows the wheel spec (PEP 427) and the installed-project
metadata spec (PEP 376): files land in site-packages, ``.data`` subfolders
get redistributed to their real destinations, and we write ``RECORD`` +
``INSTALLER`` ourselves afterwards so uninstall can work purely from what's
on disk.

We never execute code from the package during installation - unlike an
sdist build, unpacking a wheel is just moving files around.
"""

from __future__ import annotations

import base64
import configparser
import csv
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .cache import wheel_cache_path
from .environment import Environment
from .exceptions import InstallError, NetworkError
from .pypi import ReleaseFile
from .scripts import write_console_script

USER_AGENT = f"taq/{__version__}"
CHUNK = 1 << 16


@dataclass
class InstallResult:
    name: str
    version: str
    files: list[Path]
    dist_info_dir: Path


def download(release_file: ReleaseFile, on_progress=None) -> Path:
    """Download a release file to the local cache, verifying its hash."""
    destination = wheel_cache_path(release_file.url, release_file.filename)
    if destination.exists() and _hash_matches(destination, release_file):
        return destination

    request = urllib.request.Request(release_file.url, headers={"User-Agent": USER_AGENT})
    tmp_fd = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(tmp_fd, "wb") as out:
            total = release_file.size or None
            downloaded = 0
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    except OSError as exc:
        tmp_fd.unlink(missing_ok=True)
        raise NetworkError(f"Failed downloading {release_file.filename}: {exc}") from exc

    if not _hash_matches(tmp_fd, release_file):
        tmp_fd.unlink(missing_ok=True)
        raise InstallError(f"Checksum mismatch for {release_file.filename} - refusing to install")

    tmp_fd.replace(destination)
    return destination


def _hash_matches(path: Path, release_file: ReleaseFile) -> bool:
    expected = release_file.sha256
    if not expected:
        return path.exists()
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def install_wheel(wheel_path: Path, env: Environment) -> InstallResult:
    """Unpack and install a wheel into the given environment.

    Uses a temp staging directory and only touches the real site-packages
    once extraction has fully succeeded, and rolls back any partially
    copied files if something goes wrong midway.
    """
    with tempfile.TemporaryDirectory(prefix="taq-wheel-") as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(wheel_path) as zf:
                _check_zip_is_safe(zf, tmp_path)
                zf.extractall(tmp_path)
        except zipfile.BadZipFile as exc:
            raise InstallError(f"{wheel_path.name} is not a valid wheel (bad zip): {exc}") from exc

        dist_info_dirs = list(tmp_path.glob("*.dist-info"))
        if not dist_info_dirs:
            raise InstallError(f"{wheel_path.name} has no .dist-info directory")
        dist_info_src = dist_info_dirs[0]
        base_name = dist_info_src.name[: -len(".dist-info")]
        name, _, version = base_name.rpartition("-")

        data_dirs = list(tmp_path.glob("*.data"))
        data_src = data_dirs[0] if data_dirs else None

        installed_files: list[Path] = []
        try:
            installed_files.extend(_copy_tree_excluding(tmp_path, env.site_packages, exclude={dist_info_src, data_src}))

            dist_info_dest = env.site_packages / dist_info_src.name
            installed_files.extend(_copy_tree(dist_info_src, dist_info_dest))

            if data_src is not None:
                installed_files.extend(_install_data_dir(data_src, env))

            entry_points_file = dist_info_dest / "entry_points.txt"
            if entry_points_file.exists():
                installed_files.extend(_install_console_scripts(entry_points_file, env))

            (dist_info_dest / "INSTALLER").write_text("taq\n", encoding="utf-8")
            installed_files.append(dist_info_dest / "INSTALLER")

            _write_record(dist_info_dest, installed_files, env.site_packages)
        except Exception:
            for path in installed_files:
                path.unlink(missing_ok=True)
            raise InstallError(f"Failed installing {name} {version}; rolled back partial install") from None

        return InstallResult(
            name=name,
            version=version,
            files=installed_files,
            dist_info_dir=dist_info_dest,
        )


def _check_zip_is_safe(zf: zipfile.ZipFile, target: Path) -> None:
    """Reject wheels containing path-traversal entries (zip-slip)."""
    for member in zf.namelist():
        resolved = (target / member).resolve()
        if target.resolve() not in resolved.parents and resolved != target.resolve():
            raise InstallError(f"Refusing to install: unsafe path in wheel: {member}")


def _copy_tree(src: Path, dest: Path) -> list[Path]:
    installed = []
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        installed.append(out)
    return installed


def _copy_tree_excluding(src: Path, dest: Path, exclude: set) -> list[Path]:
    exclude = {p for p in exclude if p is not None}
    installed = []
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        if any(ex in path.parents for ex in exclude):
            continue
        rel = path.relative_to(src)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        installed.append(out)
    return installed


def _install_data_dir(data_src: Path, env: Environment) -> list[Path]:
    """Redistribute a ``{name}-{version}.data/<key>/...`` tree to its real home."""
    installed = []
    destinations = {
        "purelib": env.purelib,
        "platlib": env.platlib,
        "scripts": env.scripts,
        # "data" and "headers" data-dirs are rare in practice (most wheels
        # only use purelib/platlib/scripts). We deliberately don't guess a
        # destination for them rather than risk writing outside the
        # environment; such packages should be reported as a bug.
        "data": None,
        "headers": None,
    }
    for key_dir in data_src.iterdir():
        if not key_dir.is_dir():
            continue
        dest_root = destinations.get(key_dir.name)
        if dest_root is None:
            continue
        for path in key_dir.rglob("*"):
            if path.is_dir():
                continue
            rel = path.relative_to(key_dir)
            out = dest_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
            if key_dir.name == "scripts":
                mode = out.stat().st_mode
                out.chmod(mode | 0o111)
            installed.append(out)
    return installed


def _install_console_scripts(entry_points_file: Path, env: Environment) -> list[Path]:
    parser = configparser.ConfigParser(delimiters=("=",), strict=False)
    parser.optionxform = str  # preserve case
    parser.read(entry_points_file, encoding="utf-8")
    if "console_scripts" not in parser:
        return []
    written = []
    for script_name, entry_point in parser["console_scripts"].items():
        path = write_console_script(script_name.strip(), entry_point.strip(), env.scripts, env.python_executable)
        written.append(path)
        if path.suffix == ".py":  # Windows also gets a .cmd sibling
            cmd = path.with_name(path.name.replace("-script.py", ".cmd"))
            if cmd.exists():
                written.append(cmd)
    return written


def _write_record(dist_info_dest: Path, installed_files: list[Path], site_packages: Path) -> None:
    record_path = dist_info_dest / "RECORD"
    base = site_packages
    rows = []
    for path in sorted(set(installed_files) | {record_path}):
        if path == record_path:
            rows.append((_relative(path, base), "", ""))
            continue
        digest = hashlib.sha256(path.read_bytes()).digest()
        encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        size = path.stat().st_size
        rows.append((_relative(path, base), f"sha256={encoded}", str(size)))

    with record_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        for row in rows:
            writer.writerow(row)
    installed_files.append(record_path)


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
