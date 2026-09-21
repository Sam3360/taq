"""Generates executable launchers for ``console_scripts`` entry points.

On POSIX this is a plain shebang script marked executable. On Windows,
where the shell doesn't honour shebangs, we write a small ``.exe``-free
launcher pair: a ``-script.py`` file plus a ``.cmd`` wrapper, which is
enough for the command to work from ``cmd.exe`` and PowerShell once the
Scripts directory is on PATH. This mirrors what setuptools did for years
before it started vendoring compiled launcher stubs, and keeps TAQ free of
prebuilt binary blobs.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

TEMPLATE = '''#!{python_executable}
# -*- coding: utf-8 -*-
import re
import sys
from {module} import {func_path_import}
if __name__ == "__main__":
    sys.argv[0] = re.sub(r"(-script\\.pyw|\\.exe)?$", "", sys.argv[0])
    sys.exit({entry_call}())
'''

CMD_TEMPLATE = '@echo off\r\n"{python_executable}" "%~dp0{script_name}-script.py" %*\r\n'


def _split_entry_point(value: str) -> tuple[str, str]:
    """'pkg.module:func' or 'pkg.module:Class.func' -> (module, callable expr)."""
    module, _, func = value.partition(":")
    return module.strip(), func.strip()


def write_console_script(name: str, entry_point: str, scripts_dir: Path, python_executable: str) -> Path:
    """Write a launcher for one console_scripts entry point. Returns its path(s) root."""
    module, func = _split_entry_point(entry_point)

    body = TEMPLATE.format(
        python_executable=python_executable,
        module=module,
        func_path_import=func.split(".")[0],
        entry_call=func,
    )

    scripts_dir.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        script_path = scripts_dir / f"{name}-script.py"
        script_path.write_text(body, encoding="utf-8")
        cmd_path = scripts_dir / f"{name}.cmd"
        cmd_path.write_text(
            CMD_TEMPLATE.format(python_executable=python_executable, script_name=name),
            encoding="utf-8",
        )
        return script_path
    else:
        script_path = scripts_dir / name
        script_path.write_text(body, encoding="utf-8")
        mode = script_path.stat().st_mode
        script_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return script_path


def remove_console_script(name: str, scripts_dir: Path) -> list[Path]:
    """Remove launcher file(s) for a console script. Returns what was deleted."""
    removed = []
    candidates = [scripts_dir / name]
    if os.name == "nt":
        candidates = [
            scripts_dir / f"{name}.cmd",
            scripts_dir / f"{name}-script.py",
            scripts_dir / f"{name}.exe",
        ]
    for path in candidates:
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed
