"""Exception types used across TAQ.

All user-facing errors should be (or wrap into) a TaqError subclass so the
CLI can print a clean message instead of a raw traceback.
"""


class TaqError(Exception):
    """Base class for all expected TAQ errors."""


class PackageNotFoundError(TaqError):
    """Raised when a package name doesn't exist on the index."""


class VersionNotFoundError(TaqError):
    """Raised when no release matches the requested specifier."""


class NoCompatibleWheelError(TaqError):
    """Raised when a release exists but has no wheel for this interpreter/platform."""


class ResolutionError(TaqError):
    """Raised when dependency resolution can't find a consistent set of versions."""


class DistributionNotFoundError(TaqError):
    """Raised when trying to uninstall/show a package that isn't installed."""


class NetworkError(TaqError):
    """Raised when a request to the package index fails."""


class InstallError(TaqError):
    """Raised when unpacking or writing files for a package fails."""


class InvalidRequirementError(TaqError):
    """Raised when a requirement string or requirements file entry is malformed."""
