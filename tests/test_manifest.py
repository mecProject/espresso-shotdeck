from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from shotdeck_manifest import (
    AllowlistDocument,
    AllowlistEntry,
    ArtifactRef,
    ManifestSignatureError,
    ReleaseManifest,
    RollbackInfo,
    RolloutRules,
    sign_manifest,
    verify_manifest,
)


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


def test_allowlist_blank_optional_fields_are_ignored() -> None:
    allowlist = AllowlistDocument.from_dict(
        {
            "schema_version": "1.0",
            "product": "shotdeck",
            "updated_at": "2026-04-28T20:00:00Z",
            "devices": [
                {
                    "fingerprint": "a" * 64,
                    "short_id": "aaaaaaaaaaaa",
                    "channel": "stable",
                    "hardware_group": "",
                    "tags": [],
                    "notes": "",
                }
            ],
        }
    )

    entry = allowlist.devices[0]
    assert entry.hardware_group is None
    assert entry.notes is None
    assert "hardware_group" not in entry.to_dict()
    assert "notes" not in entry.to_dict()


def test_allowlist_entry_omits_empty_optional_fields() -> None:
    payload = AllowlistEntry(
        fingerprint="b" * 64,
        short_id="bbbbbbbbbbbb",
        channel="stable",
        hardware_group="",
        tags=[],
        notes="",
    ).to_dict()

    assert payload == {
        "fingerprint": "b" * 64,
        "short_id": "bbbbbbbbbbbb",
        "channel": "stable",
        "tags": [],
    }
