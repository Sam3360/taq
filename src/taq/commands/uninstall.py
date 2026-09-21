from __future__ import annotations

import argparse

from .. import dist_info
from ..environment import Environment
from ..exceptions import DistributionNotFoundError
from ..uninstall_support import remove_distribution


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("uninstall", help="Remove installed packages")
    parser.add_argument("packages", nargs="+", help="Package name(s) to remove")
    parser.add_argument("-y", "--yes", action="store_true", help="Don't ask for confirmation")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, env: Environment) -> int:
    dists = []
    for name in args.packages:
        dist = dist_info.find_installed(name, search_path=[str(env.site_packages)])
        if dist is None:
            raise DistributionNotFoundError(f"'{name}' is not installed in {env.describe()}")
        dists.append(dist)

    print("Will remove:")
    for dist in dists:
        print(f"  {dist.name} {dist.version}  ({dist.location})")

    if not args.yes:
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    for dist in dists:
        remove_distribution(dist, env)

    return 0
