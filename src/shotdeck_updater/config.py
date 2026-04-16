"""Updater configuration loading and path derivation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .identity import IdentityPolicy


def _command_list(value: Any, field_name: str) -> list[list[str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{field_name} must be an array")
    commands: list[list[str]] = []
    for item in value:
        if not isinstance(item, list) or not item or not all(isinstance(part, str) and part for part in item):
            raise ConfigError(f"{field_name} items must be non-empty string arrays")
        commands.append(item)
    return commands


@dataclass(slots=True)
class HookConfig:
    pre_install: list[list[str]] = field(default_factory=list)
    post_install: list[list[str]] = field(default_factory=list)
    rollback: list[list[str]] = field(default_factory=list)
    health_check: list[list[str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "HookConfig":
        payload = payload or {}
        return cls(
            pre_install=_command_list(payload.get("pre_install"), "hooks.pre_install"),
            post_install=_command_list(payload.get("post_install"), "hooks.post_install"),
            rollback=_command_list(payload.get("rollback"), "hooks.rollback"),
            health_check=_command_list(payload.get("health_check"), "hooks.health_check"),
        )


@dataclass(slots=True)
class UpdaterConfig:
    product: str = "shotdeck"
    install_root: Path = Path("/opt/shotdeck")
    log_file: Path = Path("/var/log/shotdeck/updater.log")
    manifest_url: str = ""
    channel: str = "stable"
    policy: str = "auto-apply"
    service_name: str = "shotdeck"
    public_key_path: Path = Path("/etc/shotdeck/update-signing-key.pem")
    lock_path: Path = Path("/run/lock/shotdeck-updater.lock")
    request_timeout_seconds: int = 60
    retained_releases: int = 2
    hooks: HookConfig = field(default_factory=HookConfig)
    identity_policy: IdentityPolicy = field(default_factory=IdentityPolicy)

    @classmethod
    def from_file(cls, path: Path, *, allow_missing: bool = False) -> "UpdaterConfig":
        if not path.exists():
            if allow_missing:
                return cls()
            raise ConfigError(f"Updater config not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity_payload = payload.get("identity", {})
        config = cls(
            product=str(payload.get("product", "shotdeck")).lower(),
            install_root=Path(payload.get("install_root", "/opt/shotdeck")),
            log_file=Path(payload.get("log_file", "/var/log/shotdeck/updater.log")),
            manifest_url=str(payload.get("manifest_url", "")),
            channel=str(payload.get("channel", "stable")).lower(),
            policy=str(payload.get("policy", "auto-apply")).lower(),
            service_name=str(payload.get("service_name", "shotdeck")),
            public_key_path=Path(payload.get("public_key_path", "/etc/shotdeck/update-signing-key.pem")),
            lock_path=Path(payload.get("lock_path", "/run/lock/shotdeck-updater.lock")),
            request_timeout_seconds=int(payload.get("request_timeout_seconds", 60)),
            retained_releases=int(payload.get("retained_releases", 2)),
            hooks=HookConfig.from_dict(payload.get("hooks")),
            identity_policy=IdentityPolicy(
                include_cpu_serial=bool(identity_payload.get("include_cpu_serial", True)),
                include_mac_addresses=bool(identity_payload.get("include_mac_addresses", True)),
                include_machine_id=bool(identity_payload.get("include_machine_id", True)),
                interface_allowlist=tuple(identity_payload.get("interface_allowlist", ())),
                interface_denylist=tuple(identity_payload.get("interface_denylist", ("lo",))),
                expose_raw_identifiers=bool(identity_payload.get("expose_raw_identifiers", False)),
                hardware_group_override=identity_payload.get("hardware_group_override"),
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.policy not in {"check-only", "download-only", "auto-apply"}:
            raise ConfigError("policy must be one of: check-only, download-only, auto-apply")
        if self.request_timeout_seconds < 1:
            raise ConfigError("request_timeout_seconds must be positive")
        if self.retained_releases < 1:
            raise ConfigError("retained_releases must be at least 1")
        if not self.manifest_url:
            raise ConfigError("manifest_url must be configured")

    @property
    def releases_dir(self) -> Path:
        return self.install_root / "releases"

    @property
    def cache_dir(self) -> Path:
        return self.install_root / "update-cache"

    @property
    def state_dir(self) -> Path:
        return self.install_root / "state"

    @property
    def work_dir(self) -> Path:
        return self.install_root / "work"

    @property
    def current_link(self) -> Path:
        return self.install_root / "current"

    @property
    def previous_link(self) -> Path:
        return self.install_root / "previous"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "updater-state.json"


DEFAULT_CONFIG_PATH = Path("/etc/shotdeck/updater.json")
