"""Typed JSON models for release manifests and device allowlists."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .errors import ManifestValidationError

SUPPORTED_SCHEMA_VERSION = "1.0"


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _require_str(value, field_name)


def _require_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int):
        raise ManifestValidationError(f"{field_name} must be an integer")
    return value


def _require_hex_sha256(value: Any, field_name: str) -> str:
    text = _require_str(value, field_name).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ManifestValidationError(f"{field_name} must be a 64-character SHA-256 hex digest")
    return text


def _normalize_slug_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestValidationError(f"{field_name} must be an array")
    normalized: list[str] = []
    for item in value:
        normalized.append(_require_str(item, field_name).lower())
    return sorted(set(normalized))


def _normalize_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestValidationError(f"{field_name} must be an array")
    return [_require_str(item, field_name) for item in value]


def _validate_version(value: str, field_name: str) -> str:
    try:
        Version(value)
    except InvalidVersion as exc:
        raise ManifestValidationError(f"{field_name} must be a valid PEP 440 version") from exc
    return value


@dataclass(slots=True)
class ManifestSignature:
    algorithm: str
    key_id: str
    value: str

    def __post_init__(self) -> None:
        self.algorithm = _require_str(self.algorithm, "signature.algorithm")
        self.key_id = _require_str(self.key_id, "signature.key_id")
        self.value = _require_str(self.value, "signature.value")
        if self.algorithm.lower() != "ed25519":
            raise ManifestValidationError("Only Ed25519 signatures are supported")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManifestSignature":
        return cls(
            algorithm=payload.get("algorithm", ""),
            key_id=payload.get("key_id", ""),
            value=payload.get("value", ""),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "value": self.value,
        }


@dataclass(slots=True)
class ArtifactRef:
    url: str
    sha256: str
    size: int
    filename: str
    install_tree_sha256: str | None = None

    def __post_init__(self) -> None:
        self.url = _require_str(self.url, "artifact.url")
        self.sha256 = _require_hex_sha256(self.sha256, "artifact.sha256")
        self.size = _require_int(self.size, "artifact.size")
        if self.size < 0:
            raise ManifestValidationError("artifact.size must be zero or greater")
        self.filename = _require_str(self.filename, "artifact.filename")
        if "/" in self.filename or self.filename in {".", ".."}:
            raise ManifestValidationError("artifact.filename must be a basename")
        if self.install_tree_sha256 is not None:
            self.install_tree_sha256 = _require_hex_sha256(
                self.install_tree_sha256,
                "artifact.install_tree_sha256",
            )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactRef":
        return cls(
            url=payload.get("url", ""),
            sha256=payload.get("sha256", ""),
            size=payload.get("size", 0),
            filename=payload.get("filename", ""),
            install_tree_sha256=payload.get("install_tree_sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
            "filename": self.filename,
        }
        if self.install_tree_sha256:
            payload["install_tree_sha256"] = self.install_tree_sha256
        return payload


@dataclass(slots=True)
class PatchArtifactRef(ArtifactRef):
    from_version: str = ""
    to_version: str = ""
    base_tree_sha256: str = ""
    target_tree_sha256: str = ""
    strategy: str = "tar-overlay"
    removed_paths: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        ArtifactRef.__post_init__(self)
        self.from_version = _validate_version(self.from_version, "patch.from_version")
        self.to_version = _validate_version(self.to_version, "patch.to_version")
        self.base_tree_sha256 = _require_hex_sha256(self.base_tree_sha256, "patch.base_tree_sha256")
        self.target_tree_sha256 = _require_hex_sha256(
            self.target_tree_sha256,
            "patch.target_tree_sha256",
        )
        self.strategy = _require_str(self.strategy, "patch.strategy")
        if self.strategy != "tar-overlay":
            raise ManifestValidationError("Only tar-overlay patch strategy is supported")
        normalized_paths: list[str] = []
        for path in self.removed_paths:
            text = _require_str(path, "patch.removed_paths")
            if text.startswith("/") or ".." in text.split("/"):
                raise ManifestValidationError("patch.removed_paths contains an unsafe path")
            normalized_paths.append(text)
        self.removed_paths = sorted(set(normalized_paths))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatchArtifactRef":
        return cls(
            url=payload.get("url", ""),
            sha256=payload.get("sha256", ""),
            size=payload.get("size", 0),
            filename=payload.get("filename", ""),
            install_tree_sha256=payload.get("install_tree_sha256"),
            from_version=payload.get("from_version", ""),
            to_version=payload.get("to_version", ""),
            base_tree_sha256=payload.get("base_tree_sha256", ""),
            target_tree_sha256=payload.get("target_tree_sha256", ""),
            strategy=payload.get("strategy", "tar-overlay"),
            removed_paths=payload.get("removed_paths", []),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = ArtifactRef.to_dict(self)
        payload.update(
            {
                "from_version": self.from_version,
                "to_version": self.to_version,
                "base_tree_sha256": self.base_tree_sha256,
                "target_tree_sha256": self.target_tree_sha256,
                "strategy": self.strategy,
                "removed_paths": list(self.removed_paths),
            }
        )
        return payload


@dataclass(slots=True)
class AllowlistRef:
    url: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        self.url = _require_str(self.url, "allowlist.url")
        self.sha256 = _require_hex_sha256(self.sha256, "allowlist.sha256")
        self.size = _require_int(self.size, "allowlist.size")
        if self.size < 0:
            raise ManifestValidationError("allowlist.size must be zero or greater")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AllowlistRef":
        return cls(
            url=payload.get("url", ""),
            sha256=payload.get("sha256", ""),
            size=payload.get("size", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "sha256": self.sha256, "size": self.size}


@dataclass(slots=True)
class RolloutRules:
    channels: list[str] = field(default_factory=list)
    hardware_groups: list[str] = field(default_factory=list)
    device_fingerprints: list[str] = field(default_factory=list)
    allowlist_tags: list[str] = field(default_factory=list)
    current_version: str | None = None
    staged_rollout_percentage: int | None = None
    allow_downgrade: bool = False
    allowlist: AllowlistRef | None = None

    def __post_init__(self) -> None:
        self.channels = _normalize_slug_list(self.channels, "rollout.channels")
        self.hardware_groups = _normalize_slug_list(self.hardware_groups, "rollout.hardware_groups")
        self.device_fingerprints = sorted(
            {
                _require_hex_sha256(item, "rollout.device_fingerprints")
                for item in self.device_fingerprints
            }
        )
        self.allowlist_tags = _normalize_slug_list(self.allowlist_tags, "rollout.allowlist_tags")
        if self.current_version is not None:
            try:
                SpecifierSet(_require_str(self.current_version, "rollout.current_version"))
            except InvalidSpecifier as exc:
                raise ManifestValidationError("rollout.current_version must be a valid specifier set") from exc
        if self.staged_rollout_percentage is not None:
            self.staged_rollout_percentage = _require_int(
                self.staged_rollout_percentage,
                "rollout.staged_rollout_percentage",
            )
            if not 0 < self.staged_rollout_percentage <= 100:
                raise ManifestValidationError("staged rollout percentage must be between 1 and 100")

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RolloutRules":
        payload = payload or {}
        allowlist_payload = payload.get("allowlist")
        return cls(
            channels=payload.get("channels", []),
            hardware_groups=payload.get("hardware_groups", []),
            device_fingerprints=payload.get("device_fingerprints", []),
            allowlist_tags=payload.get("allowlist_tags", []),
            current_version=payload.get("current_version"),
            staged_rollout_percentage=payload.get("staged_rollout_percentage"),
            allow_downgrade=bool(payload.get("allow_downgrade", False)),
            allowlist=AllowlistRef.from_dict(allowlist_payload) if allowlist_payload else None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "channels": list(self.channels),
            "hardware_groups": list(self.hardware_groups),
            "device_fingerprints": list(self.device_fingerprints),
            "allowlist_tags": list(self.allowlist_tags),
            "allow_downgrade": self.allow_downgrade,
        }
        if self.current_version:
            payload["current_version"] = self.current_version
        if self.staged_rollout_percentage is not None:
            payload["staged_rollout_percentage"] = self.staged_rollout_percentage
        if self.allowlist:
            payload["allowlist"] = self.allowlist.to_dict()
        return payload


@dataclass(slots=True)
class RollbackInfo:
    keep_versions: int = 2
    allow_manual_rollback: bool = True
    health_check_timeout_seconds: int = 20

    def __post_init__(self) -> None:
        self.keep_versions = _require_int(self.keep_versions, "rollback.keep_versions")
        self.health_check_timeout_seconds = _require_int(
            self.health_check_timeout_seconds,
            "rollback.health_check_timeout_seconds",
        )
        if self.keep_versions < 1:
            raise ManifestValidationError("rollback.keep_versions must be at least 1")
        if self.health_check_timeout_seconds < 1:
            raise ManifestValidationError("rollback.health_check_timeout_seconds must be positive")

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RollbackInfo":
        payload = payload or {}
        return cls(
            keep_versions=payload.get("keep_versions", 2),
            allow_manual_rollback=bool(payload.get("allow_manual_rollback", True)),
            health_check_timeout_seconds=payload.get("health_check_timeout_seconds", 20),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "keep_versions": self.keep_versions,
            "allow_manual_rollback": self.allow_manual_rollback,
            "health_check_timeout_seconds": self.health_check_timeout_seconds,
        }


@dataclass(slots=True)
class ReleaseManifest:
    schema_version: str
    product: str
    channel: str
    version: str
    released_at: str
    min_updater_version: str
    full_artifact: ArtifactRef
    patch_artifacts: list[PatchArtifactRef] = field(default_factory=list)
    rollout: RolloutRules = field(default_factory=RolloutRules)
    rollback: RollbackInfo = field(default_factory=RollbackInfo)
    notes: list[str] = field(default_factory=list)
    signature: ManifestSignature | None = None

    def __post_init__(self) -> None:
        self.schema_version = _require_str(self.schema_version, "schema_version")
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ManifestValidationError(
                f"Unsupported schema_version {self.schema_version!r}; expected {SUPPORTED_SCHEMA_VERSION!r}"
            )
        self.product = _require_str(self.product, "product").lower()
        self.channel = _require_str(self.channel, "channel").lower()
        self.version = _validate_version(self.version, "version")
        self.released_at = _require_str(self.released_at, "released_at")
        self.min_updater_version = _validate_version(self.min_updater_version, "min_updater_version")
        self.notes = _normalize_string_list(self.notes, "notes")
        self.patch_artifacts = list(self.patch_artifacts)
        for patch in self.patch_artifacts:
            if patch.to_version != self.version:
                raise ManifestValidationError(
                    "Each patch artifact must target the same version as the manifest"
                )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReleaseManifest":
        signature_payload = payload.get("signature")
        return cls(
            schema_version=payload.get("schema_version", ""),
            product=payload.get("product", ""),
            channel=payload.get("channel", ""),
            version=payload.get("version", ""),
            released_at=payload.get("released_at", ""),
            min_updater_version=payload.get("min_updater_version", ""),
            full_artifact=ArtifactRef.from_dict(payload.get("full_artifact", {})),
            patch_artifacts=[
                PatchArtifactRef.from_dict(item)
                for item in payload.get("patch_artifacts", [])
            ],
            rollout=RolloutRules.from_dict(payload.get("rollout")),
            rollback=RollbackInfo.from_dict(payload.get("rollback")),
            notes=payload.get("notes", []),
            signature=ManifestSignature.from_dict(signature_payload) if signature_payload else None,
        )

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "channel": self.channel,
            "version": self.version,
            "released_at": self.released_at,
            "min_updater_version": self.min_updater_version,
            "full_artifact": self.full_artifact.to_dict(),
            "patch_artifacts": [patch.to_dict() for patch in self.patch_artifacts],
            "rollout": self.rollout.to_dict(),
            "rollback": self.rollback.to_dict(),
            "notes": list(self.notes),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.unsigned_dict()
        if self.signature:
            payload["signature"] = self.signature.to_dict()
        return payload


@dataclass(slots=True)
class AllowlistEntry:
    fingerprint: str
    short_id: str | None = None
    channel: str | None = None
    hardware_group: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str | None = None

    def __post_init__(self) -> None:
        self.fingerprint = _require_hex_sha256(self.fingerprint, "allowlist.devices[].fingerprint")
        self.short_id = _optional_str(self.short_id, "allowlist.devices[].short_id")
        self.channel = _optional_str(self.channel, "allowlist.devices[].channel")
        if self.channel:
            self.channel = self.channel.lower()
        self.hardware_group = _optional_str(
            self.hardware_group,
            "allowlist.devices[].hardware_group",
        )
        if self.hardware_group:
            self.hardware_group = self.hardware_group.lower()
        self.tags = _normalize_slug_list(self.tags, "allowlist.devices[].tags")
        self.notes = _optional_str(self.notes, "allowlist.devices[].notes")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AllowlistEntry":
        return cls(
            fingerprint=payload.get("fingerprint", ""),
            short_id=payload.get("short_id"),
            channel=payload.get("channel"),
            hardware_group=payload.get("hardware_group"),
            tags=payload.get("tags", []),
            notes=payload.get("notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"fingerprint": self.fingerprint, "tags": list(self.tags)}
        if self.short_id:
            payload["short_id"] = self.short_id
        if self.channel:
            payload["channel"] = self.channel
        if self.hardware_group:
            payload["hardware_group"] = self.hardware_group
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass(slots=True)
class AllowlistDocument:
    schema_version: str
    product: str
    updated_at: str
    devices: list[AllowlistEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.schema_version = _require_str(self.schema_version, "schema_version")
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ManifestValidationError(
                f"Unsupported allowlist schema_version {self.schema_version!r}"
            )
        self.product = _require_str(self.product, "product").lower()
        self.updated_at = _require_str(self.updated_at, "updated_at")
        unique: dict[str, AllowlistEntry] = {}
        for entry in self.devices:
            unique[entry.fingerprint] = entry
        self.devices = sorted(unique.values(), key=lambda item: item.fingerprint)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AllowlistDocument":
        return cls(
            schema_version=payload.get("schema_version", ""),
            product=payload.get("product", ""),
            updated_at=payload.get("updated_at", ""),
            devices=[AllowlistEntry.from_dict(item) for item in payload.get("devices", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "updated_at": self.updated_at,
            "devices": [entry.to_dict() for entry in self.devices],
        }

    def find_device(self, fingerprint: str) -> AllowlistEntry | None:
        normalized = _require_hex_sha256(fingerprint, "fingerprint")
        for entry in self.devices:
            if entry.fingerprint == normalized:
                return entry
        return None
