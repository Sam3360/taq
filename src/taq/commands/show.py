from __future__ import annotations

import argparse

from .. import dist_info
from ..environment import Environment
from ..exceptions import DistributionNotFoundError


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("show", help="Show details about an installed package")
    parser.add_argument("package", help="Package name")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, env: Environment) -> int:
    search_path = [str(env.site_packages)]
    dist = dist_info.find_installed(args.package, search_path=search_path)
    if dist is None:
        raise DistributionNotFoundError(f"'{args.package}' is not installed in {env.describe()}")

    required_by = []
    for other in dist_info.iter_installed(search_path=search_path):
        if other.canonical_name == dist.canonical_name:
            continue
        for req in dist_info.parse_requires(other):
            if req.name and req.name.lower().replace("_", "-") == dist.canonical_name:
                required_by.append(other.name)
                break

    print(f"Name: {dist.name}")
    print(f"Version: {dist.version}")
    print(f"Summary: {dist.summary or ''}")
    print(f"Location: {dist.location.parent}")
    print(f"Installer: {dist.installer or 'unknown'}")
    requires = [r.name for r in dist_info.parse_requires(dist)]
    print(f"Requires: {', '.join(sorted(set(requires))) or '(none)'}")
    print(f"Required-by: {', '.join(sorted(set(required_by))) or '(none)'}")
    return 0
