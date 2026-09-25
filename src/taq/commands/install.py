from __future__ import annotations

import argparse

from .. import dist_info
from ..environment import Environment
from ..exceptions import TaqError
from ..pypi import PyPIClient
from ..requirements_file import parse_requirements_file
from ..resolver import Resolver, parse_requirement
from ..uninstall_support import remove_distribution
from ..wheel_installer import download, install_wheel


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("install", help="Install packages from PyPI")
    parser.add_argument("packages", nargs="*", help="Package names/specifiers, e.g. requests or 'flask>=3,<4'")
    parser.add_argument("-r", "--requirement", action="append", default=[], metavar="FILE",
                         help="Install from a requirements.txt file (repeatable)")
    parser.add_argument("-U", "--upgrade", action="store_true", help="Upgrade packages to the latest allowed version")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and print the plan without installing")
    parser.add_argument("--index-url", default=None, help="Base URL of the PyPI-compatible index to use")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, env: Environment) -> int:
    requirement_strings: list[str] = list(args.packages)
    for req_file in args.requirement:
        requirement_strings.extend(parse_requirements_file(req_file))

    if not requirement_strings:
        print("taq install: nothing to do (pass package names or -r requirements.txt)")
        return 1

    index = PyPIClient(args.index_url) if args.index_url else PyPIClient()
    search_path = [str(env.site_packages)]
    installed_idx = dist_info.installed_index(search_path=search_path)
    resolver = Resolver(env, index=index, installed_index=installed_idx)

    # With --upgrade, the packages named on the command line should always
    # be re-checked against the index (not silently kept at whatever's
    # already installed); everything else can still be reused as-is.
    force_latest = set()
    if args.upgrade:
        for text in args.packages:
            force_latest.add(parse_requirement(text).name)

    print(f"Resolving {len(requirement_strings)} requirement(s) for {env.describe()} ...")
    candidates = resolver.resolve(requirement_strings, force_latest=force_latest)
    candidates.sort(key=lambda c: c.name.lower())

    to_install = []
    already_satisfied = []
    for candidate in candidates:
        installed = installed_idx.get(candidate.canonical_name)
        if candidate.installed or (
            installed is not None
            and not args.upgrade
            and candidate.specifier.contains(installed.version, prereleases=True)
        ):
            already_satisfied.append((candidate, installed))
        else:
            to_install.append((candidate, installed))

    for candidate, installed in already_satisfied:
        version = installed.version if installed else candidate.version
        print(f"  already satisfied: {candidate.name} {version}")

    if not to_install:
        print("Nothing to install.")
        return 0

    print("Will install:")
    for candidate, installed in to_install:
        action = f"{installed.version} -> {candidate.version}" if installed else candidate.version
        print(f"  {candidate.name} {action}")

    if args.dry_run:
        print("(dry run, nothing was installed)")
        return 0

    for candidate, installed in to_install:
        if installed is not None:
            remove_distribution(installed, env, quiet=True)
        print(f"Downloading {candidate.wheel.filename} ...")
        wheel_path = download(candidate.wheel)
        result = install_wheel(wheel_path, env)
        print(f"Installed {result.name} {result.version}")

    return 0
