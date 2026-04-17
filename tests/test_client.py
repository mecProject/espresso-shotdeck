from __future__ import annotations

from pathlib import Path

import pytest

from shotdeck_manifest import ArtifactRef, ReleaseManifest, RollbackInfo, RolloutRules
from shotdeck_updater.client import UpdaterClient
from shotdeck_updater.config import UpdaterConfig
from shotdeck_updater.errors import DownloadError


def _manifest_payload(version: str = "1.0.0") -> dict[str, object]:
    manifest = ReleaseManifest(
        schema_version="1.0",
        product="shotdeck",
        channel="stable",
        version=version,
        released_at="2026-04-17T00:00:00Z",
        min_updater_version="0.1.0",
        full_artifact=ArtifactRef(
            url="https://updates.example.com/artifacts/shotdeck-1.0.0-full.tar.gz",
            sha256="a" * 64,
            size=123,
            filename="shotdeck-1.0.0-full.tar.gz",
            install_tree_sha256="b" * 64,
        ),
        rollout=RolloutRules(),
        rollback=RollbackInfo(),
    )
    return manifest.to_dict()


def test_client_uses_next_manifest_url_when_primary_fetch_fails(monkeypatch, tmp_path: Path) -> None:
    config = UpdaterConfig(
        manifest_url="https://old.example.com/metadata/shotdeck-stable.json",
        next_manifest_url="https://new.example.com/metadata/shotdeck-stable.json",
        public_key_path=tmp_path / "update-signing-key.pem",
    )
    config.public_key_path.write_text("public-key", encoding="utf-8")
    client = UpdaterClient(config)

    requested_urls: list[str] = []

    def fake_fetch_json(url: str, *, timeout: int = 60) -> dict[str, object]:
        requested_urls.append(url)
        if "old.example.com" in url:
            raise DownloadError(f"Failed to fetch {url}: HTTP Error 404: Not Found")
        return _manifest_payload(version="1.0.2")

    monkeypatch.setattr("shotdeck_updater.client.fetch_json", fake_fetch_json)
    monkeypatch.setattr("shotdeck_updater.client.verify_manifest", lambda manifest, public_key: None)

    manifest = client._load_manifest()

    assert manifest.version == "1.0.2"
    assert requested_urls == [
        "https://old.example.com/metadata/shotdeck-stable.json",
        "https://new.example.com/metadata/shotdeck-stable.json",
    ]


def test_client_raises_download_error_when_all_manifest_urls_fail(monkeypatch, tmp_path: Path) -> None:
    config = UpdaterConfig(
        manifest_url="https://old.example.com/metadata/shotdeck-stable.json",
        next_manifest_url="https://new.example.com/metadata/shotdeck-stable.json",
        public_key_path=tmp_path / "update-signing-key.pem",
    )
    config.public_key_path.write_text("public-key", encoding="utf-8")
    client = UpdaterClient(config)

    def fake_fetch_json(url: str, *, timeout: int = 60) -> dict[str, object]:
        raise DownloadError(f"Failed to fetch {url}: HTTP Error 404: Not Found")

    monkeypatch.setattr("shotdeck_updater.client.fetch_json", fake_fetch_json)
    monkeypatch.setattr("shotdeck_updater.client.verify_manifest", lambda manifest, public_key: None)

    with pytest.raises(DownloadError, match="new.example.com"):
        client._load_manifest()
