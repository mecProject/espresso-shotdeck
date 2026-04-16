"""Errors raised by manifest parsing, validation, and verification."""


class ManifestError(Exception):
    """Base class for manifest and allowlist failures."""


class ManifestValidationError(ManifestError):
    """Raised when a manifest or allowlist does not satisfy schema rules."""


class ManifestSignatureError(ManifestError):
    """Raised when a signature is missing or invalid."""
