import sys

from taq.scripts import remove_console_script, write_console_script


def test_write_and_remove_console_script(tmp_path):
    scripts_dir = tmp_path / "scripts"
    path = write_console_script("mytool", "mypkg.cli:main", scripts_dir, sys.executable)
    assert path.exists()

    if sys.platform == "win32":
        assert (scripts_dir / "mytool.cmd").exists()
        assert (scripts_dir / "mytool-script.py").exists()
        content = (scripts_dir / "mytool-script.py").read_text()
    else:
        content = path.read_text()

    assert "from mypkg.cli import main" in content
    assert "sys.exit(main())" in content

    removed = remove_console_script("mytool", scripts_dir)
    assert removed
    for p in removed:
        assert not p.exists()
