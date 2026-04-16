"""Network and checksum-safe downloading for manifests, allowlists, and artifacts."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from .errors import DownloadError
from .storage import ensure_directory, sha256_file


def fetch_bytes(url: str, *, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "shotdeck-updater/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise DownloadError(f"Failed to fetch {url}: {exc}") from exc


def fetch_json(url: str, *, timeout: int = 60) -> dict[str, object]:
    try:
        return json.loads(fetch_bytes(url, timeout=timeout).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise DownloadError(f"Remote JSON at {url} is invalid: {exc}") from exc


def download_to_path(
    url: str,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int | None = None,
    timeout: int = 60,
) -> Path:
    ensure_directory(destination.parent)
    if destination.exists() and sha256_file(destination) == expected_sha256:
        if expected_size is None or destination.stat().st_size == expected_size:
            return destination
    temp_path = destination.with_suffix(destination.suffix + ".part")
    if temp_path.exists():
        temp_path.unlink()

    request = urllib.request.Request(url, headers={"User-Agent": "shotdeck-updater/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, temp_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise DownloadError(f"Failed to download {url}: {exc}") from exc

    if expected_size is not None and temp_path.stat().st_size != expected_size:
        temp_path.unlink(missing_ok=True)
        raise DownloadError(
            f"Downloaded artifact size mismatch for {url}: expected {expected_size}, got {temp_path.stat().st_size}"
        )
    actual_sha256 = sha256_file(temp_path)
    if actual_sha256 != expected_sha256:
        temp_path.unlink(missing_ok=True)
        raise DownloadError(
            f"Downloaded artifact checksum mismatch for {url}: expected {expected_sha256}, got {actual_sha256}"
        )
    os.replace(temp_path, destination)
    return destination
