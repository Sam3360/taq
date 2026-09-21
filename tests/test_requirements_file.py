import pytest

from taq.exceptions import InvalidRequirementError
from taq.requirements_file import parse_requirements_file


def test_basic_parsing(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "requests>=2.0,<3.0",
                "flask==3.0.0  # inline comment",
                "  ",
            ]
        )
    )
    result = parse_requirements_file(req_file)
    assert result == ["requests>=2.0,<3.0", "flask==3.0.0"]


def test_line_continuation(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("requests>=2.0,\\\n<3.0\n")
    result = parse_requirements_file(req_file)
    assert result == ["requests>=2.0,<3.0"]


def test_nested_requirements_file(tmp_path):
    base = tmp_path / "base.txt"
    base.write_text("attrs>=22\n")
    main = tmp_path / "main.txt"
    main.write_text("-r base.txt\nclick>=8\n")

    result = parse_requirements_file(main)
    assert result == ["attrs>=22", "click>=8"]


def test_circular_include_detected(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("-r b.txt\n")
    b.write_text("-r a.txt\n")

    with pytest.raises(InvalidRequirementError):
        parse_requirements_file(a)


def test_missing_file_raises(tmp_path):
    with pytest.raises(InvalidRequirementError):
        parse_requirements_file(tmp_path / "nope.txt")


def test_unsupported_option_raises(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("-e git+https://example.com/repo.git\n")
    with pytest.raises(InvalidRequirementError):
        parse_requirements_file(req_file)


def test_environment_marker_passthrough(tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text('colorama>=0.4 ; platform_system == "Windows"\n')
    result = parse_requirements_file(req_file)
    assert result == ['colorama>=0.4 ; platform_system == "Windows"']
