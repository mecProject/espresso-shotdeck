from __future__ import annotations

from pathlib import Path

from shotdeck_manifest import PatchArtifactRef
from shotdeck_updater.patching import apply_patch_archive, build_patch_archive, patch_is_eligible


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative, data in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def test_patch_build_and_apply(tmp_path) -> None:
    base_dir = tmp_path / "base"
    target_dir = tmp_path / "target"
    staging_dir = tmp_path / "staging"
    _write_tree(base_dir, {"shotdeck": b"v1", "assets/a.txt": b"old", "remove.me": b"x"})
    _write_tree(target_dir, {"shotdeck": b"v2", "assets/a.txt": b"new", "assets/b.txt": b"added"})

    patch_path = tmp_path / "update.patch.tar.gz"
    metadata = build_patch_archive(base_dir, target_dir, patch_path)
    patch = PatchArtifactRef(
        url="https://updates.example.com/update.patch.tar.gz",
        sha256=metadata.sha256,
        size=metadata.size,
        filename="update.patch.tar.gz",
        install_tree_sha256=metadata.target_tree_sha256,
        from_version="1.0.0",
        to_version="1.1.0",
        base_tree_sha256=metadata.base_tree_sha256,
        target_tree_sha256=metadata.target_tree_sha256,
        removed_paths=metadata.removed_paths,
    )

    eligible, _ = patch_is_eligible("1.0.0", metadata.base_tree_sha256, patch)
    assert eligible is True
    tree_sha = apply_patch_archive(
        patch_archive=patch_path,
        base_release_dir=base_dir,
        staging_dir=staging_dir,
        patch_artifact=patch,
    )
    assert tree_sha == metadata.target_tree_sha256
    assert (staging_dir / "shotdeck").read_bytes() == b"v2"
    assert not (staging_dir / "remove.me").exists()
