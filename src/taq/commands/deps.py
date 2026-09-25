"""`taq deps` - show what an installed package depends on.

Reads entirely from local metadata (no network), so it also works offline
and doubles as a quick way to see whether a dependency graph is actually
satisfied on disk.
"""

from __future__ import annotations

import argparse

from packaging.utils import canonicalize_name

from .. import dist_info
from ..dist_info import InstalledDistribution
from ..environment import Environment
from ..exceptions import DistributionNotFoundError


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "deps", help="Show a package's dependencies, from installed metadata (no network)"
    )
    parser.add_argument("package")
    parser.add_argument("--flat", action="store_true", help="List direct dependencies only, no tree")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, env: Environment) -> int:
    index = dist_info.installed_index(search_path=[str(env.site_packages)])
    key = canonicalize_name(args.package)
    root = index.get(key)
    if root is None:
        raise DistributionNotFoundError(f"'{args.package}' is not installed in {env.describe()}")

    print(f"{root.name} {root.version}")
    reqs = dist_info.parse_requires(root)
    if not reqs:
        print("  (no dependencies)")
        return 0

    if args.flat:
        for req in reqs:
            dep = index.get(canonicalize_name(req.name))
            print(f"  {req.name} {req.specifier or ''}  {_status(req, dep, False)}".rstrip())
    else:
        _print_tree(reqs, index, prefix="", seen={key})
    return 0


def _print_tree(reqs, index: dict, prefix: str, seen: set) -> None:
    for i, req in enumerate(reqs):
        last = i == len(reqs) - 1
        branch = "└── " if last else "├── "
        key = canonicalize_name(req.name)
        dep = index.get(key)
        is_cycle = key in seen
        print(f"{prefix}{branch}{req.name} {req.specifier or ''}  {_status(req, dep, is_cycle)}".rstrip())
        if dep is not None and not is_cycle:
            child_reqs = dist_info.parse_requires(dep)
            if child_reqs:
                child_prefix = prefix + ("    " if last else "│   ")
                _print_tree(child_reqs, index, child_prefix, seen | {key})


def _status(req, dep: "InstalledDistribution | None", is_cycle: bool) -> str:
    if is_cycle:
        return f"(circular, see above - installed {dep.version if dep else '?'})"
    if dep is None:
        return "(not installed)"
    if req.specifier and not req.specifier.contains(dep.version, prereleases=True):
        return f"(installed {dep.version}, does not satisfy)"
    return f"(installed {dep.version})"
