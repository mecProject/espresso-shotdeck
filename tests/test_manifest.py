from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from shotdeck_manifest import ArtifactRef, ManifestSignatureError, ReleaseManifest, RollbackInfo, RolloutRules, sign_manifest, verify_manifest


def make_manifest() -> ReleaseManifest:
    return ReleaseManifest(
        schema_version="1.0",
        product="shotdeck",
        channel="stable",
        version="1.4.0",
        released_at="2026-04-15T12:00:00Z",
        min_updater_version="0.1.0",
        full_artifact=ArtifactRef(
            url="https://updates.example.com/artifacts/shotdeck-1.4.0-full.tar.gz",
            sha256="a" * 64,
            size=1024,
            filename="shotdeck-1.4.0-full.tar.gz",
            install_tree_sha256="b" * 64,
        ),
        patch_artifacts=[],
        rollout=RolloutRules(channels=["stable"], hardware_groups=["raspberry-pi-zero-2-w"]),
        rollback=RollbackInfo(),
        notes=["Improved boot stability"],
    )


def test_manifest_signature_round_trip() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    manifest = sign_manifest(make_manifest(), private_pem)
    verify_manifest(manifest, public_pem)


def test_manifest_tampering_is_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    manifest = sign_manifest(make_manifest(), private_pem)
    manifest.notes.append("tampered")
    with pytest.raises(ManifestSignatureError):
        verify_manifest(manifest, public_pem)
