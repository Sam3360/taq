from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from packaging.version import InvalidVersion, Version

from .. import dist_info
from ..environment import Environment
from ..exceptions import TaqError
from ..pypi import PyPIClient


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("outdated", help="List installed packages that have a newer release on PyPI")
    parser.add_argument("--index-url", default=None)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, env: Environment) -> int:
    dists = dist_info.iter_installed(search_path=[str(env.site_packages)])
    if not dists:
        print(f"No packages installed in {env.describe()}")
        return 0

    index = PyPIClient(args.index_url) if args.index_url else PyPIClient()
    outdated = []

    def check(dist):
        try:
            info = index.get_package_info(dist.name)
        except TaqError:
            return None
        try:
            current = Version(dist.version)
            latest = Version(info.latest_version)
        except InvalidVersion:
            return None
        if latest > current:
            return (dist.name, dist.version, info.latest_version)
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(check, dist) for dist in dists]
        for future in as_completed(futures):
            result = future.result()
            if result:
                outdated.append(result)

    if not outdated:
        print("Everything is up to date.")
        return 0

    outdated.sort(key=lambda r: r[0].lower())
    name_width = max(max(len(r[0]) for r in outdated), len("Package"))
    print(f"{'Package'.ljust(name_width)}  Installed   Latest")
    for name, current, latest in outdated:
        print(f"{name.ljust(name_width)}  {current.ljust(10)}  {latest}")
    return 0
