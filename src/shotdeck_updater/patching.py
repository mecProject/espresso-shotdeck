"""Patch generation and application for overlay-style release updates."""

from __future__ import annotations

import io
import json
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

from shotdeck_manifest import PatchArtifactRef

from .errors import PatchError
from .storage import copy_tree, directory_tree_sha256, safe_extract_tarball, sha256_file


PATCH_PLAN_NAME = "patch-plan.json"


@dataclass(slots=True)
class PatchBuildMetadata:
    removed_paths: list[str]
    base_tree_sha256: str
    target_tree_sha256: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "removed_paths": list(self.removed_paths),
            "base_tree_sha256": self.base_tree_sha256,
            "target_tree_sha256": self.target_tree_sha256,
            "sha256": self.sha256,
            "size": self.size,
        }


def patch_is_eligible(
    current_version: str,
    current_tree_sha256: str,
    patch_artifact: PatchArtifactRef,
) -> tuple[bool, str]:
    if patch_artifact.from_version != current_version:
        return False, "patch base version does not match the installed version"
    if patch_artifact.base_tree_sha256 != current_tree_sha256:
        return False, "patch base tree checksum does not match the installed release"
    return True, "patch is eligible"


def _build_file_map(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink():
            raise PatchError(f"Symlinks are not supported in patch trees: {path}")
        mapping[path.relative_to(root).as_posix()] = sha256_file(path)
    return mapping


def build_patch_archive(base_dir: Path, target_dir: Path, output_path: Path) -> PatchBuildMetadata:
    base_map = _build_file_map(base_dir)
    target_map = _build_file_map(target_dir)
    removed_paths = sorted(set(base_map) - set(target_map))
    changed_paths = sorted(
        path for path, digest in target_map.items() if base_map.get(path) != digest
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output_path, "w:gz") as archive:
        plan_bytes = json.dumps(
            {"removed_paths": removed_paths, "changed_paths": changed_paths},
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        plan_info = tarfile.TarInfo(PATCH_PLAN_NAME)
        plan_info.size = len(plan_bytes)
        archive.addfile(plan_info, io.BytesIO(plan_bytes))
        for relative in changed_paths:
            archive.add(target_dir / relative, arcname=relative, recursive=False)

    return PatchBuildMetadata(
        removed_paths=removed_paths,
        base_tree_sha256=directory_tree_sha256(base_dir),
        target_tree_sha256=directory_tree_sha256(target_dir),
        sha256=sha256_file(output_path),
        size=output_path.stat().st_size,
    )


def _copy_overlay(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if relative.as_posix() == PATCH_PLAN_NAME:
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def apply_patch_archive(
    *,
    patch_archive: Path,
    base_release_dir: Path,
    staging_dir: Path,
    patch_artifact: PatchArtifactRef,
) -> str:
    copy_tree(base_release_dir, staging_dir)
    overlay_dir = staging_dir.parent / f"{staging_dir.name}.overlay"
    if overlay_dir.exists():
        shutil.rmtree(overlay_dir)
    safe_extract_tarball(patch_archive, overlay_dir)

    for removed in patch_artifact.removed_paths:
        target = staging_dir / removed
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    _copy_overlay(overlay_dir, staging_dir)
    shutil.rmtree(overlay_dir, ignore_errors=True)

    actual_tree_sha = directory_tree_sha256(staging_dir)
    if actual_tree_sha != patch_artifact.target_tree_sha256:
        raise PatchError(
            "Patched release tree checksum mismatch: "
            f"expected {patch_artifact.target_tree_sha256}, got {actual_tree_sha}"
        )
    return actual_tree_sha
