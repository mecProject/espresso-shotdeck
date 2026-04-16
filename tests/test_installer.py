from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from shotdeck_manifest import ArtifactRef, ReleaseManifest, RollbackInfo, RolloutRules
from shotdeck_updater.config import UpdaterConfig
from shotdeck_updater.errors import HealthCheckError
from shotdeck_updater.installer import RELEASE_METADATA_NAME, ReleaseInstaller
from shotdeck_updater.storage import directory_tree_sha256, write_json_atomic


class FakeServiceController:
    def __init__(self, *, fail_first_health_check: bool = False) -> None:
        self.fail_first_health_check = fail_first_health_check
        self.health_calls = 0

    def stop(self) -> None:
        return None

    def start(self) -> None:
        return None

    def health_check(self, timeout_seconds: int) -> None:
        self.health_calls += 1
        if self.fail_first_health_check and self.health_calls == 1:
            raise HealthCheckError("simulated failure")


def _write_release(root: Path, version: str, files: dict[str, bytes]) -> Path:
    release_dir = root / "releases" / version
    release_dir.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        target = release_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    tree_sha = directory_tree_sha256(release_dir)
    write_json_atomic(
        release_dir / RELEASE_METADATA_NAME,
        {"version": version, "tree_sha256": tree_sha, "artifact_kind": "full", "source_version": None},
    )
    return release_dir


def _make_tarball(source_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in sorted(source_dir.rglob("*")):
            archive.add(path, arcname=path.relative_to(source_dir).as_posix(), recursive=False)


def test_installer_rolls_back_on_failed_health_check(tmp_path) -> None:
    install_root = tmp_path / "opt" / "shotdeck"
    config = UpdaterConfig(install_root=install_root, manifest_url="https://example.com/manifest.json")
    old_release = _write_release(install_root, "1.0.0", {"shotdeck": b"old"})
    config.current_link.parent.mkdir(parents=True, exist_ok=True)
    config.current_link.symlink_to(old_release)
    config.previous_link.symlink_to(old_release)

    new_tree = tmp_path / "new-tree"
    new_tree.mkdir()
    (new_tree / "shotdeck").write_bytes(b"new")
    archive_path = tmp_path / "shotdeck-1.1.0-full.tar.gz"
    _make_tarball(new_tree, archive_path)
    tree_sha = directory_tree_sha256(new_tree)
    manifest = ReleaseManifest(
        schema_version="1.0",
        product="shotdeck",
        channel="stable",
        version="1.1.0",
        released_at="2026-04-15T12:00:00Z",
        min_updater_version="0.1.0",
        full_artifact=ArtifactRef(
            url="https://updates.example.com/shotdeck-1.1.0-full.tar.gz",
            sha256="a" * 64,
            size=archive_path.stat().st_size,
            filename="shotdeck-1.1.0-full.tar.gz",
            install_tree_sha256=tree_sha,
        ),
        rollout=RolloutRules(),
        rollback=RollbackInfo(),
    )

    installer = ReleaseInstaller(
        config,
        service_controller=FakeServiceController(fail_first_health_check=True),
    )
    with pytest.raises(HealthCheckError):
        installer.apply_release(manifest=manifest, artifact_path=archive_path)

    assert config.current_link.resolve() == old_release.resolve()


def test_manual_rollback_switches_back_to_previous_release(tmp_path) -> None:
    install_root = tmp_path / "opt" / "shotdeck"
    config = UpdaterConfig(install_root=install_root, manifest_url="https://example.com/manifest.json")
    old_release = _write_release(install_root, "1.0.0", {"shotdeck": b"old"})
    new_release = _write_release(install_root, "1.1.0", {"shotdeck": b"new"})
    config.current_link.parent.mkdir(parents=True, exist_ok=True)
    config.current_link.symlink_to(new_release)
    config.previous_link.symlink_to(old_release)

    installer = ReleaseInstaller(config, service_controller=FakeServiceController())
    outcome = installer.rollback()
    assert outcome.rolled_back is True
    assert config.current_link.resolve() == old_release.resolve()
