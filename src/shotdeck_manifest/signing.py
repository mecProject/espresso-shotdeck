"""Canonical JSON signing and verification for release manifests."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Mapping

from .errors import ManifestSignatureError, ManifestValidationError
from .models import ManifestSignature, ReleaseManifest


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialize a JSON object deterministically for signing."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _import_crypto() -> tuple[Any, Any, Any]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ModuleNotFoundError as exc:
        raise ManifestSignatureError(
            "cryptography is required for manifest signing and verification"
        ) from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def derive_key_id(public_key_pem: bytes) -> str:
    import hashlib

    digest = hashlib.sha256(public_key_pem).hexdigest()
    return digest[:16]


def sign_manifest(
    manifest: ReleaseManifest,
    private_key_pem: bytes,
    key_id: str | None = None,
) -> ReleaseManifest:
    serialization, Ed25519PrivateKey, _ = _import_crypto()
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ManifestSignatureError("Expected an Ed25519 private key")
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = private_key.sign(canonical_json_bytes(manifest.unsigned_dict()))
    manifest.signature = ManifestSignature(
        algorithm="ed25519",
        key_id=key_id or derive_key_id(public_key_pem),
        value=base64.b64encode(signature).decode("ascii"),
    )
    return manifest


def verify_manifest(manifest: ReleaseManifest, public_key_pem: bytes) -> None:
    serialization, _, Ed25519PublicKey = _import_crypto()
    if manifest.signature is None:
        raise ManifestSignatureError("Manifest is missing a signature")
    public_key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(public_key, Ed25519PublicKey):
        raise ManifestSignatureError("Expected an Ed25519 public key")
    expected_key_id = derive_key_id(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    if manifest.signature.key_id != expected_key_id:
        raise ManifestSignatureError(
            f"Manifest key_id {manifest.signature.key_id!r} does not match verification key"
        )
    try:
        signature = base64.b64decode(manifest.signature.value.encode("ascii"), validate=True)
    except ValueError as exc:
        raise ManifestValidationError("Manifest signature is not valid base64") from exc
    try:
        public_key.verify(signature, canonical_json_bytes(manifest.unsigned_dict()))
    except Exception as exc:
        raise ManifestSignatureError("Manifest signature verification failed") from exc


def read_private_key(path: Path) -> bytes:
    return path.read_bytes()


def read_public_key(path: Path) -> bytes:
    return path.read_bytes()
