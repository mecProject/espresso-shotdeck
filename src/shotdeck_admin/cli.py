"""Admin CLI for safe public-repo artifacts and metadata."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from shotdeck_manifest import AllowlistDocument, AllowlistEntry, ReleaseManifest, sign_manifest, verify_manifest
from shotdeck_updater.patching import build_patch_archive


def _import_crypto():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return serialization, Ed25519PrivateKey


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shotdeck-admin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    keypair = subparsers.add_parser("create-keypair", help="Create an Ed25519 signing key pair")
    keypair.add_argument("--private-key", type=Path, required=True)
    keypair.add_argument("--public-key", type=Path, required=True)

    sign = subparsers.add_parser("sign-manifest", help="Sign an unsigned manifest JSON file")
    sign.add_argument("--input", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify-manifest", help="Verify a signed manifest JSON file")
    verify.add_argument("--input", type=Path, required=True)
    verify.add_argument("--public-key", type=Path, required=True)

    add_device = subparsers.add_parser("add-device", help="Add or update a device in an allowlist")
    add_device.add_argument("--allowlist", type=Path, required=True)
    add_device.add_argument("--product", default="shotdeck")
    add_device.add_argument("--identity-json", type=Path, required=True)
    add_device.add_argument("--channel")
    add_device.add_argument("--hardware-group")
    add_device.add_argument("--tag", action="append", default=[])
    add_device.add_argument("--notes")

    patch = subparsers.add_parser("build-patch", help="Build a tar-overlay patch archive")
    patch.add_argument("--from-dir", type=Path, required=True)
    patch.add_argument("--to-dir", type=Path, required=True)
    patch.add_argument("--output", type=Path, required=True)
    patch.add_argument("--metadata-output", type=Path)

    return parser


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "create-keypair":
        serialization, Ed25519PrivateKey = _import_crypto()
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        args.private_key.parent.mkdir(parents=True, exist_ok=True)
        args.public_key.parent.mkdir(parents=True, exist_ok=True)
        args.private_key.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        args.public_key.write_bytes(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        return 0

    if args.command == "sign-manifest":
        manifest = ReleaseManifest.from_dict(json.loads(args.input.read_text(encoding="utf-8")))
        signed = sign_manifest(manifest, args.private_key.read_bytes())
        _write_json(args.output, signed.to_dict())
        return 0

    if args.command == "verify-manifest":
        manifest = ReleaseManifest.from_dict(json.loads(args.input.read_text(encoding="utf-8")))
        verify_manifest(manifest, args.public_key.read_bytes())
        print(json.dumps({"verified": True, "version": manifest.version}, indent=2))
        return 0

    if args.command == "add-device":
        identity_payload = json.loads(args.identity_json.read_text(encoding="utf-8"))
        fingerprint = str(identity_payload["device_fingerprint"])
        short_id = identity_payload.get("device_short_id")
        hardware_group = args.hardware_group or identity_payload.get("hardware_group")
        entry = AllowlistEntry(
            fingerprint=fingerprint,
            short_id=short_id,
            channel=args.channel or identity_payload.get("channel"),
            hardware_group=hardware_group,
            tags=args.tag,
            notes=args.notes,
        )
        if args.allowlist.exists():
            allowlist = AllowlistDocument.from_dict(json.loads(args.allowlist.read_text(encoding="utf-8")))
            devices = [item for item in allowlist.devices if item.fingerprint != entry.fingerprint]
        else:
            allowlist = AllowlistDocument(
                schema_version="1.0",
                product=args.product,
                updated_at=datetime.now(timezone.utc).isoformat(),
                devices=[],
            )
            devices = []
        devices.append(entry)
        updated = AllowlistDocument(
            schema_version="1.0",
            product=allowlist.product,
            updated_at=datetime.now(timezone.utc).isoformat(),
            devices=devices,
        )
        _write_json(args.allowlist, updated.to_dict())
        return 0

    if args.command == "build-patch":
        metadata = build_patch_archive(args.from_dir, args.to_dir, args.output)
        payload = metadata.to_dict()
        if args.metadata_output:
            _write_json(args.metadata_output, payload)
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
