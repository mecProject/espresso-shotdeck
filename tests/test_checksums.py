from __future__ import annotations

import hashlib

import pytest

from shotdeck_updater.download import download_to_path
from shotdeck_updater.errors import DownloadError


def test_download_to_path_validates_checksum(tmp_path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"shotdeck")
    destination = tmp_path / "cache.bin"
    sha = hashlib.sha256(b"shotdeck").hexdigest()
    downloaded = download_to_path(source.as_uri(), destination, expected_sha256=sha, expected_size=8)
    assert downloaded.read_bytes() == b"shotdeck"


def test_download_to_path_rejects_bad_checksum(tmp_path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"shotdeck")
    destination = tmp_path / "cache.bin"
    with pytest.raises(DownloadError):
        download_to_path(source.as_uri(), destination, expected_sha256="0" * 64, expected_size=8)
