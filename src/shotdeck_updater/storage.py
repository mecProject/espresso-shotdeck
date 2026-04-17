"""Filesystem helpers for safe extraction, hashing, and atomic state updates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .errors import InstallError


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_tree_sha256(root: Path, *, ignore_names: set[str] | None = None) -> str:
    ignore_names = ignore_names or set()
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.name in ignore_names:
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            digest.update(f"dir:{relative}\n".encode("utf-8"))
            continue
        if path.is_symlink():
            raise InstallError(f"Symlinks are not allowed in release trees: {relative}")
        digest.update(f"file:{relative}\n".encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute():
        raise InstallError(f"Archive entry {name!r} is absolute")
    if ".." in relative.parts:
        raise InstallError(f"Archive entry {name!r} attempts path traversal")
    return relative


def safe_extract_tarball(archive_path: Path, destination: Path) -> None:
    ensure_directory(destination)
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            relative = _safe_relative_path(member.name)
            target = destination / relative
            if member.issym() or member.islnk():
                raise InstallError(f"Archive contains unsupported link entry: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise InstallError(f"Archive contains unsupported member type: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise InstallError(f"Could not extract archive member {member.name}")
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            os.chmod(target, member.mode & 0o777)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    with NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_symlink_swap(link_path: Path, target_path: Path) -> None:
    ensure_directory(link_path.parent)
    temp_link = link_path.with_name(f".{link_path.name}.tmp")
    if temp_link.exists() or temp_link.is_symlink():
        temp_link.unlink()
    temp_link.symlink_to(target_path)
    os.replace(temp_link, link_path)


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, symlinks=False)


def prune_releases(releases_dir: Path, *, keep_paths: set[Path], retained_releases: int) -> None:
    if not releases_dir.exists():
        return
    candidates = sorted(
        [item for item in releases_dir.iterdir() if item.is_dir()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    protected = {path.resolve() for path in keep_paths if path.exists()}
    kept = 0
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in protected:
            kept += 1
            continue
        if kept < retained_releases:
            kept += 1
            continue
        shutil.rmtree(candidate, ignore_errors=True)
