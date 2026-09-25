"""The ``taq`` command line entry point."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .commands import deps, install, list_cmd, outdated, show, uninstall, upgrade
from .environment import current_environment
from .exceptions import TaqError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taq",
        description="TAQ - Tool Acquisition & Quick-install. A small package manager for PyPI.",
    )
    parser.add_argument("--version", action="version", version=f"taq {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    install.add_parser(subparsers)
    uninstall.add_parser(subparsers)
    upgrade.add_parser(subparsers)
    list_cmd.add_parser(subparsers)
    show.add_parser(subparsers)
    outdated.add_parser(subparsers)
    deps.add_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    env = current_environment()

    try:
        return args.func(args, env)
    except TaqError as exc:
        print(f"taq: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ntaq: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
