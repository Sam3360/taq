# TAQ

**T**ool **A**cquisition & **Q**uick-install — a small, from-scratch Python package manager.

TAQ talks to PyPI directly, resolves dependencies, and installs/uninstalls wheels.
It doesn't wrap pip and doesn't require pip to be installed. It's meant to be a
real, everyday-usable alternative for the common cases, not a full pip
replacement.

```
$ taq install requests
Resolving 1 requirement(s) for /usr/bin/python3 (virtual environment) ...
Will install:
  certifi 2026.7.22
  charset-normalizer 3.5.1
  idna 3.20
  requests 2.34.2
  urllib3 2.8.0
Downloading requests-2.34.2-py3-none-any.whl ...
Installed requests 2.34.2
```

## Install

```
pip install taq        # or pipx install taq, or however you like to get CLIs
```

(TAQ itself is packaged and distributed the normal way. Once it's on your
machine, it never needs pip again.)

## Usage

```
taq install requests              # install a package
taq install "flask>=3,<4"         # with a version specifier
taq install "requests[socks]"     # with extras
taq install -r requirements.txt   # from a requirements file
taq install -U requests           # upgrade to the latest allowed version
taq uninstall requests            # remove a package
taq upgrade requests              # same as install -U, for already-installed packages
taq list                          # what's installed
taq show requests                 # metadata for one package
taq deps requests                 # dependency tree, from local metadata (no network)
taq outdated                      # what has a newer release on PyPI
```

Run `taq <command> --help` for the full option list of each command.

TAQ always operates on **the interpreter it's currently running under** — the
same way `python -m pip` does. Activate a virtualenv, then run `taq`, and
that's the environment it installs into. There's no separate `--target`
concept to configure; `taq list` prints which environment it's using so it's
always obvious.

## How it works

- **Index access**: talks to the [PyPI JSON API](https://warehouse.pypa.io/api-reference/json.html)
  over plain `urllib` — no `requests`, no shelling out to pip.
- **Dependency resolution**: a straightforward resolver built on `packaging`
  (the same library pip and setuptools vendor for PEP 440/508 parsing). For
  each package it picks a version that satisfies every specifier seen so
  far, preferring an **already-installed compatible version** over hitting
  the network at all. This is **not** a full backtracking/SAT solver like
  modern pip — see [Limitations](#limitations).
- **Dependency metadata**: read from the standard `Requires-Dist` field —
  either PyPI's per-release JSON metadata (for packages being newly
  installed) or the `Requires` field of an already-installed distribution
  (via `importlib.metadata`, when reusing it). Nothing about any specific
  package is hardcoded.
- **Reuse over reinstall**: if a package that already satisfies a
  requirement is installed, TAQ reuses it as-is — no re-download, no
  version churn — for both direct and transitive dependencies. `taq
  install -U <name>` / `taq upgrade <name>` force a fresh lookup only for
  the package(s) named, not their whole dependency tree.
- **Conflicts**: when two requirements can't both be satisfied — including
  through transitive dependencies — TAQ resolves nothing and reports the
  conflict clearly, rather than partially installing and pretending it
  worked.
- **Circular dependencies**: handled naturally — once a package has been
  resolved, revisiting it (even from a cycle) is a no-op if the existing
  choice still satisfies the new constraint, so cycles terminate instead of
  looping.
- **Installing**: downloads a wheel, verifies its SHA-256 against the index's
  metadata, unpacks it (PEP 427), and writes `RECORD`/`INSTALLER` itself
  (PEP 376). Console-script entry points get a real launcher generated in
  the environment's scripts/bin directory.
- **Uninstalling**: reads the `RECORD` file TAQ wrote at install time and
  deletes exactly those files (plus their bytecode caches), then prunes any
  directories that are now empty.
- **No arbitrary code execution**: installing a wheel is just moving files
  around — TAQ never executes the package's own code to install it. (There's
  no sdist/source-build support, which is also *why*: building from source
  means running the project's build backend, and that's a deliberately
  bigger piece of surface area than v1/v2 take on.)

## What's implemented

- `install` — single packages, version specifiers (`==`, `>=`, `<`, ranges),
  extras (`pkg[extra]`), environment markers, `-r requirements.txt`,
  transitive dependency resolution, reuse of already-satisfied dependencies,
  `--upgrade`, `--dry-run`
- `uninstall` — with confirmation prompt (`-y` to skip)
- `upgrade` — resolve and install the latest version(s) that still satisfy
  the given specifier, without touching unrelated dependencies unnecessarily
- `list` — installed packages and versions
- `show` — name, version, summary, location, requires, required-by
- `deps` — a package's dependency tree, read from local metadata (works
  offline; flags anything not installed or that doesn't satisfy its
  constraint)
- `outdated` — compares installed versions against the latest on PyPI
  (checked concurrently, so it's fast even with a lot of packages)
- Cross-platform: works on Linux/macOS/Windows, doesn't assume a shell, and
  respects `%LOCALAPPDATA%`/`XDG_CACHE_HOME` for its download cache
- Downloads are cached locally and verified by SHA-256 before install;
  interrupted downloads/installs don't leave partial files behind (writes go
  through a temp file/dir and are only "committed" on success, with rollback
  on failure)

## Limitations

Being upfront about what this doesn't do:

- **Wheels only.** If a project only ships an sdist (no wheel for your
  platform/interpreter), TAQ will tell you rather than trying to build it.
  Building from source (running `setup.py`/PEP 517 build backends) is real
  scope for a future release, not something to bolt on quickly.
- **Resolver has no backtracking.** For the vast majority of dependency
  trees this doesn't matter, but a genuine diamond conflict (two packages
  that need mutually-incompatible versions of a third) will surface as an
  error instead of being cleverly resolved. pip's modern resolver does
  full backtracking; TAQ's is intentionally simpler.
- **No `.data/headers` or `.data/data` wheel directories.** These are rare
  in practice (most packages only use `purelib`/`platlib`/`scripts`); TAQ
  skips them rather than guess at a destination.
- **No lockfiles, no virtualenv creation, no build backend.** TAQ manages
  packages in an environment you already have; it doesn't create
  environments or build packages.
- **Single index only** (defaults to PyPI; `--index-url` points it
  elsewhere, but there's no multi-index fallback yet).
- **`taq deps` shows raw declared dependencies**, including ones gated by
  extras you didn't request (this matches what `taq show`'s `Requires` field
  and `pip show` do) — it doesn't try to guess which extras are "in use."

## Development

```
pip install -e ".[test]"
pytest
```

The project layout is a flat `src/taq/` package with one module per concern
(`pypi.py`, `resolver.py`, `wheel_installer.py`, `dist_info.py`, ...) and a
`commands/` package with one file per CLI subcommand — the goal is that
adding a new command or a new piece of package-management functionality
later is a matter of adding a file, not restructuring the project.
