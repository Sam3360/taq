from __future__ import annotations

import argparse

from .. import dist_info
from ..environment import Environment


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("list", help="List installed packages")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, env: Environment) -> int:
    dists = dist_info.iter_installed(search_path=[str(env.site_packages)])
    if not dists:
        print(f"No packages installed in {env.describe()}")
        return 0

    name_width = max(len(d.name) for d in dists)
    name_width = max(name_width, len("Package"))
    print(f"{'Package'.ljust(name_width)}  Version")
    print(f"{'-' * name_width}  -------")
    for dist in dists:
        print(f"{dist.name.ljust(name_width)}  {dist.version}")
    return 0
