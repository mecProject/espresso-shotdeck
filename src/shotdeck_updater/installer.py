"""Install, activate, health-check, and roll back release artifacts."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from shotdeck_manifest import PatchArtifactRef, ReleaseManifest

from .config import UpdaterConfig
from .errors import HealthCheckError, InstallError, PatchError
from .patching import apply_patch_archive, patch_is_eligible
from .storage import (
    atomic_symlink_swap,
    directory_tree_sha256,
    ensure_directory,
    prune_releases,
    read_json,
    safe_extract_tarball,
    write_json_atomic,
)
from .system import CommandRunner, ServiceController, SystemctlServiceController, run_hooks


RELEASE_METADATA_NAME = ".shotdeck-release.json"


@dataclass(slots=True)
class InstalledRelease:
    version: str
    path: Path
    tree_sha256: str


@dataclass(slots=True)
class InstallOutcome:
    version: str
    release_path: Path
    artifact_kind: str
    rolled_back: bool = False


class ReleaseInstaller:
    def __init__(
        self,
        config: UpdaterConfig,
        *,
        service_controller: ServiceController | None = None,
        runner: CommandRunner | None = None,
        logger=None,
    ) -> None:
        self.config = config
        self.runner = runner or CommandRunner()
        self.service_controller = service_controller or SystemctlServiceController(
            config.service_name,
            runner=self.runner,
        )
        self.logger = logger

    def _log(self, level: str, message: str, *args: object) -> None:
        if self.logger is not None:
            getattr(self.logger, level)(message, *args)

    def _metadata_path(self, release_dir: Path) -> Path:
        return release_dir / RELEASE_METADATA_NAME

    def current_release(self) -> InstalledRelease | None:
        if not self.config.current_link.exists():
            return None
        target = self.config.current_link.resolve()
        return self._release_from_dir(target)

    def previous_release(self) -> InstalledRelease | None:
        if not self.config.previous_link.exists():
            return None
        target = self.config.previous_link.resolve()
        return self._release_from_dir(target)

    def _release_from_dir(self, release_dir: Path) -> InstalledRelease | None:
        metadata_path = self._metadata_path(release_dir)
        if metadata_path.exists():
            payload = read_json(metadata_path)
            return InstalledRelease(
                version=str(payload["version"]),
                path=release_dir,
                tree_sha256=str(payload["tree_sha256"]),
            )
        if release_dir.is_dir():
            tree_sha256 = directory_tree_sha256(release_dir, ignore_names={RELEASE_METADATA_NAME})
            return InstalledRelease(version=release_dir.name, path=release_dir, tree_sha256=tree_sha256)
        return None

    def _write_release_metadata(
        self,
        release_dir: Path,
        *,
        version: str,
        tree_sha256: str,
        artifact_kind: str,
        source_version: str | None,
    ) -> None:
        write_json_atomic(
            self._metadata_path(release_dir),
            {
                "version": version,
                "tree_sha256": tree_sha256,
                "artifact_kind": artifact_kind,
                "source_version": source_version,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _finalize_release(self, staging_dir: Path, version: str) -> Path:
        release_dir = self.config.releases_dir / version
        ensure_directory(self.config.releases_dir)
        if release_dir.exists():
            shutil.rmtree(release_dir, ignore_errors=True)
        staging_dir.replace(release_dir)
        return release_dir

    def _prepare_full_release(self, manifest: ReleaseManifest, artifact_path: Path) -> tuple[Path, str]:
        staging_dir = self.config.work_dir / f"{manifest.version}.full.{uuid4().hex}"
        ensure_directory(self.config.work_dir)
        safe_extract_tarball(artifact_path, staging_dir)
        tree_sha = directory_tree_sha256(staging_dir)
        expected = manifest.full_artifact.install_tree_sha256
        if expected and tree_sha != expected:
            raise InstallError(
                f"Full artifact tree checksum mismatch: expected {expected}, got {tree_sha}"
            )
        return staging_dir, tree_sha

    def _prepare_patch_release(
        self,
        current_release: InstalledRelease,
        patch_artifact: PatchArtifactRef,
        artifact_path: Path,
    ) -> tuple[Path, str]:
        eligible, reason = patch_is_eligible(
            current_release.version,
            current_release.tree_sha256,
            patch_artifact,
        )
        if not eligible:
            raise PatchError(reason)
        staging_dir = self.config.work_dir / f"{patch_artifact.to_version}.patch.{uuid4().hex}"
        ensure_directory(self.config.work_dir)
        tree_sha = apply_patch_archive(
            patch_archive=artifact_path,
            base_release_dir=current_release.path,
            staging_dir=staging_dir,
            patch_artifact=patch_artifact,
        )
        return staging_dir, tree_sha

    def _activate_release(
        self,
        new_release_dir: Path,
        *,
        previous_release: InstalledRelease | None,
        health_timeout_seconds: int,
    ) -> None:
        self._log("info", "Stopping service %s", self.config.service_name)
        self.service_controller.stop()
        run_hooks(self.runner, self.config.hooks.pre_install)
        if previous_release is not None:
            atomic_symlink_swap(self.config.previous_link, previous_release.path)
        atomic_symlink_swap(self.config.current_link, new_release_dir)
        self._log("info", "Starting service %s", self.config.service_name)
        self.service_controller.start()
        if self.config.hooks.health_check:
            run_hooks(self.runner, self.config.hooks.health_check, timeout_seconds=health_timeout_seconds)
        else:
            self.service_controller.health_check(health_timeout_seconds)
        run_hooks(self.runner, self.config.hooks.post_install)

    def _rollback_to_previous(
        self,
        previous_release: InstalledRelease | None,
        *,
        health_timeout_seconds: int,
    ) -> None:
        if previous_release is None:
            raise HealthCheckError("No previous release is available for rollback")
        self._log("warning", "Rolling back to %s", previous_release.version)
        self.service_controller.stop()
        atomic_symlink_swap(self.config.current_link, previous_release.path)
        self.service_controller.start()
        self.service_controller.health_check(health_timeout_seconds)
        run_hooks(self.runner, self.config.hooks.rollback)

    def apply_release(
        self,
        *,
        manifest: ReleaseManifest,
        artifact_path: Path,
        patch_artifact: PatchArtifactRef | None = None,
    ) -> InstallOutcome:
        ensure_directory(self.config.install_root)
        ensure_directory(self.config.releases_dir)
        ensure_directory(self.config.state_dir)
        ensure_directory(self.config.work_dir)

        previous_release = self.current_release()
        if patch_artifact:
            if previous_release is None:
                raise PatchError("Cannot apply a patch without an installed base release")
            self._log("info", "Preparing patch update from %s to %s", previous_release.version, manifest.version)
            staging_dir, tree_sha = self._prepare_patch_release(previous_release, patch_artifact, artifact_path)
            artifact_kind = "patch"
            source_version = previous_release.version
        else:
            self._log("info", "Preparing full update to %s", manifest.version)
            staging_dir, tree_sha = self._prepare_full_release(manifest, artifact_path)
            artifact_kind = "full"
            source_version = None

        release_dir = self._finalize_release(staging_dir, manifest.version)
        self._write_release_metadata(
            release_dir,
            version=manifest.version,
            tree_sha256=tree_sha,
            artifact_kind=artifact_kind,
            source_version=source_version,
        )

        try:
            self._activate_release(
                release_dir,
                previous_release=previous_release,
                health_timeout_seconds=manifest.rollback.health_check_timeout_seconds,
            )
        except Exception:
            self._rollback_to_previous(
                previous_release,
                health_timeout_seconds=manifest.rollback.health_check_timeout_seconds,
            )
            raise

        keep_paths = {release_dir}
        if previous_release:
            keep_paths.add(previous_release.path)
        prune_releases(
            self.config.releases_dir,
            keep_paths=keep_paths,
            retained_releases=max(self.config.retained_releases, manifest.rollback.keep_versions),
        )
        write_json_atomic(
            self.config.state_file,
            {
                "current_version": manifest.version,
                "current_release_path": str(release_dir),
                "previous_version": previous_release.version if previous_release else None,
                "previous_release_path": str(previous_release.path) if previous_release else None,
                "artifact_kind": artifact_kind,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return InstallOutcome(version=manifest.version, release_path=release_dir, artifact_kind=artifact_kind)

    def rollback(self, *, health_timeout_seconds: int = 20) -> InstallOutcome:
        current_release = self.current_release()
        previous_release = self.previous_release()
        if previous_release is None:
            raise InstallError("No previous release is available for rollback")
        self._log("warning", "Manual rollback from %s to %s", current_release.version if current_release else "unknown", previous_release.version)
        self.service_controller.stop()
        if current_release is not None:
            atomic_symlink_swap(self.config.previous_link, current_release.path)
        atomic_symlink_swap(self.config.current_link, previous_release.path)
        self.service_controller.start()
        if self.config.hooks.health_check:
            run_hooks(self.runner, self.config.hooks.health_check, timeout_seconds=health_timeout_seconds)
        else:
            self.service_controller.health_check(health_timeout_seconds)
        run_hooks(self.runner, self.config.hooks.rollback)
        write_json_atomic(
            self.config.state_file,
            {
                "current_version": previous_release.version,
                "current_release_path": str(previous_release.path),
                "previous_version": current_release.version if current_release else None,
                "previous_release_path": str(current_release.path) if current_release else None,
                "artifact_kind": "rollback",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return InstallOutcome(
            version=previous_release.version,
            release_path=previous_release.path,
            artifact_kind="rollback",
            rolled_back=True,
        )
