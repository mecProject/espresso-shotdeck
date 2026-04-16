"""High-level update workflow used by CLI commands and systemd timers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from shotdeck_manifest import (
    AllowlistDocument,
    ApplicabilityDecision,
    DeviceContext,
    PatchArtifactRef,
    ReleaseManifest,
    evaluate_targeting,
    verify_manifest,
)

from .config import UpdaterConfig
from .download import download_to_path, fetch_bytes, fetch_json
from .errors import ConfigError, DownloadError
from .identity import collect_identity
from .installer import InstallOutcome, ReleaseInstaller
from .patching import patch_is_eligible
from .storage import ensure_directory, sha256_file
from .system import CommandRunner
from . import __version__ as updater_version


@dataclass(slots=True)
class CheckResult:
    manifest: ReleaseManifest
    allowlist: AllowlistDocument | None
    decision: ApplicabilityDecision
    selected_patch: PatchArtifactRef | None

    @property
    def selected_artifact_filename(self) -> str:
        if self.selected_patch:
            return self.selected_patch.filename
        return self.manifest.full_artifact.filename

    @property
    def selected_artifact_url(self) -> str:
        if self.selected_patch:
            return self.selected_patch.url
        return self.manifest.full_artifact.url

    @property
    def selected_artifact_sha256(self) -> str:
        if self.selected_patch:
            return self.selected_patch.sha256
        return self.manifest.full_artifact.sha256

    @property
    def selected_artifact_size(self) -> int:
        if self.selected_patch:
            return self.selected_patch.size
        return self.manifest.full_artifact.size

    def to_dict(self) -> dict[str, object]:
        payload = {
            "applicable": self.decision.applicable,
            "reason": self.decision.reason,
            "manifest_version": self.manifest.version,
            "channel": self.manifest.channel,
            "artifact_kind": "patch" if self.selected_patch else "full",
            "artifact_filename": self.selected_artifact_filename if self.decision.applicable else None,
        }
        if self.decision.staged_rollout_bucket is not None:
            payload["staged_rollout_bucket"] = self.decision.staged_rollout_bucket
        return payload


class UpdaterClient:
    def __init__(
        self,
        config: UpdaterConfig,
        *,
        installer: ReleaseInstaller | None = None,
        runner: CommandRunner | None = None,
        logger=None,
    ) -> None:
        self.config = config
        self.runner = runner or CommandRunner()
        self.installer = installer or ReleaseInstaller(config, runner=self.runner, logger=logger)
        self.logger = logger

    def _log(self, level: str, message: str, *args: object) -> None:
        if self.logger is not None:
            getattr(self.logger, level)(message, *args)

    def _load_manifest(self) -> ReleaseManifest:
        manifest_payload = fetch_json(self.config.manifest_url, timeout=self.config.request_timeout_seconds)
        manifest = ReleaseManifest.from_dict(manifest_payload)
        verify_manifest(manifest, self.config.public_key_path.read_bytes())
        return manifest

    def _load_allowlist(self, manifest: ReleaseManifest) -> AllowlistDocument | None:
        allowlist_ref = manifest.rollout.allowlist
        if allowlist_ref is None:
            return None
        raw_bytes = fetch_bytes(allowlist_ref.url, timeout=self.config.request_timeout_seconds)
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        if len(raw_bytes) != allowlist_ref.size:
            raise DownloadError(
                f"Allowlist size mismatch: expected {allowlist_ref.size}, got {len(raw_bytes)}"
            )
        if actual_sha != allowlist_ref.sha256:
            raise DownloadError(
                f"Allowlist checksum mismatch: expected {allowlist_ref.sha256}, got {actual_sha}"
            )
        return AllowlistDocument.from_dict(json.loads(raw_bytes.decode("utf-8")))

    def _build_context(self, allowlist: AllowlistDocument | None) -> DeviceContext:
        identity = collect_identity(self.config.identity_policy)
        current_release = self.installer.current_release()
        current_version = current_release.version if current_release else "0"
        allowlist_entry = allowlist.find_device(identity.device_fingerprint) if allowlist else None
        return DeviceContext(
            product=self.config.product,
            fingerprint=identity.device_fingerprint,
            short_id=identity.device_short_id,
            hardware_group=identity.hardware_group,
            channel=self.config.channel,
            current_version=current_version,
            updater_version=updater_version,
            allowlist_entry=allowlist_entry,
        )

    def _select_patch(
        self,
        manifest: ReleaseManifest,
        current_version: str,
        current_tree_sha256: str | None,
    ) -> PatchArtifactRef | None:
        if not current_tree_sha256:
            return None
        for patch in manifest.patch_artifacts:
            eligible, _ = patch_is_eligible(current_version, current_tree_sha256, patch)
            if eligible:
                return patch
        return None

    def check(self) -> CheckResult:
        if not self.config.public_key_path.exists():
            raise ConfigError(f"Verification key not found: {self.config.public_key_path}")
        manifest = self._load_manifest()
        allowlist = self._load_allowlist(manifest)
        context = self._build_context(allowlist)
        decision = evaluate_targeting(manifest, context)
        current_release = self.installer.current_release()
        selected_patch = None
        if decision.applicable and current_release:
            selected_patch = self._select_patch(manifest, current_release.version, current_release.tree_sha256)
        return CheckResult(
            manifest=manifest,
            allowlist=allowlist,
            decision=decision,
            selected_patch=selected_patch,
        )

    def download(self, check_result: CheckResult) -> Path:
        if not check_result.decision.applicable:
            raise DownloadError(f"Refusing to download a non-applicable update: {check_result.decision.reason}")
        ensure_directory(self.config.cache_dir)
        destination = self.config.cache_dir / check_result.selected_artifact_filename
        return download_to_path(
            check_result.selected_artifact_url,
            destination,
            expected_sha256=check_result.selected_artifact_sha256,
            expected_size=check_result.selected_artifact_size,
            timeout=self.config.request_timeout_seconds,
        )

    def apply(self, check_result: CheckResult, artifact_path: Path | None = None) -> InstallOutcome:
        if not check_result.decision.applicable:
            raise DownloadError(f"Refusing to apply a non-applicable update: {check_result.decision.reason}")
        artifact_path = artifact_path or self.download(check_result)
        return self.installer.apply_release(
            manifest=check_result.manifest,
            artifact_path=artifact_path,
            patch_artifact=check_result.selected_patch,
        )

    def rollback(self) -> InstallOutcome:
        return self.installer.rollback()

    def unattended(self) -> dict[str, object]:
        result = self.check()
        if self.config.policy == "check-only":
            return {"mode": "check-only", **result.to_dict()}
        if not result.decision.applicable:
            return {"mode": self.config.policy, **result.to_dict()}
        artifact_path = self.download(result)
        if self.config.policy == "download-only":
            return {
                "mode": "download-only",
                "downloaded_artifact": str(artifact_path),
                **result.to_dict(),
            }
        outcome = self.apply(result, artifact_path)
        return {
            "mode": "auto-apply",
            "installed_version": outcome.version,
            "release_path": str(outcome.release_path),
            "artifact_kind": outcome.artifact_kind,
            **result.to_dict(),
        }
