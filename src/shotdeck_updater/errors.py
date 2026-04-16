"""Updater-specific exceptions."""


class UpdateError(Exception):
    """Base class for updater failures."""


class ConfigError(UpdateError):
    """Raised when local updater configuration is invalid."""


class DownloadError(UpdateError):
    """Raised when metadata or artifacts cannot be downloaded or verified."""


class InstallError(UpdateError):
    """Raised when release activation fails."""


class PatchError(UpdateError):
    """Raised when a patch cannot be applied safely."""


class HealthCheckError(InstallError):
    """Raised when the newly activated release fails health checks."""


class LockUnavailableError(UpdateError):
    """Raised when another updater instance already holds the runtime lock."""
