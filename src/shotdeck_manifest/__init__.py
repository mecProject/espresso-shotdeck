"""Manifest models, signatures, and targeting rules for Shotdeck updates."""

from .errors import ManifestError, ManifestSignatureError, ManifestValidationError
from .models import (
    AllowlistDocument,
    AllowlistEntry,
    AllowlistRef,
    ArtifactRef,
    ManifestSignature,
    PatchArtifactRef,
    ReleaseManifest,
    RolloutRules,
    RollbackInfo,
)
from .signing import canonical_json_bytes, sign_manifest, verify_manifest
from .targeting import ApplicabilityDecision, DeviceContext, evaluate_targeting

__all__ = [
    "AllowlistDocument",
    "AllowlistEntry",
    "AllowlistRef",
    "ApplicabilityDecision",
    "ArtifactRef",
    "DeviceContext",
    "ManifestError",
    "ManifestSignature",
    "ManifestSignatureError",
    "ManifestValidationError",
    "PatchArtifactRef",
    "ReleaseManifest",
    "RollbackInfo",
    "RolloutRules",
    "canonical_json_bytes",
    "evaluate_targeting",
    "sign_manifest",
    "verify_manifest",
]
