"""Minimal requirements.txt parsing.

Supports what covers the common case: one requirement per line, comments,
blank lines, line continuations, and nested files via ``-r other.txt``.
Pip-specific options we don't implement (``-e``, ``--hash``, index options,
etc.) are reported with a clear message rather than silently ignored.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import InvalidRequirementError

_UNSUPPORTED_PREFIXES = ("-e ", "--editable", "-f ", "--find-links", "--index-url", "-i ", "--extra-index-url")


def parse_requirements_file(path: Path) -> list[str]:
    """Return the list of requirement strings found in a requirements file."""
    requirements: list[str] = []
    _parse_into(Path(path), requirements, seen=set())
    return requirements


def _parse_into(path: Path, out: list[str], seen: set) -> None:
    resolved = path.resolve()
    if resolved in seen:
        raise InvalidRequirementError(f"Circular -r include detected at {path}")
    seen.add(resolved)

    if not path.exists():
        raise InvalidRequirementError(f"Requirements file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    lines = _join_continuations(raw.splitlines())

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("-r ") or stripped.startswith("--requirement "):
            nested = stripped.split(None, 1)[1].strip()
            _parse_into(path.parent / nested, out, seen)
            continue

        if any(stripped.startswith(prefix) for prefix in _UNSUPPORTED_PREFIXES):
            raise InvalidRequirementError(
                f"{path}:{lineno}: option '{stripped.split()[0]}' isn't supported by taq yet"
            )

        if stripped.startswith("-"):
            raise InvalidRequirementError(f"{path}:{lineno}: unrecognized option '{stripped}'")

        # Strip inline comments (a ' #' that isn't part of a URL fragment).
        comment_at = stripped.find(" #")
        if comment_at != -1:
            stripped = stripped[:comment_at].strip()

        out.append(stripped)


def _join_continuations(lines: list[str]) -> list[str]:
    joined: list[str] = []
    buffer = ""
    for line in lines:
        if line.endswith("\\"):
            buffer += line[:-1]
        else:
            joined.append(buffer + line)
            buffer = ""
    if buffer:
        joined.append(buffer)
    return joined
