from __future__ import annotations

import argparse

from packaging.utils import canonicalize_name

from .. import dist_info
from ..environment import Environment
from ..exceptions import DistributionNotFoundError
from ..pypi import PyPIClient
from ..resolver import Resolver, parse_requirement
from ..uninstall_support import remove_distribution
from ..wheel_installer import download, install_wheel


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("upgrade", help="Upgrade installed packages to the latest matching version")
    parser.add_argument("packages", nargs="+", help="Package names/specifiers to upgrade")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be upgraded without doing it")
    parser.add_argument("--index-url", default=None)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, env: Environment) -> int:
    search_path = [str(env.site_packages)]
    installed_idx = dist_info.installed_index(search_path=search_path)

    force_latest = set()
    for name in args.packages:
        base_req = parse_requirement(name)
        if installed_idx.get(canonicalize_name(base_req.name)) is None:
            raise DistributionNotFoundError(
                f"'{base_req.name}' is not installed in {env.describe()} - use 'taq install' instead"
            )
        force_latest.add(base_req.name)

    index = PyPIClient(args.index_url) if args.index_url else PyPIClient()
    resolver = Resolver(env, index=index, installed_index=installed_idx)
    # Everything named on the command line is force-refreshed against the
    # index; anything pulled in transitively is still reused if an
    # already-installed copy satisfies the (possibly updated) constraints.
    candidates = resolver.resolve(args.packages, force_latest=force_latest)

    did_something = False
    for candidate in sorted(candidates, key=lambda c: c.name.lower()):
        installed = installed_idx.get(candidate.canonical_name)
        if installed is not None and installed.version == candidate.version:
            print(f"  {candidate.name} {installed.version} is already the latest matching version")
            continue

        did_something = True
        action = f"{installed.version} -> {candidate.version}" if installed else f"(new) {candidate.version}"
        print(f"  {candidate.name}: {action}")
        if args.dry_run:
            continue

        if installed is not None:
            remove_distribution(installed, env, quiet=True)
        wheel_path = download(candidate.wheel)
        result = install_wheel(wheel_path, env)
        print(f"Installed {result.name} {result.version}")

    if not did_something:
        print("Nothing to upgrade.")
    return 0
